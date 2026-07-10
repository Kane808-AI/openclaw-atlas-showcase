#!/usr/bin/env python3
"""
Pinterest Analytics — Dad's Gadget Corner

Fetches pin and board analytics from Pinterest API v5.
Outputs JSON summary to stdout. Optionally writes to Google Sheet.

Usage:
  python3 pinterest_analytics.py --client_id ID --client_secret SECRET
  python3 pinterest_analytics.py --client_id ID --client_secret SECRET --sheet SHEET_ID
"""

import sys
import json
import click
import requests
from pathlib import Path
from datetime import datetime, timedelta

PINTEREST_BASE = "https://api.pinterest.com/v5"
TOKEN_FILE = Path("~/.openclaw/credentials/pinterest/token.json")

def load_token():
    try:
        with open(TOKEN_FILE.expanduser(), 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_token(token):
    TOKEN_FILE.expanduser().parent.mkdir(exist_ok=True, parents=True)
    with open(TOKEN_FILE.expanduser(), 'w') as f:
        json.dump(token, f)

def refresh_access_token(client_id, client_secret, refresh_token):
    resp = requests.post(
        f"{PINTEREST_BASE}/oauth/token",
        data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    if resp.ok:
        token = resp.json()
        token['refresh_token'] = refresh_token  # preserve refresh token
        save_token(token)
        return token
    else:
        print(f"Token refresh failed: {resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)

def get_headers(token):
    return {'Authorization': f"Bearer {token['access_token']}"}

def get_user_pins(token, bookmark=None):
    params = {'page_size': 25}
    if bookmark:
        params['bookmark'] = bookmark
    resp = requests.get(f"{PINTEREST_BASE}/pins", headers=get_headers(token), params=params)
    if resp.ok:
        return resp.json()
    return {'items': []}

def get_pin_analytics(token, pin_id, start_date, end_date):
    params = {
        'start_date': start_date,
        'end_date': end_date,
        'metric_types': 'IMPRESSION,PIN_CLICK,SAVE,OUTBOUND_CLICK',
    }
    resp = requests.get(
        f"{PINTEREST_BASE}/pins/{pin_id}/analytics",
        headers=get_headers(token),
        params=params
    )
    if resp.ok:
        return resp.json()
    return {}

def get_boards(token):
    resp = requests.get(f"{PINTEREST_BASE}/boards", headers=get_headers(token))
    if resp.ok:
        return resp.json().get('items', [])
    return []

@click.command()
@click.option('--client_id', required=True, help='Pinterest App ID')
@click.option('--client_secret', required=True, help='Pinterest App Secret')
@click.option('--days', default=30, help='Number of days to analyze (default: 30)')
@click.option('--sheet', default=None, help='Google Sheet ID to write results to')
def analyze(client_id, client_secret, days, sheet):
    token = load_token()
    if not token.get('access_token'):
        if token.get('refresh_token'):
            token = refresh_access_token(client_id, client_secret, token['refresh_token'])
        else:
            print("No access token or refresh token found.", file=sys.stderr)
            sys.exit(1)

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # Get all boards
    boards = get_boards(token)
    board_summary = []
    for b in boards:
        board_summary.append({
            'id': b['id'],
            'name': b['name'],
            'pin_count': b.get('pin_count', 0),
        })

    # Get all pins and their analytics
    all_pins = []
    pin_data = get_user_pins(token)
    all_pins.extend(pin_data.get('items', []))

    # Paginate if needed
    bookmark = pin_data.get('bookmark')
    while bookmark:
        pin_data = get_user_pins(token, bookmark)
        all_pins.extend(pin_data.get('items', []))
        bookmark = pin_data.get('bookmark')

    pin_analytics = []
    totals = {'impressions': 0, 'pin_clicks': 0, 'saves': 0, 'outbound_clicks': 0}

    for pin in all_pins:
        analytics = get_pin_analytics(token, pin['id'], start_date, end_date)
        impressions = sum(v for d in analytics.get('all', {}).get('daily_metrics', []) for v in [d.get('data_status', {}).get('IMPRESSION', 0)] if isinstance(v, (int, float)))

        # Simpler: aggregate from the summary if available
        summary = analytics.get('all', {})
        pin_metrics = {
            'pin_id': pin['id'],
            'title': pin.get('title', ''),
            'link': pin.get('link', ''),
            'created_at': pin.get('created_at', ''),
            'impressions': summary.get('IMPRESSION', 0),
            'pin_clicks': summary.get('PIN_CLICK', 0),
            'saves': summary.get('SAVE', 0),
            'outbound_clicks': summary.get('OUTBOUND_CLICK', 0),
        }

        for k in ['impressions', 'pin_clicks', 'saves', 'outbound_clicks']:
            if isinstance(pin_metrics[k], (int, float)):
                totals[k] += pin_metrics[k]

        pin_analytics.append(pin_metrics)

    # Calculate CTR
    ctr = (totals['outbound_clicks'] / totals['impressions'] * 100) if totals['impressions'] > 0 else 0

    # Sort by impressions
    pin_analytics.sort(key=lambda x: x.get('impressions', 0), reverse=True)

    report = {
        'period': f"{start_date} to {end_date}",
        'totals': {
            **totals,
            'ctr_percent': round(ctr, 2),
            'total_pins': len(all_pins),
            'total_boards': len(boards),
        },
        'boards': board_summary,
        'top_pins': pin_analytics[:10],
        'all_pins': pin_analytics,
    }

    print(json.dumps(report, indent=2))

    # Optionally write to Google Sheet
    if sheet:
        write_to_sheet(sheet, report)

def write_to_sheet(sheet_id, report):
    try:
        sys.path.insert(0, str(Path('~/.openclaw/scripts').expanduser()))
        from google_auth import get_brand75_credentials
        from googleapiclient.discovery import build

        creds = get_brand75_credentials(['https://www.googleapis.com/auth/spreadsheets'])
        service = build('sheets', 'v4', credentials=creds)

        # Write summary row
        date_str = datetime.now().strftime('%Y-%m-%d')
        t = report['totals']
        row = [date_str, report['period'], t['total_pins'], t['total_boards'],
               t['impressions'], t['pin_clicks'], t['saves'], t['outbound_clicks'],
               t['ctr_percent']]

        service.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range='Analytics!A:I',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': [row]}
        ).execute()
        print(f"Written to sheet {sheet_id}", file=sys.stderr)
    except Exception as e:
        print(f"Sheet write failed: {e}", file=sys.stderr)

if __name__ == '__main__':
    analyze()
