#!/usr/bin/env python3
"""Personal Gmail poller — sealed pipeline for you@example.com.

Polls personal inbox every 5 minutes (via launchd), applies a deterministic
importance filter, and posts surviving messages to the gateway hook at
/hooks/personal-gmail. The gateway then runs the LLM, drafts a reply in Gmail,
and notifies via Telegram.

This is the SOLE authorized reader/writer of ckane703 in Atlas's stack.
All other tools must continue defaulting to support@brand75.com.

Usage:
    ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/personal_gmail_poller.py
"""

import json
import os
import re
import sys
import time
import urllib.request
from email.utils import parseaddr
from pathlib import Path

from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).parent))
import google_auth

STATE_FILE = Path.home() / ".openclaw" / "state" / "personal_gmail_last_seen.json"
CONTACTS_FILE = Path.home() / ".openclaw" / "state" / "personal_contacts.json"
CONTACTS_REFRESH_DAYS = 7

GATEWAY_HOOK_URL = "http://127.0.0.1:18789/hooks/personal-gmail"
HOOK_BEARER_TOKEN = "REDACTED_SET_VIA_ENV"

POLL_LOOKBACK_MIN = 15

BULK_DOMAINS = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "pinterest.com", "tiktok.com", "youtube.com", "medium.com", "substack.com",
    "mailchimp.com", "sendgrid.net", "constantcontact.com", "hubspot.com",
)
NOREPLY_PATTERNS = re.compile(
    r"^(no[\-_\.]?reply|notifications?|alerts?|updates?|news|info|donotreply|"
    r"system|automated|mailer|bounce)@",
    re.IGNORECASE,
)
TWO_FA_SUBJECT = re.compile(
    r"\b(verification code|security code|2fa code|sign[- ]?in attempt|"
    r"one[- ]?time (code|password|pin|passcode)|otp|login code|"
    r"your code is|access code|confirmation code)\b",
    re.IGNORECASE,
)
IMPORTANT_KEYWORDS = re.compile(
    r"\b(invoice|payment|legal|medical|prescription|appointment|"
    r"contract|signed|signature|deposition|hearing|court|tax|irs|refund)\b",
    re.IGNORECASE,
)
PROMO_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"}


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def build_contacts(service) -> set[str]:
    """Build allowlist from sent-folder recipients in last 90 days."""
    contacts = set()
    page_token = None
    cutoff_query = "in:sent newer_than:90d"
    while True:
        resp = service.users().messages().list(
            userId="me", q=cutoff_query, pageToken=page_token, maxResults=100
        ).execute()
        for m in resp.get("messages", []):
            msg = service.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["To", "Cc"],
            ).execute()
            for h in msg.get("payload", {}).get("headers", []):
                if h["name"] in ("To", "Cc"):
                    for addr_part in h["value"].split(","):
                        _, addr = parseaddr(addr_part)
                        if addr and "@" in addr:
                            contacts.add(addr.lower())
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return contacts


def get_contacts(service) -> set[str]:
    """Cached contacts allowlist; refreshes weekly."""
    now = time.time()
    if CONTACTS_FILE.exists():
        cache = json.loads(CONTACTS_FILE.read_text())
        if now - cache.get("built_at", 0) < CONTACTS_REFRESH_DAYS * 86400:
            return set(cache.get("contacts", []))
    contacts = build_contacts(service)
    CONTACTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps({
        "built_at": now,
        "contacts": sorted(contacts),
    }, indent=2))
    return contacts


def get_header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def extract_body(payload: dict) -> str:
    """Recursively extract text/plain body, with text/html fallback."""
    import base64
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        sub = extract_body(part)
        if sub:
            return sub
    return ""


def should_notify(msg: dict, contacts: set[str]) -> tuple[bool, str]:
    """Apply importance filter. Returns (allow, reason)."""
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])
    label_ids = set(msg.get("labelIds", []))

    from_header = get_header(payload, "From")
    _, sender_addr = parseaddr(from_header)
    sender_addr = sender_addr.lower()
    sender_domain = sender_addr.split("@")[-1] if "@" in sender_addr else ""

    subject = get_header(payload, "Subject")
    list_unsub = get_header(payload, "List-Unsubscribe")

    if TWO_FA_SUBJECT.search(subject):
        return True, "2fa-or-security-code"

    if list_unsub:
        return False, "has-list-unsubscribe"
    if NOREPLY_PATTERNS.search(sender_addr):
        return False, "noreply-sender"
    if any(sender_domain.endswith(d) for d in BULK_DOMAINS):
        return False, f"bulk-domain:{sender_domain}"
    if label_ids & PROMO_LABELS:
        return False, f"category-label:{(label_ids & PROMO_LABELS).pop()}"

    if sender_addr in contacts:
        return True, "known-contact"
    if sender_domain.endswith(".gov") or sender_domain.endswith(".us"):
        return True, "gov-domain"
    if IMPORTANT_KEYWORDS.search(subject):
        return True, f"important-keyword:{subject[:40]}"

    return True, "primary-tab-default"


def post_to_hook(msg_payload: dict) -> tuple[int, str]:
    body = json.dumps({"messages": [msg_payload]}).encode("utf-8")
    req = urllib.request.Request(
        GATEWAY_HOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {HOOK_BEARER_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:300]
    except Exception as e:
        return -1, str(e)


def main():
    state = load_state()
    last_seen_ms = int(state.get("last_seen_internal_date_ms", 0))

    creds = google_auth.get_personal_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    contacts = get_contacts(service)

    lookback_query = f"in:inbox is:unread newer_than:{POLL_LOOKBACK_MIN}m"
    list_resp = service.users().messages().list(
        userId="me", q=lookback_query, maxResults=50
    ).execute()

    msgs = list_resp.get("messages", [])
    processed = []
    new_max_ms = last_seen_ms

    for ref in msgs:
        msg = service.users().messages().get(
            userId="me", id=ref["id"], format="full"
        ).execute()
        internal_ms = int(msg.get("internalDate", 0))
        if internal_ms <= last_seen_ms:
            continue
        if internal_ms > new_max_ms:
            new_max_ms = internal_ms

        allow, reason = should_notify(msg, contacts)
        payload = msg.get("payload", {})
        from_h = get_header(payload, "From")
        subject = get_header(payload, "Subject")

        entry = {
            "id": msg["id"],
            "threadId": msg.get("threadId"),
            "from": from_h,
            "subject": subject,
            "filter_reason": reason,
            "delivered": False,
        }

        if allow:
            body = extract_body(payload)[:20000]
            payload_for_hook = {
                "from": from_h,
                "subject": subject,
                "threadId": msg.get("threadId"),
                "body": body,
            }
            status, resp_text = post_to_hook(payload_for_hook)
            entry["hook_status"] = status
            entry["delivered"] = (200 <= status < 300)
            if not entry["delivered"]:
                entry["hook_response"] = resp_text

        processed.append(entry)
        print(json.dumps(entry), flush=True)

    if new_max_ms > last_seen_ms:
        state["last_seen_internal_date_ms"] = new_max_ms
        state["last_run_iso"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        state["last_run_processed"] = len(processed)
        save_state(state)

    print(json.dumps({
        "summary": "ok",
        "polled": len(msgs),
        "processed": len(processed),
        "delivered": sum(1 for e in processed if e["delivered"]),
        "filtered": sum(1 for e in processed if not e["delivered"]),
        "last_seen_ms": new_max_ms,
    }), flush=True)


if __name__ == "__main__":
    main()
