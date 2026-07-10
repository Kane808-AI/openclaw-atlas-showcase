#!/usr/bin/env python3
"""Patch website field on existing GHL contacts from CSV"""
import sys
import csv
import os
import json
import requests
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
def load_config():
    with open(os.path.expanduser("~/.openclaw/credentials/ghl-api-key.txt"), 'r') as f:
        api_key = f.read().strip()
    with open(os.path.expanduser("~/.openclaw/credentials/ghl-config.json"), 'r') as f:
        config = json.load(f)
    return {'api_key': api_key, 'location_id': config['locationId'], 'base_url': config['baseUrl']}
def find_contact_by_phone(config, phone):
    url = f"{config['base_url']}/contacts/"
    params = {'locationId': config['location_id'], 'query': phone}
    headers = {'Authorization': f"Bearer {config['api_key']}", 'Version': '2021-07-28'}
    r = requests.get(url, params=params, headers=headers, timeout=30)
    if r.status_code == 200:
        contacts = r.json().get('contacts', [])
        return contacts[0]['id'] if contacts else None
    return None
def patch_contact_website(config, contact_id, website):
    url = f"{config['base_url']}/contacts/{contact_id}"
    payload = {'website': website}
    headers = {'Authorization': f"Bearer {config['api_key']}", 'Content-Type': 'application/json', 'Version': '2021-07-28'}
    r = requests.put(url, json=payload, headers=headers, timeout=30)
    return r.status_code == 200
def main():
    if len(sys.argv) != 2:
        print("Usage: python patch_website_field.py <csv_file>")
        sys.exit(1)
    config = load_config()
    updated = 0
    skipped = 0
    with open(sys.argv[1], 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            phone = row.get('phone_number', '').strip()
            website = row.get('website_url', '').strip()
            if not phone:
                skipped += 1
                continue
            contact_id = find_contact_by_phone(config, phone)
            if not contact_id:
                logging.warning(f"Not found: {row['business_name']}")
                skipped += 1
                continue
            if patch_contact_website(config, contact_id, website):
                logging.info(f"Updated: {row['business_name']} → {website}")
                updated += 1
            else:
                logging.warning(f"Failed: {row['business_name']}")
                skipped += 1
    print(f"Done: {updated} updated, {skipped} skipped")
if __name__ == "__main__":
    main()
