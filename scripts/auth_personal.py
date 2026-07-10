#!/usr/bin/env python3
"""One-time OAuth2 flow for personal Google account (you@example.com).

Run once interactively to capture a refresh token with all needed scopes.
Saves to ~/.openclaw/scripts/personal-token.json.

Usage:
    ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/auth_personal.py
"""

import json
import os
from pathlib import Path

os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

from google_auth_oauthlib.flow import InstalledAppFlow

CREDENTIALS_DIR = Path.home() / ".openclaw" / "credentials" / "google"
CLIENT_SECRETS_FILE = CREDENTIALS_DIR / "personal-gmail-oauth-client.json"
TOKEN_FILE = Path.home() / ".openclaw" / "scripts" / "personal-token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]


def main():
    if not CLIENT_SECRETS_FILE.exists():
        raise SystemExit(f"Missing client secrets: {CLIENT_SECRETS_FILE}")

    print(f"Starting OAuth flow for personal account (you@example.com)")
    print(f"Scopes: {len(SCOPES)}")
    for s in SCOPES:
        print(f"  - {s.split('/')[-1]}")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        "expiry": creds.expiry.isoformat() + "Z" if creds.expiry else None,
    }

    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    print(f"\nToken saved to: {TOKEN_FILE}")
    print("This token will auto-refresh indefinitely (unless revoked in Google Account settings).")


if __name__ == "__main__":
    main()
