#!/usr/bin/env python3
"""Weekly Cloudflare health report — multi-zone.

For every zone in ~/.openclaw/config/cf_zones.json:
  - 7-day traffic (requests, bandwidth, cache hit rate, threats)
  - Top firewall rule triggers
  - DNS records + drift vs baseline
  - SSL cert expiry for each configured host

Sends one combined Telegram message. Fires a second alert if any
attention items present. Writes last-run state for the watchdog.
"""

from __future__ import annotations

import ssl
import socket
import sys
from datetime import datetime, timedelta, timezone

import requests

import cf_lib as L

NAME = "cloudflare_health"


def fmt_bytes(n: int) -> str:
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_int(n: int) -> str:
    return f"{n:,}"


def get_analytics(token: str, zone_id: str) -> dict:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=7)
    q = """
    query($z:String!,$s:Date!,$e:Date!){
      viewer{zones(filter:{zoneTag:$z}){
        httpRequests1dGroups(limit:14,filter:{date_geq:$s,date_lt:$e}){
          sum{requests cachedRequests bytes cachedBytes threats}
        }
      }}}"""
    r = L.cf_graphql(token, q, {"z": zone_id, "s": start.isoformat(), "e": end.isoformat()})
    if r.get("errors"):
        raise RuntimeError(r["errors"][0].get("message", "graphql error"))
    zones = r["data"]["viewer"]["zones"]
    groups = zones[0]["httpRequests1dGroups"] if zones else []
    t = {"requests": 0, "cachedRequests": 0, "bytes": 0, "cachedBytes": 0, "threats": 0}
    for g in groups:
        for k in t:
            t[k] += g["sum"].get(k, 0)
    return t


def get_dns(token: str, zone_id: str) -> list[dict]:
    out, page = [], 1
    while True:
        d = L.cf_get(token, f"/zones/{zone_id}/dns_records", params={"per_page": 100, "page": page})
        out.extend(d["result"])
        info = d.get("result_info", {})
        if page >= info.get("total_pages", 1):
            break
        page += 1
    return [{"type": r["type"], "name": r["name"], "content": r["content"]} for r in out
            if r.get("type") in ("A", "AAAA", "CNAME", "MX", "TXT", "NS")]


def dns_drift(zone_name: str, live: list[dict], baseline: dict) -> tuple[list[str], list[str]]:
    base = baseline.get(zone_name, [])
    sig = lambda r: (r["type"], r["name"], r["content"])
    base_sigs = {sig(r) for r in base}
    live_sigs = {sig(r) for r in live}
    added = [f"{t} {n} -> {c[:50]}" for (t, n, c) in (live_sigs - base_sigs)]
    removed = [f"{t} {n} -> {c[:50]}" for (t, n, c) in (base_sigs - live_sigs)]
    return added, removed


def get_cert(host: str) -> dict:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=10) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            cert = ssock.getpeercert()
    not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    issuer = dict(x[0] for x in cert.get("issuer", []))
    return {
        "expires": not_after,
        "days_left": (not_after - datetime.now(timezone.utc)).days,
        "issuer": issuer.get("organizationName") or issuer.get("commonName") or "unknown",
    }


def report_zone(token: str, zone: dict, baseline: dict) -> tuple[list[str], list[str]]:
    name = zone["name"]
    alerts: list[str] = []
    lines = [f"*{name}*"]

    # Traffic
    try:
        a = get_analytics(token, zone["id"])
        total = a["requests"]
        cache_pct = (a["cachedRequests"] / total * 100) if total else 0
        lines.append(f"  Req {fmt_int(total)} · {fmt_bytes(a['bytes'])} · cache {cache_pct:.1f}% · threats {fmt_int(a['threats'])}")
        if total > 0 and cache_pct < zone.get("low_cache_threshold_pct", 25):
            alerts.append(f"{name}: low cache hit rate ({cache_pct:.1f}%)")
        if a["threats"] > zone.get("threat_threshold", 5000):
            alerts.append(f"{name}: high threat count ({fmt_int(a['threats'])})")
    except Exception as e:
        lines.append(f"  ⚠️ traffic: {str(e)[:120]}")
        alerts.append(f"{name}: analytics query failed")

    # DNS drift
    try:
        live = get_dns(token, zone["id"])
        added, removed = dns_drift(name, live, baseline)
        lines.append(f"  DNS {len(live)} records")
        if added:
            lines.append(f"  ➕ added: {len(added)}")
            for a in added[:5]:
                lines.append(f"    {a}")
            alerts.append(f"{name}: {len(added)} unexpected DNS record(s) added")
        if removed:
            lines.append(f"  ➖ removed: {len(removed)}")
            for r in removed[:5]:
                lines.append(f"    {r}")
            alerts.append(f"{name}: {len(removed)} expected DNS record(s) removed")
    except Exception as e:
        lines.append(f"  ⚠️ DNS: {str(e)[:120]}")
        alerts.append(f"{name}: DNS fetch failed")

    # SSL per host
    for host in zone.get("ssl_hosts", []):
        try:
            c = get_cert(host)
            lines.append(f"  SSL {host}: {c['expires'].strftime('%Y-%m-%d')} ({c['days_left']}d, {c['issuer']})")
            if c["days_left"] < 30:
                alerts.append(f"{host}: SSL cert expires in {c['days_left']}d")
        except Exception as e:
            lines.append(f"  ⚠️ SSL {host}: {str(e)[:80]}")
            alerts.append(f"{host}: SSL probe failed")

    return lines, alerts


def main() -> int:
    token = L.load_env("CLOUDFLARE_API_TOKEN")
    zones = L.load_zones()
    baseline = L.load_dns_baseline()

    header = [f"*Cloudflare Health — {len(zones)} zone(s)*",
              f"_7d · {datetime.now().strftime('%Y-%m-%d')}_", ""]
    all_lines, all_alerts = [], []
    for z in zones:
        lines, alerts = report_zone(token, z, baseline)
        all_lines.extend(lines + [""])
        all_alerts.extend(alerts)

    if all_alerts:
        all_lines.append("*⚠️ Attention*")
        for a in all_alerts:
            all_lines.append(f"• {a}")
    else:
        all_lines.append("✅ All zones healthy")

    msg = "\n".join(header + all_lines)
    print(msg)

    if "--no-send" not in sys.argv:
        L.notify(msg)
        if all_alerts:
            L.notify(f"🚨 *CF Health degraded* — {len(all_alerts)} issue(s) across {len(zones)} zones")
        L.write_last_run(NAME)
    return 1 if all_alerts else 0


if __name__ == "__main__":
    sys.exit(main())
