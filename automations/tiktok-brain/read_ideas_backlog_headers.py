
import gspread
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

# Google Sheets ID and URL from TOOLS.md
SPREADSHEET_ID = 'SHOWCASE_TIKTOK_IDEAS_SHEET_ID'
SHEET_URL = 'https://docs.google.com/spreadsheets/d/SHOWCASE_TIKTOK_IDEAS_SHEET_ID'

# Path to token file
TOKEN_PATH = os.path.expanduser('~/.openclaw/credentials/google/brand75-brain-token.json')

try:
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                print(f"Error: Token refresh failed: {e}. You may need to re-authenticate.")
                raise Exception("Google Sheets authentication failed.")
        else:
            print("Error: No valid token found or token is invalid/expired without refresh token. Please ensure OAuth flow has been completed.")
            raise Exception("Google Sheets authentication failed.")

    gc = gspread.authorize(creds)
    
    # print(f"Type of gc: {type(gc)}")
    # print(f"Methods and attributes in gc: {dir(gc)}") # Keep commented for less verbose output

    # Open the spreadsheet by URL
    spreadsheet = gc.open_by_url(SHEET_URL)
    
    # Select the first worksheet (default)
    worksheet = spreadsheet.sheet1
    
    # Get all values from the first row to get headers
    headers = worksheet.row_values(1)
    
    print("Successfully read headers:")
    print(headers)
    
except gspread.exceptions.SpreadsheetNotFound:
    print(f"Error: Spreadsheet with URL {SHEET_URL} not found.")
except Exception as e:
    print(f"An unexpected error occurred: {e}")
