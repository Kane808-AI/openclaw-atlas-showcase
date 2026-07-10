#!/usr/bin/env python3
"""Snapshot current DNS records for all monitored zones as the baseline.

Run this manually after any intentional DNS change. The health script
diffs live records against the baseline and alerts on drift.

Usage: cf_dns_snapshot.py [--zone <name>]
"""

from __future__ import annotations

import sys

import cf_lib as L


def fetch_records(token: str, zone_id: str) -> list[dict]:
    out, page = [], 1
    while True:
        d = L.cf_get(token, f"/zones/{zone_id}/dns_records", params={"per_page": 100, "page": page})
        out.extend(d["result"])
        info = d.get("result_info", {})
        if page >= info.get("total_pages", 1):
            break
        page += 1
    keep = [r for r in out if r.get("type") in ("A", "AAAA", "CNAME", "MX", "TXT", "NS")]
    return [{"type": r["type"], "name": r["name"], "content": r["content"]} for r in keep]


def main() -> int:
    only = None
    if "--zone" in sys.argv:
        only = sys.argv[sys.argv.index("--zone") + 1]
    token = L.load_env("CLOUDFLARE_API_TOKEN")
    baseline = L.load_dns_baseline()
    for z in L.load_zones():
        if only and z["name"] != only:
            continue
        records = fetch_records(token, z["id"])
        records_sorted = sorted(records, key=lambda x: (x["type"], x["name"], x["content"]))
        baseline[z["name"]] = records_sorted
        print(f"{z['name']}: {len(records_sorted)} records")
    L.save_dns_baseline(baseline)
    print(f"Baseline written: {L.DNS_BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
