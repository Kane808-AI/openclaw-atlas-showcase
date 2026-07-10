import os
import sys
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Updated SCOPES for Google Sheets write access
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.readonly', # Keep if drive service is also needed
]

CREDENTIALS_DIR = os.path.expanduser('~/.openclaw/credentials/google/')
CLIENT_SECRETS_FILE = os.path.join(CREDENTIALS_DIR, 'brand75-gmail-oauth-client.json')
TOKEN_FILE = os.path.join(CREDENTIALS_DIR, 'brand75-brain-token.json')

SPREADSHEET_ID = '1luBDNwjl7Ogdk0zAXsXjfF3uCCO7GYAkElBeVSfzvOE' # TikTok Ideas Backlog

def get_sheets_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            from google_auth_oauthlib.flow import InstalledAppFlow
            if not os.path.exists(CLIENT_SECRETS_FILE):
                print(f"Error: Client secrets file not found at {CLIENT_SECRETS_FILE}", file=sys.stderr)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('sheets', 'v4', credentials=creds)

def append_to_sheet(service, spreadsheet_id, range_name, values):
    try:
        body = {
            'values': values
        }
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        return result
    except HttpError as err:
        print(f"Google API Error: {err}", file=sys.stderr)
        return None

def main(product_ideas):
    service = get_sheets_service()
    
    rows_to_append = []
    for idea in product_ideas:
        rows_to_append.append([idea['Product Name'], idea['Source'], idea['Description'], 'New'])

    print(f"Appending {len(rows_to_append)} rows to TikTok Ideas Backlog sheet...")
    # The range should be just the sheet name if appending to the end
    result = append_to_sheet(service, SPREADSHEET_ID, 'Ideas Backlog', rows_to_append) # Assuming 'Ideas Backlog' is the correct sheet name
    if result:
        print(f"Successfully appended to sheet. Updates: {result.get('updates')}")
    else:
        print("Failed to append to sheet.", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        try:
            product_ideas_json = sys.argv[1]
            product_ideas = json.loads(product_ideas_json)
            main(product_ideas)
        except json.JSONDecodeError:
            print("Error: Invalid JSON input for product ideas.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"An unexpected error occurred: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Usage: python3 add_to_tiktok_ideas_backlog.py '<json_string_of_product_ideas>'")
        sys.exit(1)
