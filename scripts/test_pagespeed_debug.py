#!/usr/bin/env python3
"""Debug PageSpeed API."""

import os
import sys
sys.path.insert(0, os.path.expanduser('~/.openclaw/scripts'))

from website_quality_checker import get_pagespeed_score, load_env_key

url = "https://www.aplusplumbing.com/"
print(f"Testing PageSpeed for: {url}")
print(f"API Key present: {bool(load_env_key())}")

score, metrics = get_pagespeed_score(url)
print(f"Score: {score}")
print(f"Metrics: {metrics}")
