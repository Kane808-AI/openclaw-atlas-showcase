import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes needed for TikTok Brain
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',      # Create/edit files app created
    'https://www.googleapis.com/auth/drive.readonly',   # Read any file in Drive
    'https://www.googleapis.com/auth/spreadsheets',     # Read/write Sheets
    'https://www.googleapis.com/auth/documents',        # Read/write Docs
]

# Paths
CREDENTIALS_DIR = os.path.expanduser('~/.openclaw/credentials/google/')
CLIENT_SECRETS_FILE = os.path.join(CREDENTIALS_DIR, 'brand75-gmail-oauth-client.json')
NEW_TOKEN_FILE = os.path.join(CREDENTIALS_DIR, 'brand75-brain-token.json')

def main():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"Error: Client secrets file not found at {CLIENT_SECRETS_FILE}")
        return

    print("Starting authentication flow for Brand75 Brain (Docs + Sheets)...")
    
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, SCOPES
    )
    
    creds = flow.run_local_server(port=0)
    
    # Save the credentials for the next run
    with open(NEW_TOKEN_FILE, 'w') as token:
        token.write(creds.to_json())
        
    print(f"\nSuccess! Token saved to: {NEW_TOKEN_FILE}")

if __name__ == '__main__':
    main()
