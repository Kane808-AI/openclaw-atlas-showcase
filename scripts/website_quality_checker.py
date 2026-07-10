#!/usr/bin/env python3
"""Website Quality Checker for Google Places Scraper

Checks websites for:
- SSL (HTTPS vs HTTP)
- Mobile viewport meta tag
- Page load time
- Google PageSpeed Insights score

Flags contacts with 'bad-website' tag if score < 50 or missing SSL/mobile viewport.
"""

import os
import re
import time
import urllib.request
import urllib.error
from urllib.parse import urlparse
from typing import Dict, Optional, Tuple
# Load API key from env or .env file
def load_env_key():
    """Load PAGESPEED_API_KEY from ~/.openclaw/.env - checks multiple key names"""
    env_path = os.path.expanduser("~/.openclaw/.env")
    key_names = ['GOOGLE_PAGESPEED_API_KEY=', 'GOOGLE_PLACES_API_KEY=', 'GOOGLE_API_KEY=']
    
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                for key_prefix in key_names:
                    if line.startswith(key_prefix):
                        key = line.split('=', 1)[1].strip()
                        # Remove quotes if present
                        if key.startswith('"') and key.endswith('"'):
                            key = key[1:-1]
                        if key.startswith("'") and key.endswith("'"):
                            key = key[1:-1]
                        return key
    
    # Fallback to environment variables
    return os.environ.get('GOOGLE_PAGESPEED_API_KEY') or os.environ.get('GOOGLE_PLACES_API_KEY') or os.environ.get('GOOGLE_API_KEY')

PAGESPEED_API_KEY = load_env_key()

def check_ssl(url: str) -> Tuple[bool, str]:
    """Check if URL uses HTTPS."""
    parsed = urlparse(url)
    return parsed.scheme == "https", parsed.scheme

def fetch_page_content(url: str, timeout: int = 10) -> Tuple[Optional[str], Optional[int], float]:
    """Fetch page and return (content, status_code, load_time_seconds)."""
    start_time = time.time()
    try:
        # Follow redirects
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8", errors="ignore")
            load_time = time.time() - start_time
            return content, response.getcode(), load_time
    except urllib.error.HTTPError as e:
        return None, e.code, time.time() - start_time
    except Exception as e:
        return None, None, time.time() - start_time

def check_mobile_viewport(html: str) -> Tuple[bool, Optional[str]]:
    """Check for mobile viewport meta tag in HTML."""
    # Look for viewport meta tag
    viewport_pattern = r'<meta[^>]+name=["\']viewport["\'][^>]*>'
    viewport_match = re.search(viewport_pattern, html, re.IGNORECASE)
    
    if viewport_match:
        content = viewport_match.group(0)
        # Check if it has width=device-width
        has_device_width = "width=device-width" in content.lower()
        return has_device_width, content
    
    return False, None

def get_pagespeed_score(url: str, strategy: str = "mobile") -> Tuple[Optional[int], Optional[Dict]]:
    """Get PageSpeed Insights score. Returns (score, full_metrics)."""
    if not PAGESPEED_API_KEY:
        return None, {"error": "No API key configured"}
    
    try:
        import urllib.request
        import json
        
        api_url = (
            f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}"
            f"&strategy={strategy}&key={PAGESPEED_API_KEY}"
        )
        
        req = urllib.request.Request(api_url)
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            # Extract score
            lighthouse = data.get("lighthouseResult", {})
            categories = lighthouse.get("categories", {})
            performance = categories.get("performance", {})
            score = performance.get("score")
            
            if score is not None:
                score = int(score * 100)  # Convert 0-1 to 0-100
            
            metrics = {
                "score": score,
                "largest_contentful_paint": lighthouse.get("audits", {}).get("largest-contentful-paint", {}).get("displayValue", "N/A"),
                "first_input_delay": lighthouse.get("audits", {}).get("max-potential-fid", {}).get("displayValue", "N/A"),
                "cumulative_layout_shift": lighthouse.get("audits", {}).get("cumulative-layout-shift", {}).get("displayValue", "N/A"),
            }
            
            return score, metrics
            
    except Exception as e:
        return None, {"error": str(e)}

def check_website_quality(url: str) -> Dict:
    """Run full quality check on a website.
    
    Returns dict with:
    - has_website: bool
    - has_ssl: bool
    - has_mobile_viewport: bool
    - load_time_seconds: float
    - pagespeed_score: int or None
    - pagespeed_metrics: dict
    - quality_score: int (0-100, composite)
    - flags: list of issue strings
    - is_bad_website: bool (score < 50 or missing SSL/viewport)
    """
    result = {
        "has_website": bool(url and url.strip() and url != "none"),
        "url": url,
        "has_ssl": False,
        "has_mobile_viewport": False,
        "load_time_seconds": None,
        "pagespeed_score": None,
        "pagespeed_metrics": {},
        "quality_score": 0,
        "flags": [],
        "is_bad_website": True,  # Default to bad until proven otherwise
        "error": None
    }
    
    if not result["has_website"]:
        result["flags"].append("no_website")
        return result
    
    # Ensure URL has scheme
    if not url.startswith(("http://", "https://")):
        url = "https://" + url  # Try HTTPS first
    
    # Check SSL
    has_ssl, scheme = check_ssl(url)
    result["has_ssl"] = has_ssl
    
    if not has_ssl:
        result["flags"].append("no_ssl")
    
    # Fetch page
    content, status_code, load_time = fetch_page_content(url)
    result["load_time_seconds"] = round(load_time, 2)
    
    if content is None:
        result["error"] = f"Failed to fetch (status: {status_code})"
        result["flags"].append("unreachable")
        return result
    
    # Check mobile viewport
    has_viewport, viewport_content = check_mobile_viewport(content)
    result["has_mobile_viewport"] = has_viewport
    
    if not has_viewport:
        result["flags"].append("no_mobile_viewport")
    
    # Get PageSpeed score
    pagespeed_score, metrics = get_pagespeed_score(url)
    result["pagespeed_score"] = pagespeed_score
    result["pagespeed_metrics"] = metrics
    
    if pagespeed_score is not None and pagespeed_score < 50:
        result["flags"].append(f"low_pagespeed_score ({pagespeed_score})")
    
    # Calculate composite quality score
    score = 0
    checks = 0
    
    if result["has_ssl"]:
        score += 25
    checks += 1
    
    if result["has_mobile_viewport"]:
        score += 25
    checks += 1
    
    if pagespeed_score is not None:
        # Normalize PageSpeed to 0-50 range
        score += min(pagespeed_score / 2, 50)
        checks += 1
    else:
        # Couldn't get PageSpeed, assume middle score
        score += 25
    
    result["quality_score"] = int(score)
    
    # Determine if it's a "bad website"
    # Bad if: score < 50 OR missing SSL OR missing mobile viewport
    result["is_bad_website"] = (
        result["quality_score"] < 50 or
        not result["has_ssl"] or
        not result["has_mobile_viewport"]
    )
    
    return result

def format_quality_report(result: Dict) -> str:
    """Format quality check results for display."""
    lines = [
        f"URL: {result['url']}",
        f"SSL: {'✓' if result['has_ssl'] else '✗'}",
        f"Mobile Viewport: {'✓' if result['has_mobile_viewport'] else '✗'}",
        f"Load Time: {result['load_time_seconds']:.2f}s" if result['load_time_seconds'] else "Load Time: N/A",
    ]
    
    if result['pagespeed_score'] is not None:
        lines.append(f"PageSpeed Score: {result['pagespeed_score']}/100")
    else:
        lines.append("PageSpeed Score: N/A (check failed)")
    
    lines.append(f"Quality Score: {result['quality_score']}/100")
    lines.append(f"Flags: {', '.join(result['flags']) if result['flags'] else 'None'}")
    lines.append(f"Verdict: {'BAD WEBSITE' if result['is_bad_website'] else 'GOOD WEBSITE'}")
    