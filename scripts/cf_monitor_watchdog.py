#!/usr/bin/env python3
"""Meta-monitor — alerts if the CF heartbeat or health scripts haven't run.

Checks the last-run timestamps written by cloudflare_heartbeat.py and
cloudflare_health.py. Fires a Telegram alert if either is stale.

Thresholds:
  - heartbeat: must run within last 26h (daily 8:35 + 1h buffer + 1h DST)
  - health:    must run within last 8 days (weekly Mon 8:30 + 1d buffer)
"""

from __future__ import annotations

import sys
import time

import cf_lib as L

CHECKS = [
    ("cloudflare_heartbeat", 26 * 3600, "daily"),
    ("cloudflare_health", 8 * 86400, "weekly"),
]


def main() -> int:
    now = int(time.time())
    fails: list[str] = []
    for name, max_age, cadence in CHECKS:
        ts = L.read_last_run(name)
        if ts is None:
            fails.append(f"{name} ({cadence}): never ran")
            continue
        age = now - ts
        if age > max_age:
            hrs = age / 3600
            fails.append(f"{name} ({cadence}): last ran {hrs:.1f}h ago (limit {max_age/3600:.0f}h)")
    if fails:
        msg = "🚨 *CF Monitor Watchdog* — script(s) not running:\n" + "\n".join(f"• {f}" for f in fails)
        L.notify(msg)
        print("FAIL:", *fails, sep="\n  ")
        return 1
    print(f"OK — all {len(CHECKS)} monitors running on schedule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
