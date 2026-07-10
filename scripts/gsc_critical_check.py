#!/usr/bin/env python3
"""GSC critical-issue daily check for n8n.

Emits a single-line JSON object on stdout:
    {"alerts": ["...", "..."]}

Empty `alerts` array = clean day, n8n IF node sends no message.

Checks:
  - Index coverage drop: total_indexed dropped >5% vs prior day stored state
  - Search performance crash: today's clicks dropped >70% vs 7-day prior avg
    (uses 3-day-lagged GSC data so "today" = today_lag)

Manual-action detection is NOT included — GSC public API does not expose it.
That check has to live in the GSC UI for now.

State file: ~/.openclaw/state/gsc_prev.json
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google_auth import get_brand75_credentials, get_personal_credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

STATE = Path.home() / ".openclaw" / "state" / "gsc_prev.json"


def build_service():
    try:
        creds = get_brand75_credentials()
        svc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        svc.sites().list().execute()
        return svc
    except Exception:
        pass
    creds = get_personal_credentials()
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def index_total(svc, site):
    r = svc.sitemaps().list(siteUrl=site).execute()
    total_idx = 0
    for sm in r.get("sitemap", []):
        for c in sm.get("contents", []):
            total_idx += int(c.get("indexed", 0))
    return total_idx


def perf_clicks(svc, site, start, end):
    body = {"startDate": start, "endDate": end, "dimensions": []}
    try:
        r = svc.searchanalytics().query(siteUrl=site, body=body).execute()
    except HttpError:
        return None
    rows = r.get("rows", [])
    if not rows:
        return 0
    return int(rows[0].get("clicks", 0))


def main():
    alerts = []
    site = "sc-domain:brand75.com"
    svc = build_service()

    # Load state
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}
    else:
        state = {}

    # Index coverage
    try:
        idx_now = index_total(svc, site)
        idx_prev = state.get("indexed_prev")
        if idx_prev and idx_prev > 0:
            drop_pct = (idx_prev - idx_now) / idx_prev * 100
            if drop_pct > 5:
                alerts.append(
                    f"Index coverage dropped {drop_pct:.1f}% "
                    f"(was {idx_prev}, now {idx_now})"
                )
        state["indexed_prev"] = idx_now
    except Exception as e:
        alerts.append(f"GSC index check failed: {e}")

    # Performance: today_lag vs 7-day prior avg
    try:
        today_lag = datetime.now(timezone.utc).date() - timedelta(days=3)
        prior_start = today_lag - timedelta(days=7)
        prior_end = today_lag - timedelta(days=1)

        clicks_today = perf_clicks(svc, site, today_lag.isoformat(), today_lag.isoformat())
        clicks_prior = perf_clicks(svc, site, prior_start.isoformat(), prior_end.isoformat())
        if clicks_prior is not None and clicks_today is not None:
            avg_prior = clicks_prior / 7
            if avg_prior >= 5 and clicks_today < avg_prior * 0.3:
                pct = (1 - clicks_today / avg_prior) * 100
                alerts.append(
                    f"Search clicks crashed {pct:.0f}% "
                    f"({clicks_today} vs 7-day avg {avg_prior:.1f})"
                )
    except Exception as e:
        alerts.append(f"GSC performance check failed: {e}")

    STATE.write_text(json.dumps(state))
    print(json.dumps({"alerts": alerts}))


if __name__ == "__main__":
    main()
