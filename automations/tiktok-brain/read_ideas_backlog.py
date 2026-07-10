import os, json
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

def read_new_ideas():
    creds = get_credentials()
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)

    ssid = get_sheet_id(drive_service, IDEAS_SHEET_TITLE)
    if not ssid:
        return {"error": f"Spreadsheet '{IDEAS_SHEET_TITLE}' not found."}

    # Assuming the following fixed column order based on tiktok_brain.py's log_ideas
    # The actual first row of the sheet might not be header, but data.
    # So we'll treat all rows as data and rely on positional mapping.
    expected_headers = ["Idea", "Category", "Source Doc Link", "Date Captured", "Status"]
    range_name = 'A:E' # To read all 5 columns
    result = sheets_service.spreadsheets().values().get(spreadsheetId=ssid, range=range_name).execute()
    values = result.get('values', [])

    # print(f"Raw values from sheet (after fix attempt): {values}") # DEBUG PRINT

    if not values:
        return {"message": "No data found in Ideas Backlog."}

    new_ideas = []
    for row in values:
        # Ensure row has enough columns to avoid IndexError
        if len(row) >= len(expected_headers):
            # Map row elements to expected headers by position
            row_dict = dict(zip(expected_headers, row))
            if row_dict.get('Status') == 'New':
                new_ideas.append({
                    "idea": row_dict.get('Idea'),
                    "category": row_dict.get('Category'),
                    "source_doc": row_dict.get('Source Doc Link')
                })
    return {"new_ideas": new_ideas}

if __name__ == "__main__":
    result = read_new_ideas()
    print(json.dumps(result, indent=2))
