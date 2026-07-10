#!/usr/bin/env python3
"""Find and optionally remove duplicates from TikTok Brain sheets."""
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

def read_sheet_data(sheets_service, ssid, range_name):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=ssid, range=range_name
    ).execute()
    return result.get('values', [])

def find_tiktok_brain_duplicates(values):
    """Find duplicates in TikTok Brain sheet based on URL."""
    if not values:
        return [], {}
    
    seen_urls = {}
    duplicates = []
    
    for i, row in enumerate(values):
        if len(row) >= 2 and row[1]:  # URL is in column B (index 1)
            url = row[1].strip()
            if url in seen_urls:
                duplicates.append({
                    'row': i + 1,  # 1-based for Google Sheets
                    'url': url,
                    'first_seen_row': seen_urls[url]['row'],
                    'data': row
                })
            else:
                seen_urls[url] = {'row': i + 1, 'data': row}
    
    return duplicates, seen_urls

def find_ideas_backlog_duplicates(values):
    """Find duplicates in Ideas Backlog sheet based on Idea text."""
    if not values:
        return [], {}
    
    seen_ideas = {}
    duplicates = []
    
    for i, row in enumerate(values):
        if len(row) >= 1 and row[0]:  # Idea is in column A (index 0)
            idea = row[0].strip().lower()  # Normalize to lowercase
            if idea in seen_ideas:
                duplicates.append({
                    'row': i + 1,
                    'idea': row[0][:80] + "..." if len(row[0]) > 80 else row[0],
                    'first_seen_row': seen_ideas[idea]['row'],
                    'data': row
                })
            else:
                seen_ideas[idea] = {'row': i + 1, 'data': row}
    
    return duplicates, seen_ideas

def main():
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    
    # Check TikTok Brain
    print("=" * 60)
    print("SCANNING: TikTok Brain")
    print("=" * 60)
    
    tiktok_ssid = get_sheet_id(drive_service, "TikTok Brain")
    if tiktok_ssid:
        tiktok_data = read_sheet_data(sheets_service, tiktok_ssid, "A:F")
        print(f"Total rows: {len(tiktok_data)}")
        
        tiktok_dups, tiktok_unique = find_tiktok_brain_duplicates(tiktok_data)
        print(f"Unique URLs: {len(tiktok_unique)}")
        print(f"Duplicate rows found: {len(tiktok_dups)}")
        
        if tiktok_dups:
            print("\nDuplicate entries:")
            for dup in tiktok_dups:
                print(f"  Row {dup['row']}: URL appears first at row {dup['first_seen_row']}")
                print(f"    Data: {dup['data'][:3]}...")  # Show first 3 columns
    else:
        print("Sheet not found!")
    
    # Check Ideas Backlog
    print("\n" + "=" * 60)
    print("SCANNING: Ideas Backlog")
    print("=" * 60)
    
    ideas_ssid = get_sheet_id(drive_service, "Ideas Backlog")
    if ideas_ssid:
        ideas_data = read_sheet_data(sheets_service, ideas_ssid, "A:E")
        print(f"Total rows: {len(ideas_data)}")
        
        ideas_dups, ideas_unique = find_ideas_backlog_duplicates(ideas_data)
        print(f"Unique ideas: {len(ideas_unique)}")
        print(f"Duplicate rows found: {len(ideas_dups)}")
        
        if ideas_dups:
            print("\nDuplicate entries:")
            for dup in ideas_dups:
                print(f"  Row {dup['row']}: Idea appears first at row {dup['first_seen_row']}")
                print(f"    Idea: {dup['idea']}")
    else:
        print("Sheet not found!")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"TikTok Brain: {len(tiktok_dups) if tiktok_ssid else 'N/A'} duplicates")
    print(f"Ideas Backlog: {len(ideas_dups) if ideas_ssid else 'N/A'} duplicates")
    
    return {
        "tiktok_brain": {
            "ssid": tiktok_ssid,
            "duplicates": tiktok_dups,
            "unique_count": len(tiktok_unique) if tiktok_ssid else 0
        },
        "ideas_backlog": {
            "ssid": ideas_ssid,
            "duplicates": ideas_dups,
            "unique_count": len(ideas_unique) if ideas_ssid else 0
        }
    }

if __name__ == "__main__":
    result = main()
    print("\n\nRaw result:")
    print(json.dumps(result, indent=2, default=str))