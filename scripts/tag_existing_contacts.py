#!/usr/bin/env python3
"""Add bad-website tag to existing GHL contacts that match the 15 failed companies."""

import os
import re
import requests
from pathlib import Path

# Config
ENV_PATH = Path.home() / ".openclaw/.env"
LOCATION_ID = "SHOWCASE_GHL_LOCATION_ID"
GHL_BASE = "https://services.leadconnectorhq.com/contacts/"

# Load env
env = {}
if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")

GHL_KEY = env.get("GHL_API_KEY", "")

if not GHL_KEY:
    print("ERROR: GHL_API_KEY not found")
    exit(1)

GHL_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GHL_KEY}",
    "Version": "2021-07-28",
}

# The 15 failed companies (from previous run)
FAILED_COMPANIES = [
    {"name": "Olympia Plumbing Solutions", "website": "http://flowpointpros.com/"},
    {"name": "Lacey 24/7 Plumbing Pros", "website": "http://pureriseventures.com/"},
    {"name": "Sound Rooter and Plumbing, LLC", "website": "https://soundrooter.com/"},
    {"name": "White Knight Plumbing", "website": "https://plumbingolympia.com/"},
    {"name": "Lacey UltraCare Plumbing", "website": "http://pureriseventures.com/"},
    {"name": "Evergreen State Plumbing", "website": "http://aquapointco.com/"},
    {"name": "Boyd's Plumbing", "website": "http://www.boydsplumbing.com/"},
    {"name": "Trusted Lacey Plumbing Experts", "website": "http://aquapointco.com/"},
    {"name": "Olympia Plumbing Pros", "website": "http://swiftcoreco.com/"},
    {"name": "Hardie Plumbing", "website": "http://hardieplumbing.com/"},
    {"name": "Treat Plumbing", "website": "https://treatplumbingolympia.com/"},
    {"name": "John's Plumbing & Pumps, Inc", "website": "http://johnsplumbingandpumps.com/"},
    {"name": "Capital Heating, Cooling, Plumbing & Electric", "website": "http://www.comfortsince1937.com/"},
    {"name": "West Coast Plumbing Pumps & Filtration, LLC", "website": "https://www.westcoastplumbingandrooter.com/"},
    {"name": "On the Level Plumbing", "website": "http://www.onthelevelplumber.com/"},
    {"name": "Lacey Local Plumbing", "website": "http://aquapointco.com/"},  # This succeeded, but let's include it too
]

def clean_phone(phone):
    """Clean phone to digits only."""
    if not phone:
        return ""
    return re.sub(r'[^\d]', '', phone)

def get_contacts_with_tags(max_results=200):
    """Get all contacts tagged atlas-scraper and plumber from GHL."""
    contacts = []
    cursor = None
    
    print("Fetching contacts tagged with atlas-scraper and plumber...")
    
    while len(contacts) < max_results:
        params = {
            "locationId": LOCATION_ID,
            "limit": 100,
            "tags": "atlas-scraper,plumber",  # Only contacts with BOTH tags
        }
        if cursor:
            params["cursor"] = cursor
        
        try:
            resp = requests.get(GHL_BASE, headers=GHL_HEADERS, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                new_contacts = data.get('contacts', [])
                if not new_contacts:
                    break
                contacts.extend(new_contacts)
                print(f"  Fetched {len(contacts)} contacts so far...")
                
                # Check for pagination
                meta = data.get('meta', {})
                cursor = meta.get('nextCursor')
                if not cursor:
                    break
            else:
                print(f"  API error: {resp.status_code} - {resp.text[:200]}")
                break
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    return contacts

def match_contact_to_failed(contact, failed_companies):
    """Check if a GHL contact matches any of the failed companies."""
    contact_name = contact.get('firstName', '') or contact.get('companyName', '')
    contact_phone = clean_phone(contact.get('phone', ''))
    
    for failed in failed_companies:
        failed_name = failed['name'].lower()
        # Match by name similarity
        if failed_name in contact_name.lower() or contact_name.lower() in failed_name:
            return failed
        
        # Also check company name
        company_name = contact.get('companyName', '').lower()
        if failed_name in company_name or company_name in failed_name:
            return failed
    
    return None

def update_contact_tags(contact_id, current_tags):
    """Add bad-website tag to contact."""
    if "bad-website" in current_tags:
        print(f"  Already has bad-website tag")
        return True
    
    new_tags = list(current_tags) + ["bad-website"]
    
    try:
        update_url = f"{GHL_BASE}{contact_id}"
        resp = requests.put(
            update_url,
            headers=GHL_HEADERS,
            json={"tags": new_tags},
            timeout=15
        )
        
        if 200 <= resp.status_code < 300:
            return True
        else:
            print(f"  Update failed: {resp.status_code} - {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

def main():
    print("=" * 80)
    print("TAG EXISTING GHL CONTACTS WITH BAD-WEBSITE")
    print("=" * 80)
    print()
    
    # Get atlas-scraper plumber contacts
    contacts = get_contacts_with_tags()
    print(f"\nTotal contacts found: {len(contacts)}")
    print()
    
    # Match and update
    print("Matching and tagging...")
    print("=" * 80)
    
    matched = []
    already_tagged = []
    failed = []
    
    for contact in contacts:
        contact_id = contact.get('id')
        contact_name = contact.get('firstName') or contact.get('companyName', 'Unknown')
        current_tags = contact.get('tags', [])
        
        # Match against failed companies
        match = match_contact_to_failed(contact, FAILED_COMPANIES)
        
        if match:
            print(f"\n✓ {contact_name}")
            print(f"  Current tags: {current_tags}")
            
            if "bad-website" in current_tags:
                print(f"  → Already tagged")
                already_tagged.append(contact)
            else:
                print(f"  → Adding bad-website tag...")
                if update_contact_tags(contact_id, current_tags):
                    print(f"  → ✓ Success")
                    matched.append(contact)
                else:
                    print(f"  → ✗ Failed")
                    failed.append(contact)
    
    # Summary
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Atlas-scraper plumber contacts checked: {len(contacts)}")
    print(f"Matched failed companies:                {len(matched) + len(already_tagged) + len(failed)}")
    print(f"  - Newly tagged with bad-website:       {len(matched)}")
    print(f"  - Already had bad-website tag:         {len(already_tagged)}")
    print(f"  - Failed to tag:                       {len(failed)}")
    print()
    print(f"Final count of bad-website tagged plumber contacts: {len(matched) + len(already_tagged)}")
    print("=" * 80)

if __name__ == "__main__":
    main()
