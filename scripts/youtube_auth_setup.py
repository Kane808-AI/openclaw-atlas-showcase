#!/Users/chriskaneshiro/.openclaw/venv/google/bin/python3
"""
youtube_auth_setup.py — One-time OAuth2 setup for YouTube Data API v3.

Run this interactively to generate:
    ~/.openclaw/credentials/google/youtube-token.json

Prerequisites (do these in Google Cloud Console first):
  1. Go to APIs & Services → Library → enable "YouTube Data API v3"
  2. Go to APIs & Services → Credentials → your OAuth 2.0 Client
     (personal-gmail-oauth-client.json) → ensure you@example.com
     is listed as a test user if the app is in "Testing" mode.
  3. If the consent screen is in "Testing" mode, add
     you@example.com under OAuth consent screen → Test users.

Usage:
    /opt/homebrew/bin/python3 ~/.openclaw/scripts/youtube_auth_setup.py
"""

import json
import sys
from pathlib import Path

CLIENT_FILE = Path.home() / ".openclaw" / "credentials" / "google" / "personal-gmail-oauth-client.json"
TOKEN_FILE = Path.home() / ".openclaw" / "credentials" / "google" / "youtube-token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube",            # upload, playlists, channel management
    "https://www.googleapis.com/auth/youtube.force-ssl",  # required for commentThreads.list
    "https://www.googleapis.com/auth/youtube.readonly",   # read-only fallback path
]


def main():
    # Verify client file exists before starting
    if not CLIENT_FILE.exists():
        print(f"ERROR: OAuth client file not found: {CLIENT_FILE}")
        print("Download from Google Cloud Console → Credentials → OAuth 2.0 Client IDs")
        sys.exit(1)

    # Check if token already valid
    if TOKEN_FILE.exists():
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            with open(TOKEN_FILE) as f:
                tok = json.load(f)
            with open(CLIENT_FILE) as f:
                cli = json.load(f)["installed"]

            creds = Credentials(
                token=tok.get("token"),
                refresh_token=tok.get("refresh_token"),
                token_uri=tok.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=cli["client_id"],
                client_secret=cli["client_secret"],
                scopes=tok.get("scopes", SCOPES),
            )

            if creds.valid:
                print(f"Token already valid at {TOKEN_FILE}")
                print("Nothing to do. Delete the token file to force re-auth.")
                return

            if creds.expired and creds.refresh_token:
                print("Token expired — refreshing...")
                creds.refresh(Request())
                _save(creds)
                print(f"Token refreshed and saved to {TOKEN_FILE}")
                return
        except Exception as e:
            print(f"Existing token unusable ({e}) — starting fresh OAuth flow.")

    # Run the browser-based OAuth flow
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed.")
        print("Run: /opt/homebrew/bin/pip3 install google-auth-oauthlib")
        sys.exit(1)

    print("Opening browser for Google OAuth authorization...")
    print(f"Sign in as: you@example.com")
    print(f"Scopes requested: {SCOPES}")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    _save(creds)
    print(f"\nYouTube OAuth token saved: {TOKEN_FILE}")
    print("The YouTube Shorts pipeline is now authorized to upload.")


def _save(creds):
    from google.oauth2.credentials import Credentials
    tok = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    if creds.expiry:
        tok["expiry"] = creds.expiry.isoformat() + "Z"
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f, indent=2)


if __name__ == "__main__":
    main()
