#!/usr/bin/env python3
"""Remove duplicate rows from TikTok Brain sheets."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from google_auth import get_brand75_credentials

from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets',
]


def get_credentials():
    return get_brand75_credentials(SCOPES)

def get_sheet_id(drive_service, title):
    query = f"mimeType='application/vnd.google-apps.spreadsheet' and name='{title}' and trashed=false"
    results = drive_service.files().list(q=query, fields='files(id)').execute()
    files = results.get('files', [])
    return files[0]['id'] if files else None

def delete_rows(sheets_service, ssid, row_indices):
    """Delete rows from a sheet. Row indices are 0-based."""
    if not row_indices:
        return 0
    
    # Get sheet ID (first sheet)
    sheet_metadata = sheets_service.spreadsheets().get(spreadsheetId=ssid).execute()
    sheet_id = sheet_metadata['sheets'][0]['properties']['sheetId']
    
    # Sort in descending order to delete from bottom up
    sorted_indices = sorted(row_indices, reverse=True)
    
    requests = []
    for idx in sorted_indices:
        requests.append({
            'deleteDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': idx,
                    'endIndex': idx + 1
                }
            }
        })
    
    body = {'requests': requests}
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=ssid, body=body
    ).execute()
    
    return len(requests)

def main():
    # Rows to delete (1-based from find_duplicates.py)
    # TikTok Brain: rows 7, 8, 9 (converted to 0-based: 6, 7, 8)
    tiktok_rows_to_delete = [6, 7, 8]
    
    # Ideas Backlog: rows 17, 18, 19, 30, 31, 32, 33, 34 
    # (converted to 0-based: 16, 17, 18, 29, 30, 31, 32, 33)
    ideas_rows_to_delete = [16, 17, 18, 29, 30, 31, 32, 33]
    
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    # Delete from TikTok Brain
    print("=" * 60)
    print("REMOVING DUPLICATES: TikTok Brain")
    print("=" * 60)
    
    tiktok_ssid = get_sheet_id(drive_service, "TikTok Brain")
    if tiktok_ssid:
        print(f"Spreadsheet ID: {tiktok_ssid}")
        print(f"Rows to delete (1-based): {[r+1 for r in tiktok_rows_to_delete]}")
        deleted = delete_rows(sheets_service, tiktok_ssid, tiktok_rows_to_delete)
        print(f"✓ Deleted {deleted} duplicate rows from TikTok Brain")
    else:
        print("✗ TikTok Brain sheet not found!")
    
    # Delete from Ideas Backlog
    print("\n" + "=" * 60)
    print("REMOVING DUPLICATES: Ideas Backlog")
    print("=" * 60)
    
    ideas_ssid = get_sheet_id(drive_service, "Ideas Backlog")
    if ideas_ssid:
        print(f"Spreadsheet ID: {ideas_ssid}")
        print(f"Rows to delete (1-based): {[r+1 for r in ideas_rows_to_delete]}")
        deleted = delete_rows(sheets_service, ideas_ssid, ideas_rows_to_delete)
        print(f"✓ Deleted {deleted} duplicate rows from Ideas Backlog")
    else:
        print("✗ Ideas Backlog sheet not found!")
    
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)

if __name__ == "__main__":
    main()