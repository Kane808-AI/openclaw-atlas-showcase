#!/usr/bin/env python3
"""Re-authorize personal Google account (you@example.com) with full scopes.

Run this, follow the browser link, paste the auth code back.
"""
import json
import os
import socket
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCRIPT_DIR = Path.home() / ".openclaw" / "scripts"
CREDENTIALS_DIR = Path.home() / ".openclaw" / "credentials" / "google"

CLIENT_FILE = CREDENTIALS_DIR / "personal-gmail-oauth-client.json"
TOKEN_FILE = SCRIPT_DIR / "personal-token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
]

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), scopes=SCOPES)
creds = flow.run_local_server(port=0, open_browser=True)

token_data = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri": creds.token_uri,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "scopes": creds.scopes,
    "expiry": creds.expiry.isoformat() if creds.expiry else None,
}

TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(TOKEN_FILE, "w") as f:
    json.dump(token_data, f, indent=2)

print(f"\n✅ Token saved to {TOKEN_FILE}")
print(f"Scopes: {creds.scopes}")
