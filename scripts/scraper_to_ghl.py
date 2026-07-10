#!/usr/bin/env python3
"""Google Places scraper → GHL contact uploader with Hunter.io email enrichment.

Usage:
  # Scrape + upload trades in a city:
  python3 scraper_to_ghl.py --search "Olympia, WA"

  # Or pipe pre-existing JSONL (one record per line):
  cat leads.jsonl | python3 scraper_to_ghl.py

Deduplicates by place_id against a local cache.
After creating a contact, attempts email enrichment via Hunter.io domain search.
"""
import sys
import json
import re
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import requests

# --- Config ---
ENV_PATH = Path.home() / ".openclaw/.env"
CACHE_FILE = Path.home() / ".openclaw/data/ghl_posted.json"
LOG_DIR = Path.home() / ".openclaw/logs"
LOG_FILE = LOG_DIR / "ghl_post.log"
GHL_BASE = "https://services.leadconnectorhq.com/contacts/"
LOCATION_ID = "WbjKV1nKqrMFAFBwAplZ"
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
        # Limit to 20 results per search call to be safe/fast for now, unless pagination loop is really needed
        # Google returns max 20 per page. For this targeted run, one page per trade is likely enough to hit 20 total.
        break 
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
    """Scrape trades in a city. Returns normalized records."""
    records = []
    seen = set()
    total_found = 0

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
            
            # Filter for businesses with no website
            if details.get("website"):
                log(f"SKIP_WEBSITE place_id={pid} name={details.get('name','?')} reason=has_website")
                continue
                
            records.append({
                "place_id": pid,
                "name": details.get("name", ""),
                "phone": details.get("international_phone_number", "") or details.get("formatted_phone_number", ""),
                "website": details.get("website", ""),
                "address": details.get("formatted_address", ""),
                "types": details.get("types", []),
                "rating": details.get("rating"),
            })
            total_found += 1
            
        if max_results > 0 and total_found >= max_results:
            break
            
    log(f"SCRAPE_CITY city={city} trades={trades_list} total_new={len(records)}")
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
    tags = list(record.get("types", [])) + ["atlas-scraper", "plumber"]
    if not website:
        tags.append("no-website")

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
            log(f"GHL_OK place_id={place_id} contact_id={cid} company={payload['companyName']} website={website or 'none'}")
            posted.add(place_id)
            with open(CACHE_FILE, "a") as f:
                f.write(place_id + "\n")
            enrich_email(cid, record)
            return True
        else:
            log(f"GHL_FAIL place_id={place_id} status={resp.status_code} body={resp.text[:200]}")
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

    success = 0
    fail = 0
    skip = 0
    
    # Process scraped records (upload to GHL)
    for rec in records:
        pid = rec.get("place_id", "")
        if pid in posted: # Double check in case duplicate encountered
            skip += 1
            log(f"SKIP duplicate place_id={pid}")
            continue
        if upload_to_ghl(rec):
            success += 1
        else:
            fail += 1

    print(f"Done. success={success} fail={fail} skip={skip}")


if __name__ == "__main__":
    main()
