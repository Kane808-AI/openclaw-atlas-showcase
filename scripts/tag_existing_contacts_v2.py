#!/usr/bin/env python3
"""Add bad-website tag to existing GHL contacts - version 2 using search."""

import os
import re
import requests
from pathlib import Path

# Config
ENV_PATH = Path.home() / ".openclaw/.env"
LOCATION_ID = "WbjKV1nKqrMFAFBwAplZ"
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

# The 15 failed companies
FAILED_COMPANIES = [
    {"name": "Olympia Plumbing Solutions", "flags": "no_ssl"},
    {"name": "Lacey 24/7 Plumbing Pros", "flags": "no_ssl"},
    {"name": "Sound Rooter and Plumbing, LLC", "flags": "low_pagespeed"},
    {"name": "White Knight Plumbing", "flags": "low_pagespeed"},
    {"name": "Lacey UltraCare Plumbing", "flags": "no_ssl"},
    {"name": "Evergreen State Plumbing", "flags": "no_ssl"},
    {"name": "Boyd's Plumbing", "flags": "no_ssl"},
    {"name": "Trusted Lacey Plumbing Experts", "flags": "no_ssl"},
    {"name": "Olympia Plumbing Pros", "flags": "no_ssl"},
    {"name": "Hardie Plumbing", "flags": "no_ssl"},
    {"name": "Treat Plumbing", "flags": "unreachable"},
    {"name": "John's Plumbing & Pumps, Inc", "flags": "no_ssl"},
    {"name": "Capital Heating, Cooling, Plumbing & Electric", "flags": "no_ssl"},
    {"name": "West Coast Plumbing Pumps & Filtration, LLC", "flags": "no_mobile_viewport"},
    {"name": "On the Level Plumbing", "flags": "no_ssl, no_mobile_viewport"},
]

def normalize_name(name):
    """Normalize name for comparison."""
    if not name:
        return ""
    # Remove common suffixes/prefixes and lowercase
    name = name.lower()
    name = re.sub(r'\b(llc|inc|corp|co|ltd)\b', '', name)
    name = re.sub(r'[^a-z]', '', name)
    return name

def search_contact_by_name(name):
    """Search for a contact by name in GHL."""
    try:
        search_url = f"{GHL_BASE}search"
        params = {
            "locationId": LOCATION_ID,
            "query": name,
            "limit": 10
        }
        
        resp = requests.post(search_url, headers=GHL_HEADERS, json=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            contacts = data.get('contacts', [])
            return contacts
        else:
            # Fall back to regular search
            params = {
                "locationId": LOCATION_ID,
                "query": name,
                "limit": 10
            }
            resp = requests.get(GHL_BASE, headers=GHL_HEADERS, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json().get('contacts', [])
        return []
    except Exception as e:
        print(f"  Search error: {e}")
        return []

def get_contacts(limit=500):
    """Get all contacts from GHL."""
    contacts = []
    cursor = None
    
    while len(contacts) < limit:
        params = {
            "locationId": LOCATION_ID,
            "limit": 100,
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
                
                meta = data.get('meta', {})
                cursor = meta.get('nextCursor')
                if not cursor:
                    break
            else:
                print(f"  API error: {resp.status_code}")
                break
        except Exception as e:
            print(f"  Error: {e}")
            break
    
    return contacts

def match_by_name(contact, failed_list):
    """Check if contact name matches any failed company."""
    contact_name = contact.get('firstName', '') or contact.get('companyName', '') or ''
    contact_name_norm = normalize_name(contact_name)
    
    for failed in failed_list:
        failed_name_norm = normalize_name(failed['name'])
        
        # Check if either contains the other
        if failed_name_norm in contact_name_norm or contact_name_norm in failed_name_norm:
            return failed
    
    return None

def update_contact_tags(contact_id, current_tags):
    """Add bad-website tag to contact."""
    if not contact_id:
        print("  No contact ID")
        return False
    
    if "bad-website" in current_tags:
        print(f"  Already has bad-website tag")
        return True
    
    new_tags = list(set(current_tags + ["bad-website"]))
    
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
    print("TAG EXISTING GHL CONTACTS WITH BAD-WEBSITE (v2)")
    print("=" * 80)
    print()
    
    # Get all contacts
    print("Fetching contacts from GHL...")
    contacts = get_contacts(limit=500)
    print(f"Found {len(contacts)} total contacts")
    print()
    
    # Filter for ones with atlas-scraper tag
    print("Filtering for atlas-scraper contacts...")
    tagged_contacts = [c for c in contacts if 'atlas-scraper' in c.get('tags', [])]
    print(f"Found {len(tagged_contacts)} contacts with atlas-scraper tag")
    print()
    
    # Match and tag
    print("Matching against failed companies and tagging...")
    print("=" * 80)
    
    newly_tagged = []
    already_tagged = []
    failed_updates = []
    no_match = []
    
    for contact in tagged_contacts:
        contact_id = contact.get('id')
        contact_name = contact.get('firstName') or contact.get('companyName', 'Unknown')
        current_tags = contact.get('tags', [])
        
        # Match against failed companies
        match = match_by_name(contact, FAILED_COMPANIES)
        
        if match:
            print(f"\n✓ {contact_name}")
            print(f"  Matched: {match['name']}")
            print(f"  Issue: {match['flags']}")
            print(f"  Current tags: {current_tags}")
            
            if update_contact_tags(contact_id, current_tags):
                print(f"  → ✓ Tagged with bad-website")
                if "bad-website" in current_tags:
                    already_tagged.append((contact, match))
                else:
                    newly_tagged.append((contact, match))
            else:
                print(f"  → ✗ Failed to update")
                failed_updates.append((contact, match))
        else:
            no_match.append(contact)
    
    # Summary
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Atlas-scraper contacts checked:      {len(tag