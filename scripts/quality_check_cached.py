#!/usr/bin/env python3
"""Quality check cached plumber websites from previous scrapes."""

import sys
sys.path.insert(0, "/Users/example/.openclaw/scripts")

import re
import json
from pathlib import Path
from website_quality_checker import check_website_quality
from scraper_to_ghl_v2 import upload_to_ghl, log

LOG_FILE = Path.home() / ".openclaw/logs/ghl_post.log"

def extract_plumber_websites_from_log():
    """Extract unique plumber entries with websites from the log."""
    if not LOG_FILE.exists():
        print(f"ERROR: Log file not found: {LOG_FILE}")
        return []
    
    plumbers = {}
    
    with open(LOG_FILE, 'r') as f:
        content = f.read()
    
    # Find all PLACES_DETAIL entries for plumbers with websites
    # Pattern: PLACES_DETAIL place_id=XXX name=XXX website=XXX phone=XXX
    pattern = r'\[.*?\] PLACES_DETAIL place_id=(\S+) name=(.*?) website=(\S+) phone=(.*?)(?:\n|$)'
    matches = re.findall(pattern, content, re.MULTILINE)
    
    for place_id, name, website, phone in matches:
        # Skip non-plumbers and entries without real websites
        if not any(word in name.lower() for word in ['plumb', 'rooter', 'pipe', 'water']):
            continue
        if website == 'none' or not website.startswith('http'):
            continue
        
        # Get the most recent entry for this place_id
        if place_id not in plumbers:
            plumbers[place_id] = {
                'place_id': place_id,
                'name': name.strip(),
                'website': website,
                'phone': phone.strip() if phone else ''
            }
    
    return list(plumbers.values())

def main():
    print("=" * 80)
    print("CACHED PLUMBER WEBSITE QUALITY CHECK")
    print("=" * 80)
    print()
    
    # Extract cached plumber data
    print("Extracting cached plumber data from log...")
    plumbers = extract_plumber_websites_from_log()
    print(f"Found {len(plumbers)} unique plumbers with websites in cache")
    print()
    
    if not plumbers:
        print("No plumbers with websites found in cache.")
        return
    
    # Run quality checks
    print("Running website quality checks...")
    print("=" * 80)
    
    bad_websites = []
    good_websites = []
    failed_checks = []
    
    for i, plumber in enumerate(plumbers, 1):
        url = plumber['website']
        name = plumber['name']
        
        print(f"\n{i}/{len(plumbers)}: {name}")
        print(f"  URL: {url}")
        
        try:
            quality = check_website_quality(url)
            
            score = quality.get('quality_score', 0)
            has_ssl = quality.get('has_ssl', False)
            has_viewport = quality.get('has_mobile_viewport', False)
            pagespeed = quality.get('pagespeed_score', 'N/A')
            flags = quality.get('flags', [])
            
            print(f"  SSL: {'✓' if has_ssl else '✗'}")
            print(f"  Mobile: {'✓' if has_viewport else '✗'}")
            print(f"  PageSpeed: {pagespeed}")
            print(f"  Quality Score: {score}")
            print(f"  Flags: {', '.join(flags) if flags else 'None'}")
            
            if quality.get('is_bad_website', False):
                print(f"  → BAD WEBSITE (will push to GHL)")
                bad_websites.append({
                    **plumber,
                    'quality': quality
                })
            else:
                print(f"  → GOOD WEBSITE (skip)")
                good_websites.append({
                    **plumber,
                    'quality': quality
                })
                
        except Exception as e:
            print(f"  → ERROR: {e}")
            failed_checks.append({**plumber, 'error': str(e)})
    
    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total plumbers with websites:     {len(plumbers)}")
    print(f"Bad websites (will push):       {len(bad_websites)}")
    print(f"Good websites (will skip):      {len(good_websites)}")
    print(f"Failed checks:                    {len(failed_checks)}")
    print()
    
    # Show bad websites table
    if bad_websites:
        print("BAD WEBSITES TO PUSH TO GHL:")
        print("-" * 80)
        print(f"{'Company':<35} {'Website':<30} {'Score':<8} {'Flags'}")
        print("-" * 80)
        for p in bad_websites:
            flags = ', '.join(p['quality'].get('flags', []))
            score = p['quality'].get('quality_score', 0)
            website = p['website'][:28] + '..' if len(p['website']) > 30 else p['website']
            print(f"{p['name']:<35} {website:<30} {score:<8} {flags}")
        print()
    
    # Push bad websites to GHL
    if bad_websites:
        print("=" * 80)
        print("PUSHING BAD WEBSITES TO GHL")
        print("=" * 80)
        print()
        
        success_count = 0
        skip_count = 0
        fail_count = 0
        
        for p in bad_websites:
            print(f"Pushing: {p['name']}...")
            
            # Create record in expected format
            record = {
                'place_id': p['place_id'],
                'name': p['name'],
                'phone': p['phone'],
                'website': p['website'],
                'address': '',  # Not available from cache
                'types': ['plumber'],
                'website_status': 'bad-website',
                'website_quality': p['quality']
            }
            
            result = upload_to_ghl(record)
            if result:
                success_count += 1
                print(f"  ✓ Success")
            else:
                # upload_to_ghl returns False for actual failures
                # but returns records found in GHL as skipped (duplicates)
                fail_count += 1
                print(f"  ✗ Failed")
        
        print()
        print("=" * 80)
        print("PUSH RESULTS")
        print("=" * 80)
        print(f"Successfully pushed:  {success_count}")
        print(f"Failed:               {fail_count}")
        print(f"Total bad websites:   {len(bad_websites)}")
        print()
        print(f"Final count of bad-website contacts in GHL: {success_count}")
        print("=" * 80)

if __name__ == "__main__":
    main()
