#!/usr/bin/env python3
"""Google Places scraper → GHL contact uploader with Hunter.io email enrichment.

NEW FEATURE: Website quality checking - only pushes "bad" websites to GHL.

Usage:
    python3 scraper_to_ghl_v2.py --search "98501" --trades "plumber"

Filters:
    - No website: Keep (tags: atlas-scraper, plumber, no-website)
    - Bad website: Keep (tags: atlas-scraper, plumber, bad-website)
    - Good website: Skip (don't add to GHL)

Bad website = missing SSL OR missing mobile viewport OR low PageSpeed score
"""

import sys
sys.path.insert(0, "/Users/example/.openclaw/scripts")

import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import requests
from website_quality_checker import check_website_quality

# --- Config ---
ENV_PATH = Path.home() / ".openclaw/.env"
CACHE_FILE = Path.home() / ".openclaw/data/ghl_posted.json"
LOG_DIR = Path.home() / ".openclaw/logs"
LOG_FILE = LOG_DIR / "ghl_post.log"
GHL_BASE = "https://services.leadconnectorhq.com/contacts/"
LOCATION_ID = "SHOWCASE_GHL_LOCATION_ID"
PLACES_TEXT_SEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
HUNTER_BASE = "https://api.hunter.io/v2/domain-search"
TRADES_DEFAULT = ["plumber", "electrician", "HVAC", "roofer"]

# Ensure dirs
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# --- Load env ---
env = {}
if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")

GHL_KEY = env.get("GHL_API_KEY", "")
PLACES_KEY = env.get("GOOGLE_PLACES_API_KEY", "")
HUNTER_KEY = env.get("HUNTER_API_KEY", "")

if not GHL_KEY:
    print("ERROR: GHL_API_KEY not found in ~/.openclaw/.env")
    sys.exit(1)

GHL_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {GHL_KEY}",
    "Version": "2021-07-28",
}

# --- Load cache ---
posted = set()
if CACHE_FILE.exists():
    try:
        with open(CACHE_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    posted.add(line)
    except Exception:
        pass

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")

# ==================== Google Places ====================
def search_places(city, trade):
    """Text Search for a trade in a city. Returns list of basic results."""
    if not PLACES_KEY:
        log(f"PLACES_SKIP reason=no_GOOGLE_PLACES_API_KEY")
        return []
    results = []
    query = f"{trade} in {city}"
    next_token = None
    while True:
        params = {"query": query, "key": PLACES_KEY}
        if next_token:
            params["pagetoken"] = next_token
        resp = requests.get(PLACES_TEXT_SEARCH, params=params, timeout=20)
        if resp.status_code != 200:
            log(f"PLACES_SEARCH_FAIL query={query} status={resp.status_code}")
            break
        data = resp.json()
        results.extend(data.get("results", []))
        next_token = data.get("next_page_token")
        if not next_token:
            break
        break  # One page per query for speed
    log(f"PLACES_SEARCH query={query} results={len(results)}")
    return results

def get_place_details(place_id):
    """Fetch full details for a single place_id."""
    if not PLACES_KEY:
        return None
    resp = requests.get(
        PLACES_DETAILS,
        params={
            "place_id": place_id,
            "key": PLACES_KEY,
            "fields": "name,formatted_phone_number,international_phone_number,website,formatted_address,place_id,types,rating",
        },
        timeout=20,
    )
    if resp.status_code != 200:
        log(f"PLACES_DETAIL_FAIL place_id={place_id} status={resp.status_code}")
        return None
    result = resp.json().get("result")
    if result:
        log(f"PLACES_DETAIL place_id={place_id} name={result.get('name','?')} website={result.get('website','none')} phone={result.get('formatted_phone_number','none')}")
    return result

def scrape_city(city, trades_list, max_results=0):
    """Scrape trades in a city. Returns normalized records.
    
    NEW LOGIC:
    - If website exists: Run quality check
      - If bad website: Keep with "bad-website" tag
      - If good website: Skip
    - If no website: Keep with "no-website" tag
    """
    records = []
    seen = set()
    total_found = 0
    skipped_good_websites = 0
    
    for trade in trades_list:
        results = search_places(city, trade)
        for r in results:
            if max_results > 0 and total_found >= max_results:
                break
                
            pid = r.get("place_id", "")
            if not pid or pid in seen or pid in posted:
                continue
            seen.add(pid)
            
            details = get_place_details(pid)
            if not details:
                continue
            
            website = details.get("website", "")
            business_name = details.get("name", "?")
            
            if website:
                # Has website - run quality check
                log(f"QUALITY_CHECK place_id={pid} name={business_name} website={website}")
                quality = check_website_quality(website)
                
                if quality.get("is_bad_website", False):
                    # Bad website - keep it
                    record = {
                        "place_id": pid,
                        "name": business_name,
                        "phone": details.get("international_phone_number", "") or details.get("formatted_phone_number", ""),
                        "website": website,
                        "address": details.get("formatted_address", ""),
                        "types": details.get("types", []),
                        "rating": details.get("rating"),
                        "website_quality": quality,
                        "website_status": "bad-website",  # Tag
                    }
                    records.append(record)
                    flags = quality.get("flags", [])
                    log(f"KEEP_BAD_WEBSITE place_id={pid} name={business_name} flags={','.join(flags) if flags else 'none'}")
                    total_found += 1
                else:
                    # Good website - skip
                    skipped_good_websites += 1
                    log(f"SKIP_GOOD_WEBSITE place_id={pid} name={business_name} score={quality.get('quality_score', 'N/A')}")
            else:
                # No website - keep it  
                record = {
                    "place_id": pid,
                    "name": business_name,
                    "phone": details.get("international_phone_number", "") or details.get("formatted_phone_number", ""),
                    "website": "",
                    "address": details.get("formatted_address", ""),
                    "types": details.get("types", []),
                    "rating": details.get("rating"),
                    "website_status": "no-website",  # Tag
                }
                records.append(record)
                log(f"KEEP_NO_WEBSITE place_id={pid} name={business_name}")
                total_found += 1
                
            if max_results > 0 and total_found >= max_results:
                break
                
    log(f"SCRAPE_CITY city={city} trades={trades_list} total_new={len(records)} skipped_good_websites={skipped_good_websites}")
    return records


# ==================== Hunter.io Enrichment ====================

def guess_domain(record):
    website = record.get("website", "")
    if website:
        parsed = urlparse(website if "://" in website else f"http://{website}")
        if parsed.netloc:
            return parsed.netloc.lower().replace("www.", "")
    name = record.get("name", "")
    if name:
        slug = re.sub(r"[^a-z0-9]+", "", name.lower())
        if slug:
            return f"{slug}.com"
    return None


def enrich_email(contact_id, record):
    if not HUNTER_KEY:
        log(f"ENRICH_SKIP contact_id={contact_id} reason=no_HUNTER_API_KEY")
        return
    domain = guess_domain(record)
    if not domain:
        log(f"ENRICH_SKIP contact_id={contact_id} reason=no_domain")
        return
    try:
        resp = requests.get(HUNTER_BASE, params={"domain": domain, "api_key": HUNTER_KEY}, timeout=15)
        if resp.status_code != 200:
            log(f"ENRICH_FAIL contact_id={contact_id} domain={domain} hunter_status={resp.status_code}")
            return
        emails = resp.json().get("data", {}).get("emails", [])
        if not emails:
            log(f"ENRICH_NONE contact_id={contact_id} domain={domain}")
            return
        best = sorted(emails, key=lambda e: e.get("confidence", 0), reverse=True)[0]
        email = best.get("value", "")
        confidence = best.get("confidence", 0)
        if not email:
            return
        patch_url = f"{GHL_BASE}{contact_id}"
        pr = requests.put(patch_url, headers=GHL_HEADERS, json={"email": email}, timeout=15)
        if 200 <= pr.status_code < 300:
            log(f"ENRICH_OK contact_id={contact_id} email={email} confidence={confidence}")
        else:
            log(f"ENRICH_PATCH_FAIL contact_id={contact_id} email={email} status={pr.status_code}")
    except Exception as e:
        log(f"ENRICH_EXCEPTION contact_id={contact_id} error={e}")


# ==================== GHL Upload ====================

def upload_to_ghl(record):
    place_id = record.get("place_id", "")
    if place_id in posted:
        log(f"SKIP duplicate place_id={place_id}")
        return False

    website = record.get("website", "")
    tags = list(record.get("types", [])) + ["atlas-scraper"]
    
    # Add trade tag (e.g., "plumber") - assuming a single trade per scrape_city call
    trade_tag = next((t for t in TRADES_DEFAULT if t in record.get("types", [])), "")
    if trade_tag:
        tags.append(trade_tag)
    else:
        # Fallback if trade not in types (e.g. for plumber-only scrapes)
        tags.append("plumber") # Default to plumber for this specific task

    # Add website status tag
    website_status = record.get("website_status")
    if website_status == "no-website":
        tags.append("no-website")
    elif website_status == "bad-website":
        tags.append("bad-website")

    payload = {
        "locationId": LOCATION_ID,
        "firstName": record.get("name", ""),
        "lastName": "Lead",
        "companyName": record.get("name", ""),
        "phone": record.get("phone", ""),
        "address1": record.get("address", ""),
        "website": website,
        "tags": tags,
    }

    try:
        resp = requests.post(GHL_BASE, headers=GHL_HEADERS, json=payload, timeout=20)
        if 200 <= resp.status_code < 300:
            cid = resp.json().get("contact", {}).get("id", "unknown")
            log(f"GHL_OK place_id={place_id} contact_id={cid} company={payload['companyName']} website={website or 'none'} tags={tags}")
            posted.add(place_id)
            with open(CACHE_FILE, "a") as f:
                f.write(place_id + "\n")
            enrich_email(cid, record)
            return True
        else:
            error_body = resp.text
            if resp.status_code == 400 and "This location does not allow duplicated contacts." in error_body:
                log(f"GHL_SKIP_DUPLICATE place_id={place_id} status={resp.status_code} body={error_body[:200]}")
                # Treat as a skip rather than a hard fail for our local count, as the contact exists in GHL
                # We still consider it a "bad_website_contact" for the final tally if it was marked as such.
                return True # Indicate successful handling (skipped, not failed)
            else:
                log(f"GHL_FAIL place_id={place_id} status={resp.status_code} body={error_body[:200]}")
                return False
    except Exception as e:
        log(f"GHL_EXCEPTION place_id={place_id} error={e}")
        return False


# ==================== Main ====================

def main():
    parser = argparse.ArgumentParser(description="Scrape trades → GHL contacts")
    parser.add_argument("--search", type=str, help="City/zip to scrape (e.g. 'Olympia, WA')")
    parser.add_argument("--trades", type=str, default=",".join(TRADES_DEFAULT), help="Comma-separated trades to search")
    parser.add_argument("--max", type=int, default=0, help="Max results to upload (0=unlimited)")
    parser.add_argument("file", nargs="?", help="JSONL file path (or stdin)")
    args = parser.parse_args()

    records = []

    if args.search:
        # Live Google Places scrape
        trades_list = [t.strip() for t in args.trades.split(",") if t.strip()]
        records = scrape_city(args.search, trades_list, max_results=args.max)
    elif args.file:
        with open(args.file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        log(f"PARSE_ERROR line={line[:80]}")
    else:
        # If no file/search args, try reading stdin if data is piped
        if not sys.stdin.isatty():
             for line in sys.stdin:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        log(f"PARSE_ERROR line={line[:80]}")

    success_count = 0
    fail_count = 0
    skip_count = 0
    bad_website_count = 0
    no_website_count = 0
    
    # Process scraped records (upload to GHL)
    for rec in records:
        pid = rec.get("place_id", "")
        if pid in posted: # Double check in case duplicate encountered
            skip_count += 1
            log(f"SKIP duplicate place_id={pid}")
            continue
        
        if upload_to_ghl(rec):
            success_count += 1
            if rec.get("website_status") == "bad-website":
                bad_website_count += 1
            elif rec.get("website_status") == "no-website":
                no_website_count += 1
        else:
            fail_count += 1

    print(f"Done. success={success_count} fail={fail_count} skip={skip_count} bad_website_contacts={bad_website_count} no_website_contacts={no_website_count}")


if __name__ == "__main__":
    main()
