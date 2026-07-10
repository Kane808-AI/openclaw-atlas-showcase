#!/usr/bin/env python3
"""Test PageSpeed API with updated key loading."""

import sys
sys.path.insert(0, "/Users/chriskaneshiro/.openclaw/scripts")

from website_quality_checker import get_pagespeed_score, load_env_key, PAGESPEED_API_KEY

url = "https://www.aplusplumbing.com/"

print(f"Testing PageSpeed for: {url}")
print(f"API Key loaded: {bool(PAGESPEED_API_KEY)} (first 10 chars: {PAGESPEED_API_KEY[:10]}...)" if PAGESPEED_API_KEY else "NO API KEY FOUND")

score, metrics = get_pagespeed_score(url)

if score is not None:
    print(f"\n✓ SUCCESS! PageSpeed Score: {score}/100")
    print(f"\nMetrics:")
    for key, value in metrics.items():
        print(f"  - {key}: {value}")
else:
    print(f"\n✗ FAILED to get score")
    print(f"Error: {metrics.get('error', 'Unknown error')}")
