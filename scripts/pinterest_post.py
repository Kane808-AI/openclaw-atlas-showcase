#!/usr/bin/env python3
'''
Pinterest Post Console — Dad's Gadget Corner Auto-Poster

Usage:
  python3 ~/.openclaw/scripts/pinterest_post.py --client_id YOUR_ID --client_secret YOUR_SECRET --refresh_token YOUR_REFRESH --image pin1.png --title "Smart Plug Dad Hack" --desc "Full desc" --board "AI Gadgets" --link "https://amazon.com/ASIN"

Gets boards:list → posts pin via /v5/pins.

Token refresh: OAuth2 auth code flow (manual first auth → refresh_token persists).
Save token to ~/.openclaw/credentials/pinterest/token.json after first run.

Req: pip install requests oauthlib click (or exec once).
'''

import sys
import json
import click
import requests
from pathlib import Path
from requests_oauthlib import OAuth2Session
from urllib.parse import urlparse

PINTEREST_BASE = "https://api.pinterest.com/v5"
CLIENT_ID = None
CLIENT_SECRET = None
REFRESH_URL = f"{PINTEREST_BASE}/oauth/token"
BOARDS_URL = f"{PINTEREST_BASE}/boards"
PINS_URL = f"{PINTEREST_BASE}/pins"
TOKEN_FILE = Path("~/.openclaw/credentials/pinterest/token.json")

@click.command()
@click.option('--client_id', required=True, help='Pinterest App ID')
@click.option('--client_secret', required=True, help='Pinterest App Secret')
@click.option('--refresh_token', help='Initial refresh token (manual auth)')
@click.option('--image', required=True, help='Local image path (PNG/JPG)')
@click.option('--title', required=True, help='Pin title')
@click.option('--desc', required=True, help='Pin description')
@click.option('--board', required=True, help='Board name (exact)')
@click.option('--link', default='', help='Affiliate link')
def post(client_id, client_secret, refresh_token, image, title, desc, board, link):
    global CLIENT_ID, CLIENT_SECRET
    CLIENT_ID, CLIENT_SECRET = client_id, client_secret
    token = load_token()
    if refresh_token and not token:
        token = {'refresh_token': refresh_token}
        save_token(token)
    
    session = get_oauth_session(token)
    
    # Get boards → find ID
    boards = session.get(BOARDS_URL).json()['items']
    board_id = next((b['id'] for b in boards if b['name'].lower() == board.lower()), None)
    if not board_id:
        print(f"Board '{board}' not found. Available: {[b['name'] for b in boards]}")
        sys.exit(1)
    
    # Upload image → media_id
    with open(image, 'rb') as f:
        media_resp = session.post(f"{PINS_URL}", files={'image': f}).json()
    media_id = media_resp['id']  # Simplified; handle upload_url if needed
    
    # Create pin
    pin_data = {
        'board_id': board_id,
        'board_owner_id': session.get(f"{BOARDS_URL}/{board_id}").json()['owner']['id'],  # Get owner
        'title': title,
        'description': desc,
        'link': link,
        'media_source': {'source_type': 'image_url', 'url': media_id}  # Or media_id
    }
    resp = session.post(PINS_URL, json=pin_data)
    if resp.ok:
        print(f"✅ Pin posted: {resp.json()['data']['id']}")
    else:
        print(f"❌ Error: {resp.json()}")

def get_oauth_session(token):
    session = OAuth2Session(CLIENT_ID, redirect_uri='https://developers.pinterest.com/tools/api-explorer/', scope=['boards:read boards:write pins:read pins:write'])
    if 'access_token' in token:
        session.token = token
    else:
        token = session.fetch_token(REFRESH_URL, client_secret=CLIENT_SECRET, refresh_token=token.get('refresh_token'))
        save_token(token)
    return session

def load_token():
    try:
        with open(TOKEN_FILE.expanduser(), 'r') as f:
            return json.load(f)
    except:
        return {}

def save_token(token):
    TOKEN_FILE.expanduser().parent.mkdir(exist_ok=True)
    with open(TOKEN_FILE.expanduser(), 'w') as f:
        json.dump(token, f)

if __name__ == '__main__':
    post()