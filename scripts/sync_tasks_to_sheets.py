#!/usr/bin/env python3
"""Sync ~/.openclaw/workspace/tasks.db → Google Sheet "Atlas Tasks" (full replace)."""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials

from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]
SPREADSHEET_ID = "1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk"
SHEET_NAME = "Atlas Tasks"
DB_PATH = os.path.expanduser("~/.openclaw/workspace/tasks.db")

HEADERS = ["id", "title", "type", "status", "priority", "project",
           "due_date", "recurrence", "notes", "created_at", "updated_at"]

QUERY = """
SELECT id, title, type, status, priority, project,
       due_date, recurrence, notes, created_at, updated_at
FROM tasks
ORDER BY project,
         CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
         status,
         created_at
"""


def get_credentials():
    return get_brand75_credentials(SCOPES)


def read_tasks():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(QUERY).fetchall()
    conn.close()
    return [[str(row[col]) if row[col] is not None else "" for col in HEADERS] for row in rows]


def sync():
    creds = get_credentials()
    service = build("sheets", "v4", credentials=creds)
    sheets = service.spreadsheets()

    # Clear existing data
    sheets.values().clear(
        spreadsheetId=SPREADSHEET_ID,
        range=SHEET_NAME,
    ).execute()

    # Build payload: header + data rows
    task_rows = read_tasks()
    values = [HEADERS] + task_rows

    sheets.values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    print(f"Synced {len(task_rows)} tasks to Google Sheet")


if __name__ == "__main__":
    sync()
