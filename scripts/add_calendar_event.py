
import datetime
import os.path
import json
import pickle
import argparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from google_auth import get_brand75_credentials

SCOPES = ['https://www.googleapis.com/auth/calendar']
PERSONAL_CLIENT_FILE = os.path.expanduser('~/.openclaw/credentials/google/personal-gmail-oauth-client.json')
PERSONAL_TOKEN_FILE = os.path.expanduser('~/.openclaw/scripts/personal-token.json')


def create_calendar_event(
    summary,
    description,
    location,
    start_time_str,
    end_time_str,
    time_zone,
    calendar_id='primary',
    account='brand75'
):
    creds = None
    if account == 'brand75':
        creds = get_brand75_credentials()
    elif os.path.exists(PERSONAL_TOKEN_FILE):
        try:
            with open(PERSONAL_TOKEN_FILE, 'r') as token_file:
                token_data = json.load(token_file)
            
            expiry_str = token_data.get('expiry')
            expiry_datetime = None
            if expiry_str:
                try:
                    if expiry_str.endswith('Z'):
                        expiry_str = expiry_str[:-1]
                    expiry_datetime = datetime.datetime.fromisoformat(expiry_str)
                except ValueError:
                    print(f"Warning: Could not parse expiry datetime string: {expiry_str}")

            creds = Credentials(
                token=token_data.get('token'),
                refresh_token=token_data.get('refresh_token'),
                token_uri=token_data.get('token_uri'),
                client_id=token_data.get('client_id'),
                client_secret=token_data.get('client_secret'),
                scopes=token_data.get('scopes'),
                expiry=expiry_datetime
            )
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading personal token file as JSON: {e}. Attempting re-authentication.")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                PERSONAL_CLIENT_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            
            token_data = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": list(creds.scopes) if creds.scopes else SCOPES,
                "expiry": creds.expiry.isoformat() + "Z" if creds.expiry else None,
            }
            with open(PERSONAL_TOKEN_FILE, "w") as token_file:
                json.dump(token_data, token_file, indent=2)
            os.chmod(PERSONAL_TOKEN_FILE, 0o600)

    try:
        service = build('calendar', 'v3', credentials=creds)
        print(f"Attempting to add event to calendar ID: {calendar_id}")

        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time_str,
                'timeZone': time_zone,
            },
            'end': {
                'dateTime': end_time_str,
                'timeZone': time_zone,
            },
            'recurrence': [
                'RRULE:FREQ=DAILY;COUNT=1'
            ],
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f'Event created: {event.get("htmlLink")}')
        
        # Verification step
        created_event = service.events().get(calendarId=calendar_id, eventId=event['id']).execute()
        if created_event:
            print(f"Verification: Event '{created_event['summary']}' successfully found on calendar.")
        else:
            print(f"Verification FAILED: Event '{summary}' not found on calendar after creation.")

    except HttpError as error:
        print(f'An error occurred: {error}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a Google Calendar event.')
    parser.add_argument('--account', type=str, default='brand75', help='Google account: brand75 (default) or personal')
    parser.add_argument('--summary', type=str, required=True, help='Summary of the event.')
    parser.add_argument('--description', type=str, default='', help='Description of the event.')
    parser.add_argument('--location', type=str, default='', help='Location of the event.')
    parser.add_argument('--start-time', type=str, required=True, help='Start time of the event (ISO format, e.g., 2026-04-18T12:15:00).')
    parser.add_argument('--end-time', type=str, required=True, help='End time of the event (ISO format, e.g., 2026-04-18T13:15:00).')
    parser.add_argument('--time-zone', type=str, default='America/Los_Angeles', help='Time zone of the event.')
    parser.add_argument('--calendar-id', type=str, default='primary', help='Calendar ID to add the event to.')

    args = parser.parse_args()

    if args.account in ('personal', 'brand75'):
        create_calendar_event(
            summary=args.summary,
            description=args.description,
            location=args.location,
            start_time_str=args.start_time,
            end_time_str=args.end_time,
            time_zone=args.time_zone,
            calendar_id=args.calendar_id,
            account=args.account,
        )
    else:
        print(f"Error: Account '{args.account}' not supported.")
