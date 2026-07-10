#!/usr/bin/env python3
"""
Pinterest OAuth2 Authorization Flow (manual callback version)
Run once to get tokens. Saves to ~/.openclaw/credentials/pinterest/token.json
"""

import urllib.parse
import requests
import json
import sys
from pathlib import Path

CLIENT_ID = "1557764"
REDIRECT_URI = "http://localhost:8080/callback"
SCOPES = "boards:read,boards:write,pins:read,pins:write,user_accounts:read"
TOKEN_PATH = Path.home() / ".openclaw/credentials/pinterest/token.json"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 pinterest_oauth.py <client_secret>")
        sys.exit(1)

    client_secret = sys.argv[1]

    auth_url = (
        f"https://www.pinterest.com/oauth/"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(SCOPES, safe='')}"
    )

    print("\n=== Pinterest OAuth2 Setup ===\n")
    print("Step 1: Open this URL in your browser:\n")
    print(auth_url)
    print("\nStep 2: Click 'Give access' on the Pinterest page.")
    print("Step 3: Your browser will try to load localhost:8080 (it will fail — that's fine).")
    print("Step 4: Copy the FULL URL from your browser address bar and paste it here.\n")

    redirect_url = input("Paste the redirect URL here: ").strip()

    parsed = urllib.parse.urlparse(redirect_url)
    params = urllib.parse.parse_qs(parsed.query)

    if "code" not in params:
        print(f"\nERROR: No 'code' found in URL. Got params: {params}")
        sys.exit(1)

    auth_code = params["code"][0]
    print(f"\nGot authorization code. Exchanging for tokens...")

    response = requests.post(
        "https://api.pinterest.com/v5/oauth/token",
        auth=(CLIENT_ID, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        }
    )

    if response.status_code != 200:
        print(f"\nERROR: Token exchange failed ({response.status_code})")
        print(response.text)
        sys.exit(1)

    tokens = response.json()
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

    token_data = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "bearer"),
        "expires_in": tokens.get("expires_in"),
        "refresh_token_expires_in": tokens.get("refresh_token_expires_in"),
        "scope": tokens.get("scope"),
        "client_id": CLIENT_ID,
    }

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✅ SUCCESS! Tokens saved to {TOKEN_PATH}")
    print(f"Scopes: {token_data.get('scope')}")
