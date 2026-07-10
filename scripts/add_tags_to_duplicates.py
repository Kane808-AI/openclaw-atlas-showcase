#!/usr/bin/env python3
"""Add bad-website tag to existing GHL contacts that failed duplicate check."""

import re
import json
from pathlib import Path
import requests

# Config
ENV_PATH = Path.home() / ".openclaw/.env"
LOG_FILE = Path.home() / ".openclaw/logs/ghl_post.log"

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
LOCATION_ID = "SHOWCASE_GHL_LOCATION_ID"
GHL_BASE = "https://services.leadconnectorhq.com/contacts/"

GHL_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GHL_KEY}",
    "Version": "2021-07-28",
}

def extract_duplicate_contacts():
    """Extract contacts that failed with duplicate error from log."""
    if not LOG_FILE.exists():
        print(f"ERROR: Log file not found: {LOG_FILE}")
        return []
    
    with open(LOG_FILE, 'r') as f:
        content = f.read()
    
    # Find recent GHL_FAIL entries (from today's run)
    # Pattern: GHL_FAIL place_id=XXX status=422 body={...duplicate...}
    duplicates = []
    
    # Find the entries from the most recent quality check run
    # Look for entries after the last "PUSHING BAD WEBSITES TO GHL"
    last_push_pos = content.rfind("PUSHING BAD WEBSITES TO GHL")
    if last_push_pos == -1:
        print("Could not find PUSHING marker in log")
        return []
    
    recent_content = content[last_push_pos:]
    
    # Find GHL_FAIL entries with status 400 (duplicate)
    for line in recent_content.split('\n'):
        if 'GHL_FAIL' in line and 'place_id=' in line:
            # Extract place_id and phone from the error
            place_match = re.search(r'place_id=(\S+)', line)
            if place_match:
                place_id = place_match.group(1)
                
                # Look for contact name and phone in the error body
                name_match = re.search(r'"contactName":"([^"]+)"', line)
                phone_match = re.search(r'"matchingField":"([^"]+)"', line)
                
                name = name_match.group(1) if name_match else "Unknown"
                
                # Need to find the actual phone - let's look at the PLACES_DETAIL entry
                phone_pattern = rf'PLACES_DETAIL place_id={re.escape(place_id)}.*?phone=(\S+)'
                phone_match = re.search(phone_pattern, content)
                phone = phone_match.group(1) if phone_match else ""
                
                duplicates.append({
                    'place_id': place_id,
                    'name': name,
                    'phone': phone
                })
    
    return duplicates

def find_contact_by_phone(phone):
    """Search for a contact in GHL by phone number."""
    if not phone:
        return None
    
    # Clean phone number
    clean_phone = re.sub(r'[^\d]', '', phone)
    if not clean_phone:
        return None
    
    try:
        search_url = f"{GHL_BASE}?locationId={LOCATION_ID}&query={clean_phone}&limit=1"
        resp = requests.get(search_url, headers=GHL_HEADERS, timeout=15)
        
        if resp.status_code == 200:
            data = resp.json()
            contacts = data.get('contacts', [])
            if contacts:
                return contacts[0]['id']
        
        return None
    except Exception as e:
        print(f"  Error searching: {e}")
        return None

def add_tag_to_contact(contact_id, tag):
    """Add a tag to an existing GHL contact."""
    try:
        # First get current contact
        get_url = f"{GHL_BASE}{contact_id}"
        resp = requests.get(get_url, headers=GHL_HEADERS, timeout=15)
        
        if resp.status_code != 200:
            print(f"  Failed to get contact: {resp.status_code}")
            return False
        
        contact = resp.json().get('contact', {})
        current_tags = contact.get('tags', [])
        
        # Add new tag if not already present
        if tag not in current_tags:
            current_tags.append(tag)
        else:
            print(f"  Tag '{tag}' already exists")
            return True
        
        # Update contact with new tags
        patch_url = f"{GHL_BASE}{contact_id}"
        resp = requests.put(patch_url, headers=GHL_HEADERS, 
                          json={"tags": current_tags}, timeout=15)
        
        if 200 <= resp.status_code < 300:
            return True
        else:
            print(f"  Failed to update: {resp.status_code}")
            return False
            
    except Exception as e:
        print(f"  Error: {e}")
        return False

def main():
    print("=" * 80)
    print("ADD BAD-WEBSITE TAG TO DUPLICATE CONTACTS")
    print("=" * 80)
    print()
    
    # Get the duplicate contacts from the log
    print("Extracting duplicate contacts from log...")
    duplicates = []
    
    # List of the 15 failed contacts (from previous run output)
    failed_contacts = [
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
        {"name": "Lacey Local Plumbing", "website": "http://aquapointco.com/"},
    ]
    
    print(f"Found {len(failed_contacts)} contacts to tag")
    print()
    
    # Process each contact
    success_count = 0
    fail_count = 0
    not_found_count = 0
    
    print("Processing contacts...")
    print("=" * 80)
    
    for contact in failed_contacts:
        name = contact['name']
        print(f"\n{name}...")
        
        # For now, we need to query GHL to find these contacts
        # Since we don't have phone numbers in the log easily accessible,
        # let's try the GHL search API with the company name
        
        try:
            search_url = f"{GHL_BASE}?locationId={LOCATION_ID}&query={name}&limit=10"
            resp = requests.get(search_url, headers=GHL_HEADERS, timeout=15)
            
            if resp.status_code == 200:
                data = resp.json()
                contacts = data.get('contacts', [])
                
                if contacts:
                    # Take the first matching contact
                    contact_id = contacts[0].get('id')
                    if not contact_id:
                        print("  No contact id returned")
                        not_found_count += 1
                        continue
                    if add_tag_to_contact(contact_id, 'bad-website'):
                        print(f"  Tagged contact {contact_id}")
                        success_count += 1
                    else:
                        print(f"  Failed to tag contact {contact_id}")
                        fail_count += 1
                else:
                    print("  No matching contact found")
                    not_found_count += 1
            else:
                print(f"  Search failed: HTTP {resp.status_code}")
                fail_count += 1
        except Exception as exc:
            print(f"  Error: {exc}")
            fail_count += 1

    print()
    print("=" * 80)
    print(f"Tagged: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Not found: {not_found_count}")


if __name__ == "__main__":
    main()
