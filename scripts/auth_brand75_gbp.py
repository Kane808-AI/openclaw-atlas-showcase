#!/usr/bin/env python3
"""One-time OAuth2 consent flow to mint a Brand75 GBP token for support@brand75.com.

Run once in a terminal with browser access. The resulting token is stored at
~/.openclaw/credentials/google/brand75-gbp-token.json and auto-refreshed by
google_auth.get_brand75_gbp_credentials() on every subsequent use.

Prerequisites:
  - brand75-gmail-oauth-client.json must exist in ~/.openclaw/credentials/google/
  - The GCP project must have the Google My Business APIs enabled
  - The OAuth consent screen must list https://www.googleapis.com/auth/business.manage
    as an authorized scope (or the app must be in testing mode with support@brand75.com
    as a test user)

Usage:
  ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/auth_brand75_gbp.py
"""

import json
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

CREDENTIALS_DIR = Path.home() / ".openclaw" / "credentials" / "google"
CLIENT_SECRETS_FILE = CREDENTIALS_DIR / "brand75-gmail-oauth-client.json"
TOKEN_FILE = CREDENTIALS_DIR / "brand75-gbp-token.json"

GBP_SCOPE = "https://www.googleapis.com/auth/business.manage"


def main():
    if not CLIENT_SECRETS_FILE.exists():
        raise SystemExit(f"OAuth client file not found: {CLIENT_SECRETS_FILE}")

    print("Starting Brand75 GBP OAuth flow...")
    print(f"Scope: {GBP_SCOPE}")
    print(f"Account: support@brand75.com (sign in as this account when the browser opens)\n")

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), [GBP_SCOPE])
    creds = flow.run_local_server(port=0)

    token_data = json.loads(creds.to_json())
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    TOKEN_FILE.chmod(0o600)

    print(f"\nSuccess — token saved to: {TOKEN_FILE}")
    print("Test with: ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/gbp_tool.py --account brand75 accounts")


if __name__ == "__main__":
    main()
