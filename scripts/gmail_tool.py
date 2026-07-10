#!/usr/bin/env python3
"""Gmail tool for Atlas — search, list, read, and draft emails."""
import argparse
import base64
import json
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials, get_personal_credentials

from googleapiclient.discovery import build

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def load_credentials(account: str):
    if account == "brand75":
        return get_brand75_credentials(GMAIL_SCOPES)
    elif account == "personal":
        return get_personal_credentials()
    else:
        raise ValueError(f"Unknown account: {account}")

def parse_message(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    return {
        "id": msg["id"],
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", ""),
    }

def action_list(service, max_results: int) -> list:
    result = service.users().messages().list(userId="me", maxResults=max_results).execute()
    messages = result.get("messages", [])
    return [{"id": m["id"], "threadId": m["threadId"]} for m in messages]

def action_search(service, query: str, max_results: int) -> list:
    result = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    messages = result.get("messages", [])
    output = []
    for m in messages:
        msg = service.users().messages().get(userId="me", id=m["id"], format="metadata",
              metadataHeaders=["From","To","Subject","Date"]).execute()
        output.append(parse_message(msg))
    return output

def _extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace") if data else ""
    parts = payload.get("parts", [])
    for part in parts:
        text = _extract_body(part)
        if text:
            return text
    return ""

def action_read(service, message_id: str) -> dict:
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    result = parse_message(msg)
    result["body"] = _extract_body(msg.get("payload", {}))
    return result

def action_draft(service, to: str, subject: str, body: str, thread_id: str = "", account: str = "brand75") -> dict:
    user_id = "automation@example.com" if account == "brand75" else "me"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    msg = MIMEText(body)
    msg["to"] = to
    msg["subject"] = subject
    msg["from"] = user_id
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft_body = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id
    draft = service.users().drafts().create(userId=user_id, body=draft_body).execute()
    return {"ok": True, "draftId": draft["id"], "threadId": thread_id}


def main():
    parser = argparse.ArgumentParser(description="Gmail tool for Atlas")
    parser.add_argument("--account", required=True, choices=["brand75", "personal"])
    parser.add_argument("--action", required=True, choices=["search", "list", "read", "draft"])
    parser.add_argument("--query", default="")
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--id", dest="message_id", default="")
    parser.add_argument("--to", default="")
    parser.add_argument("--subject", default="")
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--stdin", action="store_true", help="Read body from stdin")
    args = parser.parse_args()
    try:
        creds = load_credentials(args.account)
        service = build("gmail", "v1", credentials=creds)
        if args.action == "list":
            result = action_list(service, args.max)
        elif args.action == "search":
            if not args.query:
                print(json.dumps({"error": "--query required for search"}))
                sys.exit(1)
            result = action_search(service, args.query, args.max)
        elif args.action == "read":
            if not args.message_id:
                print(json.dumps({"error": "--id required for read"}))
                sys.exit(1)
            result = action_read(service, args.message_id)
        elif args.action == "draft":
            if not args.to or not args.subject:
                print(json.dumps({"error": "--to and --subject required for draft"}))
                sys.exit(1)
            body = sys.stdin.read() if args.stdin else ""
            if not body:
                print(json.dumps({"error": "Body required — use --stdin"}))
                sys.exit(1)
            result = action_draft(service, args.to, args.subject, body, args.thread_id, args.account)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
