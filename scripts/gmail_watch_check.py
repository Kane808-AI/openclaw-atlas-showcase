#!/usr/bin/env python3
"""Gmail watch health check — headless replacement for gog CLI watch commands.

Checks Gmail push notification watch status and renews/creates as needed.
Uses google_auth.py for authentication (no TTY/keyring dependency).

Usage:
    python3 gmail_watch_check.py
    Exit code 0 = all watches OK, non-zero = at least one failure.
    Outputs JSON: {"results": [{"account": ..., "status": "ok"|"renewed"|"started"|"failed", "detail": ...}]}
"""

import json
import sys
from pathlib import Path

from googleapiclient.discovery import build

# Ensure scripts dir is on path for google_auth import
sys.path.insert(0, str(Path(__file__).parent))
import google_auth

ACCOUNTS = [
    {
        "label": "ckane703",
        "email": "you@example.com",
        "get_creds": google_auth.get_personal_credentials,
        "topic": "projects/primeval-proton-487909-k9/topics/gog-gmail-watch",
    },
    {
        "label": "Brand75",
        "email": "support@brand75.com",
        "get_creds": google_auth.get_brand75_credentials,
        "topic": "projects/openclaw-brand75-488404/topics/gog-gmail-watch",
    },
]


def check_and_renew_watch(account: dict) -> dict:
    """Check Gmail watch for an account, renew if missing/expired."""
    label = account["label"]
    try:
        creds = account["get_creds"]()
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        # Gmail API doesn't have a "get watch status" endpoint.
        # The only way to ensure a watch is active is to call watch() —
        # it's idempotent and returns the current expiration if already active.
        result = service.users().watch(
            userId="me",
            body={
                "topicName": account["topic"],
                "labelIds": ["INBOX"],
            },
        ).execute()

        expiration = result.get("expiration", "unknown")
        return {
            "account": label,
            "status": "ok",
            "detail": f"Watch active, expires {expiration}",
        }

    except Exception as e:
        return {
            "account": label,
            "status": "failed",
            "detail": str(e),
        }


def main():
    results = [check_and_renew_watch(acct) for acct in ACCOUNTS]
    failures = [r for r in results if r["status"] == "failed"]

    # Output JSON for the watchdog to parse
    print(json.dumps({"results": results}))

    if failures:
        # Print human-readable failures to stderr for logging
        for f in failures:
            print(f"FAIL: {f['account']} — {f['detail']}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
