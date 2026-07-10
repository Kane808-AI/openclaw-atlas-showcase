import os, json, sys
from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/documents'
]
CREDENTIALS_DIR = os.path.expanduser('~/.openclaw/credentials/google/')
CLIENT_SECRETS_FILE = os.path.join(CREDENTIALS_DIR, 'brand75-gmail-oauth-client.json')
TOKEN_FILE = os.path.join(CREDENTIALS_DIR, 'brand75-brain-token.json')
IDEAS_SHEET_TITLE = "Ideas Backlog"

def get_credentials():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return creds

def get_sheet_id(drive_service, title):
    query = f"mimeType='application/vnd.google-apps.spreadsheet' and name='{title}' and trashed=false"
    results = drive_service.files().list(q=query, fields='files(id)').execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    return None

def add_ideas_to_sheet(ideas):
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    ssid = get_sheet_id(drive_service, IDEAS_SHEET_TITLE)
    if not ssid:
        return { "error": f"Spreadsheet '{IDEAS_SHEET_TITLE}' not found." }

    values = []
    current_date = datetime.now().strftime('%Y-%m-%d')
    for idea in ideas:
        values.append([
            idea['Idea'],
            idea['Category'],
            idea['Source Doc Link'],
            current_date,
            'New'
        ])

    body = {
        'values': values
    }
    range_name = 'A1' # Appends starting from the first empty row
    result = sheets_service.spreadsheets().values().append(
        spreadsheetId=ssid,
        range=range_name,
        valueInputOption='USER_ENTERED',
        body=body
    ).execute()
    return {"updated_range": result.get('updates').get('updatedRange'), "updated_rows": result.get('updates').get('updatedRows')}

if __name__ == "__main__":
    if len(sys.argv) > 1:
        ideas_json = sys.argv[1]
        ideas_to_add = json.loads(ideas_json)
        result = add_ideas_to_sheet(ideas_to_add)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python3 add_product_briefs_to_ideas_backlog.py '<json_string_of_ideas>'")
