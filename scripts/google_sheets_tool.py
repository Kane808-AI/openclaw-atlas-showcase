#!/usr/bin/env python3
"""Google Sheets CLI tool for Atlas — append rows to spreadsheets.

Replaces gog sheets append.

Usage:
    google_sheets_tool.py append SPREADSHEET_ID RANGE --values-json '[[...]]'
    google_sheets_tool.py read SPREADSHEET_ID RANGE
    google_sheets_tool.py update SPREADSHEET_ID RANGE --values-json '[[...]]'

Output (append): JSON with {"status": "ok", "updatedRows": N}
Output (read):   JSON with {"values": [[...]]}
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials

from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def action_append(spreadsheet_id: str, range_: str, values: list) -> dict:
    creds = get_brand75_credentials(SCOPES)
    sheets = build("sheets", "v4", credentials=creds)

    body = {"values": values}
    result = (
        sheets.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )
    updates = result.get("updates", {})
    return {"status": "ok", "updatedRows": updates.get("updatedRows", 0)}


def action_read(spreadsheet_id: str, range_: str) -> dict:
    creds = get_brand75_credentials(SCOPES)
    sheets = build("sheets", "v4", credentials=creds)

    result = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_)
        .execute()
    )
    return {"values": result.get("values", [])}


def action_update(spreadsheet_id: str, range_: str, values: list) -> dict:
    creds = get_brand75_credentials(SCOPES)
    sheets = build("sheets", "v4", credentials=creds)

    body = {"values": values}
    result = (
        sheets.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body=body,
        )
        .execute()
    )
    updates = result.get("updatedCells", 0)
    return {"status": "ok", "updatedCells": updates}


def main():
    parser = argparse.ArgumentParser(description="Google Sheets tool for Atlas")
    sub = parser.add_subparsers(dest="action", required=True)

    p_append = sub.add_parser("append", help="Append rows to a spreadsheet")
    p_append.add_argument("spreadsheet_id", help="Spreadsheet ID")
    p_append.add_argument("range", help="Range (e.g. 'Sheet1!A:F')")
    p_append.add_argument("--values-json", required=True, help="JSON 2D array of values")

    p_read = sub.add_parser("read", help="Read values from a spreadsheet")
    p_read.add_argument("spreadsheet_id", help="Spreadsheet ID")
    p_read.add_argument("range", help="Range (e.g. 'Sheet1!A1:Z100')")

    p_update = sub.add_parser("update", help="Update values in a spreadsheet")
    p_update.add_argument("spreadsheet_id", help="Spreadsheet ID")
    p_update.add_argument("range", help="Range (e.g. 'Sheet1!A1')")
    p_update.add_argument("--values-json", required=True, help="JSON 2D array of values")

    args = parser.parse_args()

    try:
        if args.action == "append":
            values = json.loads(args.values_json)
            result = action_append(args.spreadsheet_id, args.range, values)
        elif args.action == "read":
            result = action_read(args.spreadsheet_id, args.range)
        elif args.action == "update":
            values = json.loads(args.values_json)
            result = action_update(args.spreadsheet_id, args.range, values)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
