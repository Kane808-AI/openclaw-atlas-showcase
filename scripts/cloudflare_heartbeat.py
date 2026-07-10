#!/usr/bin/env python3
"""Daily Cloudflare heartbeat — multi-zone liveness check.

For each zone: verifies API token works against it, zone status active,
SSL cert >14d, analytics queryable. Silent on success. One aggregated
Telegram alert listing all failing zones if anything breaks.

Writes last-run timestamp for the watchdog.
"""

from __future__ import annotations

import ssl
import socket
import sys
from datetime import datetime, timedelta, timezone

import requests

import cf_lib as L

NAME = "cloudflare_heartbeat"


def check_zone(token: str, zone: dict) -> list[str]:
    failures: list[str] = []
    name = zone["name"]

    # Zone status
    try:
        r = requests.get(f"{L.API}/zones/{zone['id']}",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        body = r.json()
        if not body.get("success"):
            failures.append(f"{name}: zone fetch failed ({body.get('errors')})")
        else:
            status = body["result"].get("status")
            if status != "active":
                failures.append(f"{name}: zone status {status}")
    except Exception as e:
        failures.append(f"{name}: zone exception {e}")

    # Analytics query (regression check)
    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=1)
        r = requests.post(
            f"{L.API}/graphql",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "query": "query($z:String!,$s:Date!,$e:Date!){viewer{zones(filter:{zoneTag:$z}){httpRequests1dGroups(limit:2,filter:{date_geq:$s,date_lt:$e}){sum{requests}}}}}",
                "variables": {"z": zone["id"], "s": start.isoformat(), "e": end.isoformat()},
            },
            timeout=15,
        )
        body = r.json()
        errs = body.get("errors") or []
        if errs:
            failures.append(f"{name}: analytics {errs[0].get('message', '')[:120]}")
    except Exception as e:
        failures.append(f"{name}: analytics exception {e}")

    # SSL per configured host
    for host in zone.get("ssl_hosts", []):
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
            not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days = (not_after - datetime.now(timezone.utc)).days
            if days < 14:
                failures.append(f"{host}: SSL expires in {days}d")
        except Exception as e:
            failures.append(f"{host}: SSL probe {e}")

    return failures


def main() -> int:
    token = L.load_env("CLOUDFLARE_API_TOKEN")

    # Verify token first — if dead, every zone fails for the same reason
    try:
        r = requests.get(f"{L.API}/user/tokens/verify",
                         headers={"Authorization": f"Bearer {token}"}, timeout=15)
        body = r.json()
        if not body.get("success") or body.get("result", {}).get("status") != "active":
            L.notify(f"🚨 *CF Heartbeat FAIL* — token verify failed: {body}")
            return 1
    except Exception as e:
        L.notify(f"🚨 *CF Heartbeat FAIL* — token verify exception: {e}")
        return 1

    all_failures: list[str] = []
    zones = L.load_zones()
    for z in zones:
        all_failures.extend(check_zone(token, z))

    L.write_last_run(NAME)

    if all_failures:
        msg = f"🚨 *CF Heartbeat FAIL* ({len(all_failures)} issue/s, {len(zones)} zones)\n" + "\n".join(f"• {f}" for f in all_failures[:20])
        L.notify(msg[:3900])
        print("FAIL:", *all_failures, sep="\n  ")
        return 1
    print(f"OK — {len(zones)} zones healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
