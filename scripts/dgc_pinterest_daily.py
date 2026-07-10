#!/usr/bin/env python3
"""
DGC Pinterest Daily Poster — posts up to 3 new DGC affiliate pins per day.

Pulls product data from the DGC Pinterest manifest, dedupes against the post log,
and posts via Pinterest API v5. Token refresh is handled by the JS script.

Usage:
  python3 dgc_pinterest_daily.py

Exit codes:
  0 = success (1-3 pins posted)
  1 = no unposted products in manifest
  2 = API error / rate limit
  3 = manifest not found or not ACTIVE
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from datetime import date

WORKSPACE = Path.home() / ".openclaw" / "workspace"
DGC_MANIFEST = WORKSPACE / "agents" / "builder" / "deliverables" / "pinterest" / "dgc-pinterest-manifest.md"
POST_LOG = WORKSPACE / "social-monitor" / "pinterest-post-log.json"
TOKEN_PATH = Path.home() / ".openclaw" / "credentials" / "pinterest" / "token.json"
JS_POSTER = Path.home() / ".openclaw" / "scripts" / "pinterest_api_post.js"

# Board name → board_id mapping
BOARD_IDS = {
    "ai_smart_home": "502644077101126211",
    "home_office": "502644077101126212",
    "audio_recording": "502644077101126213",
    "tech_gifts_dads": "502644077101126214",
    "portable_power": "502644077101126215",
}

# Board name normalization (manifest uses display names)
BOARD_NAME_MAP = {
    "AI & Smart Home Gadgets": "ai_smart_home",
    "Home Office & Desk Setup Essentials": "home_office",
    "Audio & Recording Gear": "audio_recording",
    "Tech Gifts for Dads": "tech_gifts_dads",
    "Portable Power & On-the-Go Tech": "portable_power",
}


def parse_dgc_manifest():
    """Parse the DGC manifest markdown table into a list of product dicts."""
    if not DGC_MANIFEST.exists():
        print(f"ERROR: Manifest not found at {DGC_MANIFEST}")
        return None

    content = DGC_MANIFEST.read_text()

    # Check the status line (first 10 lines, not in checklist bullets)
    status_line = None
    for line in content.splitlines()[:10]:
        if line.strip().startswith("**STATUS:"):
            status_line = line.strip()
            break

    if status_line is None:
        print("ERROR: Could not find STATUS line in manifest")
        return None

    if "STUB" in status_line:
        print("ERROR: Manifest is STATUS: STUB — not ready for posting")
        return None

    if "ACTIVE" not in status_line:
        print(f"ERROR: Manifest status is not ACTIVE: {status_line}")
        return None

    products = []
    in_table = False
    for line in content.splitlines():
        line = line.strip()
        # Detect table rows: must start with | and contain at least 4 pipes
        if line.startswith("|") and line.count("|") >= 5:
            cells = [c.strip() for c in line.split("|")]
            # Skip header and separator rows
            if cells[1].startswith("ASIN") or cells[1].startswith("---") or cells[1] == "":
                continue
            if len(cells) >= 6:
                asin = cells[1].strip()
                title = cells[2].strip()
                image_path = cells[3].strip()
                board_name = cells[4].strip()
                notes = cells[5].strip() if len(cells) > 5 else ""

                if asin and asin != "-" and not asin.startswith("B0"):
                    continue  # skip non-ASIN rows

                board_key = BOARD_NAME_MAP.get(board_name)
                if not board_key:
                    print(f"WARNING: Unknown board '{board_name}' for ASIN {asin}, skipping")
                    continue

                products.append({
                    "asin": asin,
                    "title": title,
                    "image_path": image_path,
                    "board_key": board_key,
                    "board_name": board_name,
                    "board_id": BOARD_IDS[board_key],
                    "notes": notes,
                })

    return products


def load_post_log():
    """Load the post log, return set of posted ASINs and the full data."""
    if not POST_LOG.exists():
        return set(), {"pins": []}

    data = json.loads(POST_LOG.read_text())
    posted_asins = set()
    for pin in data.get("pins", []):
        asin = pin.get("asin", "")
        if asin:
            posted_asins.add(asin)
    return posted_asins, data


def save_post_log(data):
    """Save updated post log."""
    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(POST_LOG, "w") as f:
        json.dump(data, f, indent=2)


def ensure_token():
    """Ensure the Pinterest token is valid by running a quick probe via the JS script."""
    if not TOKEN_PATH.exists():
        print("ERROR: No Pinterest token found. Run OAuth flow first.")
        return False

    token = json.loads(TOKEN_PATH.read_text())
    if not token.get("access_token"):
        return False

    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(
            "https://api.pinterest.com/v5/user_account",
            headers={"Authorization": f"Bearer {token['access_token']}"}
        )
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("Token expired — attempting refresh via JS script...")
            result = subprocess.run(
                ["node", str(JS_POSTER), "--dry-run"],
                capture_output=True, text=True, timeout=30,
                cwd=Path.home() / ".openclaw"
            )
            if "Token valid" in result.stdout:
                print("Token refreshed successfully.")
                return True
            else:
                print(f"Token refresh failed: {result.stderr[:200]}")
                return False
        else:
            print(f"Token probe failed: {e.code} {e.reason}")
            return False


def post_pin(asin, title, description, board_id, affiliate_url, image_path):
    """Post a single pin via Pinterest API v5."""
    import urllib.request, urllib.error

    token = json.loads(TOKEN_PATH.read_text())
    access_token = token["access_token"]

    # Resolve image path
    img_path = Path(image_path).expanduser()
    if not img_path.exists():
        # Try alternative locations
        alt = Path.home() / ".openclaw" / "media" / "tool-image-generation" / Path(image_path).name
        if alt.exists():
            img_path = alt
        else:
            print(f"ERROR: Image not found at {image_path} or {alt}")
            return None

    headers = {
        "Authorization": f"Bearer {access_token}",
    }

    # Step 1: Create media upload
    media_body = json.dumps({
        "media_type": "image",
        "file_name": img_path.name,
    }).encode()

    req = urllib.request.Request(
        "https://api.pinterest.com/v5/media",
        data=media_body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req)
        media_data = json.loads(resp.read())
        media_id = media_data.get("id")
        upload_url = media_data.get("upload_url")
        upload_headers = media_data.get("upload_parameters", {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"ERROR creating media: {e.code} {body[:300]}")
        return None

    if not upload_url:
        print(f"ERROR: No upload_url in media response: {json.dumps(media_data, indent=2)[:300]}")
        return None

    # Step 2: Upload the image file to the provided URL
    with open(img_path, "rb") as f:
        img_data = f.read()

    upload_req = urllib.request.Request(upload_url, data=img_data, method="POST")
    # Add upload parameters as headers
    for k, v in upload_headers.items():
        upload_req.add_header(k, v)
    upload_req.add_header("Content-Type", "image/jpeg")

    try:
        upload_resp = urllib.request.urlopen(upload_req)
        if upload_resp.status not in (200, 201, 204):
            print(f"WARNING: Image upload returned {upload_resp.status}")
    except urllib.error.HTTPError as e:
        print(f"ERROR uploading image: {e.code} {e.read().decode()[:200]}")
        return None

    # Step 3: Create the pin
    pin_body = json.dumps({
        "board_id": board_id,
        "title": title[:100],
        "description": description[:500],
        "link": affiliate_url,
        "media_source": {
            "source_type": "image_id",
            "content_type": "image/jpeg",
            "data": media_id,
        },
    }).encode()

    req = urllib.request.Request(
        "https://api.pinterest.com/v5/pins",
        data=pin_body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST"
    )
    try:
        resp = urllib.request.urlopen(req)
        pin_data = json.loads(resp.read())
        pin_id = pin_data.get("id")
        print(f"✅ Posted pin {pin_id}: {title[:60]}")
        return pin_id
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"ERROR posting pin: {e.code} {body[:300]}")
        return None


def main():
    today = date.today().isoformat()

    # Check if already posted today
    posted_asins, log_data = load_post_log()
    today_pins = [p for p in log_data.get("pins", [])
                  if p.get("timestamp", "").startswith(today) and p.get("source") == "dgc_pinterest_daily.py"]
    if today_pins:
        print(f"Already posted {len(today_pins)} pins today ({today}). Skipping.")
        return 0

    # Parse manifest
    products = parse_dgc_manifest()
    if products is None:
        return 3
    if not products:
        print("ERROR: No products found in DGC manifest")
        return 3

    print(f"DGC Manifest: {len(products)} products, {len(posted_asins)} already posted")

    # Find unposted products
    unposted = [p for p in products if p["asin"] not in posted_asins]
    print(f"Unposted products: {len(unposted)}")

    if not unposted:
        print("All manifest products have been posted. Need more products added to manifest.")
        return 1

    # Ensure valid token
    if not ensure_token():
        return 2

    # Post up to 3 pins
    to_post = unposted[:3]
    posted_count = 0
    for product in to_post:
        title = product["title"][:100]
        desc = product["notes"][:500] if product["notes"] else f"Check out this {product['title']} on Amazon!"
        affiliate_url = f"https://www.amazon.com/dp/{product['asin']}?tag=dadsgadgetc05-20"
        board_id = product["board_id"]

        pin_id = post_pin(
            asin=product["asin"],
            title=title,
            description=desc,
            board_id=board_id,
            affiliate_url=affiliate_url,
            image_path=product["image_path"],
        )

        if pin_id:
            # Log it
            log_data.setdefault("pins", []).append({
                "asin": product["asin"],
                "pin_id": pin_id,
                "board": product["board_name"],
                "board_id": board_id,
                "title": title,
                "timestamp": f"{today}T{__import__('datetime').datetime.now().strftime('%H:%M:%S')}",
                "source": "dgc_pinterest_daily.py",
                "status": "OK",
            })
            posted_count += 1
        else:
            print(f"❌ Failed to post {product['asin']}")

    save_post_log(log_data)
    print(f"\nPosted {posted_count} new pins today.")
    return 0 if posted_count > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
