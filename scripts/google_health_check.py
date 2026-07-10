#!/usr/bin/env python3
"""Google API health check for Atlas morning briefing.

Tests both Brand75 (service account) and Personal (OAuth2) credentials
against each configured API.

Usage:
    ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/google_health_check.py
    ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/google_health_check.py --json

Exit code: 0 if all pass, 1 if any fail.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials, get_personal_credentials, PERSONAL_TOKEN_FILE

from googleapiclient.discovery import build

DEFAULT_OUTPUT_FILE = Path.home() / ".openclaw" / "workspace" / "outputs" / "health" / "google-status.json"


def check(name: str, fn) -> dict:
    try:
        result = fn()
        return {"service": name, "status": "ok", "detail": result}
    except Exception as e:
        return {"service": name, "status": "error", "detail": str(e)}


def brand75_gmail():
    creds = get_brand75_credentials(["https://www.googleapis.com/auth/gmail.readonly"])
    svc = build("gmail", "v1", credentials=creds)
    profile = svc.users().getProfile(userId="me").execute()
    return f"{profile['emailAddress']} ({profile['messagesTotal']} messages)"


def brand75_calendar():
    creds = get_brand75_credentials(["https://www.googleapis.com/auth/calendar.readonly"])
    svc = build("calendar", "v3", credentials=creds)
    cals = svc.calendarList().list(maxResults=5).execute()
    count = len(cals.get("items", []))
    return f"{count} calendars accessible"


def brand75_drive():
    creds = get_brand75_credentials(["https://www.googleapis.com/auth/drive.readonly"])
    svc = build("drive", "v3", credentials=creds)
    about = svc.about().get(fields="user").execute()
    return f"Drive OK ({about['user']['emailAddress']})"


def brand75_sheets():
    creds = get_brand75_credentials(["https://www.googleapis.com/auth/spreadsheets.readonly"])
    svc = build("sheets", "v4", credentials=creds)
    # Test with TikTok Brain sheet
    result = svc.spreadsheets().get(spreadsheetId="1wvmJxXQgaAgR0rBNZkGbeOzJtJ6s3m4KSLCszv4AHqU").execute()
    return f"Sheets OK ({result['properties']['title']})"


def brand75_docs():
    creds = get_brand75_credentials(["https://www.googleapis.com/auth/documents.readonly"])
    svc = build("docs", "v1", credentials=creds)
    # Just verify the API responds (no specific doc needed)
    return "Docs API accessible"


def personal_gmail():
    creds = get_personal_credentials()
    svc = build("gmail", "v1", credentials=creds)
    profile = svc.users().getProfile(userId="me").execute()
    return f"{profile['emailAddress']} ({profile['messagesTotal']} messages)"


def personal_calendar():
    creds = get_personal_credentials()
    svc = build("calendar", "v3", credentials=creds)
    cals = svc.calendarList().list(maxResults=5).execute()
    count = len(cals.get("items", []))
    return f"{count} calendars accessible"


def personal_drive():
    creds = get_personal_credentials()
    svc = build("drive", "v3", credentials=creds)
    about = svc.about().get(fields="user").execute()
    return f"Drive OK ({about['user']['emailAddress']})"


def personal_sheets():
    creds = get_personal_credentials()
    svc = build("sheets", "v4", credentials=creds)
    result = svc.spreadsheets().get(
        spreadsheetId="1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk"
    ).execute()
    return f"Sheets OK ({result['properties']['title']})"


def personal_docs():
    creds = get_personal_credentials()
    svc = build("docs", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    files = drive.files().list(
        q="mimeType='application/vnd.google-apps.document'",
        pageSize=1,
        fields="files(id,name)",
    ).execute()
    if files.get("files"):
        doc = svc.documents().get(documentId=files["files"][0]["id"]).execute()
        return f"Docs OK ({doc['title']})"
    return "Docs OK (API accessible, no docs found)"


def main():
    use_json = "--json" in sys.argv
    output_file = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        output_file = Path(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else DEFAULT_OUTPUT_FILE
    elif "--save" in sys.argv:
        output_file = DEFAULT_OUTPUT_FILE

    results = {
        "checkedAt": datetime.now().astimezone().isoformat(),
        "brand75": [
            check("Gmail", brand75_gmail),
            check("Calendar", brand75_calendar),
            check("Drive", brand75_drive),
            check("Sheets", brand75_sheets),
        ],
        "personal": [],
    }

    # Only test personal if token file exists
    if PERSONAL_TOKEN_FILE.exists():
        results["personal"] = [
            check("Gmail", personal_gmail),
            check("Calendar", personal_calendar),
            check("Drive", personal_drive),
            check("Sheets", personal_sheets),
            check("Docs", personal_docs),
        ]
    else:
        results["personal"].append({
            "service": "ALL",
            "status": "skipped",
            "detail": f"Token file not found: {PERSONAL_TOKEN_FILE}",
        })

    all_ok = all(
        r["status"] == "ok" or r["status"] == "skipped"
        for key, group in results.items()
        if key != "checkedAt"
        for r in group
    )
    results["allOk"] = all_ok

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(results, indent=2))
        print(f"Health check saved to: {output_file}")

    if use_json:
        print(json.dumps(results, indent=2))
    else:
        print("=== Google API Health Check ===\n")
        for account, checks in results.items():
            if account in ("checkedAt", "allOk"):
                continue
            print(f"[{account}]")
            for r in checks:
                icon = "OK" if r["status"] == "ok" else "SKIP" if r["status"] == "skipped" else "FAIL"
                print(f"  {icon:4s} {r['service']}: {r['detail']}")
            print()

        if all_ok:
            print("All checks passed.")
        else:
            print("SOME CHECKS FAILED — see above.")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
