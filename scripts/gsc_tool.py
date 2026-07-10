#!/usr/bin/env python3
"""Google Search Console tool for Atlas agents.

Usage:
    gsc_tool.py list-sites
    gsc_tool.py list-sitemaps
    gsc_tool.py submit-sitemap URL
    gsc_tool.py delete-sitemap URL
    gsc_tool.py index-status
    gsc_tool.py performance [--days N]

Auth: Brand75 service account (DWD) impersonating support@brand75.com.
      Falls back to personal OAuth2 token if service account lacks GSC access.
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_auth import get_brand75_credentials, get_personal_credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def build_service():
    """Build Search Console service, trying service account then personal OAuth2."""
    try:
        creds = get_brand75_credentials()
        service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        service.sites().list().execute()
        return service, "service-account (support@brand75.com)"
    except HttpError as e:
        if e.resp.status not in (401, 403):
            raise
    except Exception:
        pass

    personal_token = Path.home() / ".openclaw" / "scripts" / "personal-token.json"
    if not personal_token.exists():
        sys.exit(
            "Service account lacks GSC access and no personal-token.json found.\n"
            "Grant the service account Search Console access, or run reauth_personal.py."
        )

    creds = get_personal_credentials()
    service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    return service, "personal-oauth (you@example.com)"


def resolve_site_url(service):
    """Find the correct property URL for brand75.com, preferring domain property."""
    try:
        result = service.sites().list().execute()
        entries = result.get("siteEntry", [])
        # Prefer sc-domain (covers www + non-www + all subdomains)
        for e in entries:
            if e.get("siteUrl") == "sc-domain:brand75.com":
                return "sc-domain:brand75.com"
        # Fall back to any brand75.com property
        for e in entries:
            if "brand75.com" in e.get("siteUrl", ""):
                return e["siteUrl"]
    except HttpError:
        pass
    return "sc-domain:brand75.com"


def cmd_list_sites(service):
    result = service.sites().list().execute()
    entries = result.get("siteEntry", [])
    if not entries:
        print("No sites found.")
        return
    print(f"{'Site URL':<55}  Permission")
    print("-" * 75)
    for e in entries:
        print(f"{e['siteUrl']:<55}  {e.get('permissionLevel', 'unknown')}")


def cmd_list_sitemaps(service, site_url):
    result = service.sitemaps().list(siteUrl=site_url).execute()
    sitemaps = result.get("sitemap", [])
    if not sitemaps:
        print(f"No sitemaps registered for {site_url}")
        return

    print(f"Sitemaps for {site_url}:\n")
    print(f"  {'URL':<60}  {'Type':<12}  {'Submitted':<12}  {'URLs':>5}  Status")
    print("  " + "-" * 105)
    for sm in sitemaps:
        path = sm.get("path", "")
        sm_type = sm.get("type", "")
        submitted = sm.get("lastSubmitted", "")[:10] if sm.get("lastSubmitted") else "—"
        contents = sm.get("contents", [])
        url_count = sum(int(c.get("submitted", 0)) for c in contents) if contents else "—"
        errors = sm.get("errors", "0")
        warnings = sm.get("warnings", "0")
        status = "ok"
        if errors != "0":
            status = f"errors:{errors}"
        elif warnings != "0":
            status = f"warnings:{warnings}"
        print(f"  {path:<60}  {sm_type:<12}  {submitted:<12}  {str(url_count):>5}  {status}")


def cmd_submit_sitemap(service, site_url, sitemap_url):
    try:
        service.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
        print(f"Submitted: {sitemap_url}")
        print(f"Property:  {site_url}")
    except HttpError as e:
        sys.exit(f"Submit failed: {e}")


def cmd_delete_sitemap(service, site_url, sitemap_url):
    try:
        service.sitemaps().delete(siteUrl=site_url, feedpath=sitemap_url).execute()
        print(f"Deleted: {sitemap_url}")
    except HttpError as e:
        sys.exit(f"Delete failed: {e}")


def cmd_index_status(service, site_url):
    """Report indexed vs submitted counts from sitemap data."""
    result = service.sitemaps().list(siteUrl=site_url).execute()
    sitemaps = result.get("sitemap", [])
    if not sitemaps:
        print(f"No sitemaps registered for {site_url}. Cannot report index status.")
        return

    total_submitted = 0
    total_indexed = 0
    print(f"Index status for {site_url} (via sitemap data):\n")

    for sm in sitemaps:
        path = sm.get("path", "")
        contents = sm.get("contents", [])
        for c in contents:
            sub = int(c.get("submitted", 0))
            idx = int(c.get("indexed", 0))
            total_submitted += sub
            total_indexed += idx
            pct = f"{idx/sub*100:.0f}%" if sub else "—"
            print(f"  {path}")
            print(f"    Submitted: {sub}   Indexed: {idx}   Coverage: {pct}")

    print(f"\n  Total submitted:  {total_submitted}")
    print(f"  Total indexed:    {total_indexed}")
    if total_submitted:
        print(f"  Overall coverage: {total_indexed/total_submitted*100:.0f}%")


def cmd_performance(service, site_url, days):
    # GSC data has a ~3-day processing lag
    end_date = datetime.now(timezone.utc).date() - timedelta(days=3)
    start_date = end_date - timedelta(days=days - 1)

    body = {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "dimensions": ["query"],
        "rowLimit": 25,
    }

    try:
        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except HttpError as e:
        sys.exit(f"Performance query failed: {e}")

    rows = result.get("rows", [])
    print(f"Search performance: {site_url}")
    print(f"Period: {start_date} to {end_date} ({days} days, top 25 queries)\n")

    if not rows:
        print("No data for this period.")
        return

    print(f"  {'Query':<50}  {'Clicks':>6}  {'Impr':>7}  {'CTR':>6}  {'Pos':>5}")
    print("  " + "-" * 85)
    total_clicks = 0
    total_impr = 0
    for row in rows:
        query = row["keys"][0][:49]
        clicks = int(row.get("clicks", 0))
        impr = int(row.get("impressions", 0))
        ctr = f"{row.get('ctr', 0)*100:.1f}%"
        pos = f"{row.get('position', 0):.1f}"
        total_clicks += clicks
        total_impr += impr
        print(f"  {query:<50}  {clicks:>6}  {impr:>7}  {ctr:>6}  {pos:>5}")

    print(f"\n  Totals: {total_clicks:,} clicks,  {total_impr:,} impressions")


def main():
    parser = argparse.ArgumentParser(description="Google Search Console tool for brand75.com")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-sites", help="List all GSC properties this account can access")
    sub.add_parser("list-sitemaps", help="List sitemaps registered for brand75.com")

    p = sub.add_parser("submit-sitemap", help="Submit a sitemap URL")
    p.add_argument("url", help="Full sitemap URL (e.g. https://brand75.com/sitemap.xml)")

    p = sub.add_parser("delete-sitemap", help="Delete a sitemap URL")
    p.add_argument("url", help="Full sitemap URL to remove")

    sub.add_parser("index-status", help="Show indexed vs submitted URL counts from sitemaps")

    p = sub.add_parser("performance", help="Pull search performance data (queries, clicks, etc.)")
    p.add_argument("--days", type=int, default=28, help="Days to look back (default: 28)")

    args = parser.parse_args()

    service, auth_label = build_service()
    print(f"[auth: {auth_label}]\n")

    site_url = resolve_site_url(service)

    if args.command == "list-sites":
        cmd_list_sites(service)
    elif args.command == "list-sitemaps":
        cmd_list_sitemaps(service, site_url)
    elif args.command == "submit-sitemap":
        cmd_submit_sitemap(service, site_url, args.url)
    elif args.command == "delete-sitemap":
        cmd_delete_sitemap(service, site_url, args.url)
    elif args.command == "index-status":
        cmd_index_status(service, site_url)
    elif args.command == "performance":
        cmd_performance(service, site_url, args.days)


if __name__ == "__main__":
    main()
