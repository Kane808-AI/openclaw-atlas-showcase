#!/usr/bin/env python3
"""Unified Google auth module for Atlas.

Brand75 (support@brand75.com):
    Service account with domain-wide delegation. Never expires.
    Key file: ~/.openclaw/credentials/google/brand75-service-account.json

Personal (you@example.com):
    OAuth2 refresh token stored as JSON file. Auto-refreshes.
    Token file: ~/.openclaw/scripts/personal-token.json
"""

import json
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials

CREDENTIALS_DIR = Path.home() / ".openclaw" / "credentials" / "google"

BRAND75_SERVICE_ACCOUNT_FILE = CREDENTIALS_DIR / "brand75-service-account.json"
BRAND75_SUBJECT = "support@brand75.com"

PERSONAL_TOKEN_FILE = Path.home() / ".openclaw" / "scripts" / "personal-token.json"
PERSONAL_CLIENT_FILE = CREDENTIALS_DIR / "personal-gmail-oauth-client.json"

# Brand75 GBP OAuth token — user-consent flow required (service account has 0 quota for GBP APIs)
BRAND75_GBP_TOKEN_FILE = CREDENTIALS_DIR / "brand75-gbp-token.json"
BRAND75_GBP_CLIENT_FILE = CREDENTIALS_DIR / "brand75-gmail-oauth-client.json"

# All scopes authorized via domain-wide delegation in Google Admin.
# Service account must request all scopes together (DWD validates the full set).
BRAND75_ALL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/business.manage",
]


def get_brand75_credentials(scopes: list[str] | None = None) -> service_account.Credentials:
    """Load Brand75 service account credentials with domain-wide delegation.

    Args:
        scopes: Ignored — always uses full authorized scope set for DWD compatibility.
                Kept for API compatibility with callers.

    Returns:
        google.oauth2.service_account.Credentials impersonating support@brand75.com
    """
    creds = service_account.Credentials.from_service_account_file(
        str(BRAND75_SERVICE_ACCOUNT_FILE),
        scopes=BRAND75_ALL_SCOPES,
        subject=BRAND75_SUBJECT,
    )
    return creds


def get_brand75_gbp_credentials() -> Credentials:
    """Load Brand75 GBP OAuth2 credentials for support@brand75.com.

    GBP APIs (mybusinessaccountmanagement, mybusinessbusinessinformation) reject
    service-account/DWD auth with quota_limit_value=0. Only user-consent OAuth works.

    Raises FileNotFoundError if the token hasn't been minted yet — run auth_brand75_gbp.py first.
    """
    if not BRAND75_GBP_TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"Brand75 GBP OAuth token not found at {BRAND75_GBP_TOKEN_FILE}.\n"
            "Run: ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/auth_brand75_gbp.py"
        )

    with open(BRAND75_GBP_TOKEN_FILE) as f:
        token_data = json.load(f)

    with open(BRAND75_GBP_CLIENT_FILE) as f:
        client_data = json.load(f)["installed"]

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_data["client_id"],
        client_secret=client_data["client_secret"],
        scopes=token_data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            if "invalid_grant" in str(e) or "revoked" in str(e).lower():
                raise SystemExit(
                    "Brand75 GBP OAuth token has been revoked or expired permanently.\n"
                    "Re-run: ~/.openclaw/venv/google/bin/python3 "
                    "~/.openclaw/scripts/auth_brand75_gbp.py\n"
                    f"Original error: {e}"
                )
            raise
        token_data["token"] = creds.token
        if creds.expiry:
            token_data["expiry"] = creds.expiry.isoformat() + "Z"
        with open(BRAND75_GBP_TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)

    return creds


def get_personal_credentials() -> Credentials:
    """Load personal OAuth2 credentials, auto-refreshing if expired.

    Returns:
        google.oauth2.credentials.Credentials for you@example.com
    """
    with open(PERSONAL_TOKEN_FILE) as f:
        token_data = json.load(f)

    with open(PERSONAL_CLIENT_FILE) as f:
        client_data = json.load(f)["installed"]

    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=client_data["client_id"],
        client_secret=client_data["client_secret"],
        scopes=token_data.get("scopes"),
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            if "invalid_grant" in str(e) or "revoked" in str(e).lower():
                raise SystemExit(
                    "Personal Google token has been revoked or expired permanently.\n"
                    "Re-run: ~/.openclaw/venv/google/bin/python3 "
                    "~/.openclaw/scripts/reauth_personal.py\n"
                    f"Original error: {e}"
                )
            raise
        token_data["token"] = creds.token
        if creds.expiry:
            token_data["expiry"] = creds.expiry.isoformat() + "Z"
        with open(PERSONAL_TOKEN_FILE, "w") as f:
            json.dump(token_data, f, indent=2)

    return creds
