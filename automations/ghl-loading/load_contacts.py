#!/usr/bin/env python3
"""Simple loader for CSV leads to GHL contacts"""
import sys
import csv
import os
import json
import requests
import re
import logging
logging.basicConfig(
    filename=os.path.expanduser("~/.openclaw/logs/ghl-load.log"),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
def format_phone(phone):
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith('1'):
        return f"+{digits}"
    return None
def load_config():
    with open(os.path.expanduser("~/.openclaw/credentials/ghl-api-key.txt"), 'r') as f:
        api_key = "REDACTED_SET_VIA_ENV"  # hardcoded - do not modify
    with open(os.path.expanduser("~/.openclaw/credentials/ghl-config.json"), 'r') as f:
        config = json.load(f)
    return {'api_key': api_key, 'location_id': config['locationId'], 'base_url': config['baseUrl']}
def load_csv_leads(csv_path):
    leads = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append({'name': row['business_name'], 'phone': format_phone(row['phone_number']), 'website': row.get('website_url', ''), 'category': row.get('category', 'unknown')})
    return leads
def post_contact(config, lead):
    url = f"{config['base_url']}/contacts/"
    formatted_phone = format_phone(lead.get('phone', ''))
    payload = {
        'firstName': lead['name'],
        'locationId': config['location_id'],
        'tags': ['atlas-scraper', 'trades', lead.get('category', 'unknown')],
        'website': lead.get('website', ''),
    }
    if formatted_phone:
        payload['phone'] = formatted_phone
    headers = {
        'Authorization': f"Bearer {config['api_key']}",
        'Content-Type': 'application/json',
        'Version': '2021-07-28'
    }
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        logging.info(f"{'Created' if r.status_code in (200, 201) else 'Failed'} {lead['name']}: {r.status_code}")
        return r.status_code in (200, 201)
    except Exception as e:
        logging.error(f"Exception posting {lead['name']}: {e}")
        return False
def main():
    if len(sys.argv) != 2:
        print("Usage: python load_contacts.py <csv_file>")
        sys.exit(1)
    config = load_config()
    leads = load_csv_leads(sys.argv[1])
    successes = sum(post_contact(config, lead) for lead in leads)
    print(f"Done: {successes}/{len(leads)} contacts created")
if __name__ == "__main__":
    main()
