#!/usr/bin/env python3
"""Test website quality checker on 10 plumber websites."""

import sys
import os
sys.path.insert(0, os.path.expanduser('~/.openclaw/scripts'))

from website_quality_checker import check_website_quality

# 10 plumber websites from previous scrapes
test_urls = [
    "https://www.aplusplumbing.com/",  # from 98512
    "https://springerplumbing.com/",
    "https://olympicplumbing.com/",
    "http://flowpointpros.com/",
    "https://trustedplumbingolympia.com/",
    "http://www.onthelevelplumber.com/",
    "https://www.americanplumbingwa.com/",
    "http://pureriseventures.com/",  # Lacey 24/7 Plumbing
    "http://johnsplumbingandpumps.com/",
    "https://www.rotorooter.com/olympiawa/",
]

def format_seconds(seconds):
    """Format seconds value."""
    if seconds is None:
        return "N/A"
    return f"{seconds:.2f}s"

def main():
    results = []
    
    print("Testing website quality checker on 10 plumber websites...\n")
    print("="*100)
    
    for i, url in enumerate(test_urls, 1):
        print(f"\n{i}/10: Checking {url}")
        result = check_website_quality(url)
        results.append({
            "url": url,
            "has_ssl": "✓" if result["has_ssl"] else "✗",
            "has_viewport": "✓" if result["has_mobile_viewport"] else "✗",
            "load_time": format_seconds(result["load_time_seconds"]),
            "pagespeed": result["pagespeed_score"] if result["pagespeed_score"] else "N/A",
            "quality_score": result["quality_score"],
            "verdict": "BAD-WEBSITE" if result["is_bad_website"] else "GOOD",
            "flags": ", ".join(result["flags"]) if result["flags"] else "None"
        })
    
    # Print table
    print("\n\n" + "="*100)
    print("RESULTS TABLE")
    print("="*100)
    
    # Header
    print(f"{'URL':<45} {'SSL':<4} {'Mobile':<7} {'Load':<8} {'PS':<5} {'Q-Score':<8} {'Verdict':<12}")
    print("-"*100)
    
    # Rows
    bad_count = 0
    for r in results:
        print(f"{r['url'][:43]:<45} {r['has_ssl']:<4} {r['has_viewport']:<7} {r['load_time']:<8} {str(r['pagespeed']):<5} {r['quality_score']:<8} {r['verdict']:<12}")
        if r["verdict"] == "BAD-WEBSITE":
            bad_count += 1
    
    # Flags detail
    print("\n" + "="*100)
    print("DETAILED FLAGS")
    print("="*100)
    for r in results:
        if r["flags"] != "None":
            print(f"{r['url'][:50]:<52} → {r['flags']}")
    
    # Summary
    print("\n" + "="*100)
    print("SUMMARY")
    print("="*100)
    print(f"Total websites tested: {len(results)}")
    print(f"BAD-WEBSITE flagged: {bad_count} ({bad_count/len(results)*100:.0f}%)")
    print(f"GOOD websites: {len(results) - bad_count} ({(len(results)-bad_count)/len(results)*100:.0f}%)")
    
    # SSL breakdown
    ssl_count = sum(1 for r in results if r["has_ssl"] == "✓")
    viewport_count = sum(1 for r in results if r["has_viewport"] == "✓")
    pagespeed_count = sum(1 for r in results if r["pagespeed"] != "N/A" and r["pagespeed"] != None)
    
    print(f"\nBreakdown:")
    print(f"  - Have SSL (https): {ssl_count}/{len(results)}")
    print(f"  - Have mobile viewport: {viewport_count}/{len(results)}")
    print(f"  - Got PageSpeed score: {pagespeed_count}/{len(results)}")

if __name__ == "__main__":
    main()
