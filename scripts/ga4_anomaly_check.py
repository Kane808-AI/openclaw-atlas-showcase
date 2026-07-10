#!/usr/bin/env python3
"""GA4 traffic anomaly check for n8n.

Compares today's sessions for property 488531418 (Brand75) against the
prior 7-day average. If today's sessions are 30%+ below avg, emit an
alert object on stdout.

Output (single JSON line):
    {"alert": true,  "today": N, "avg": F, "drop_pct": F}
    {"alert": false, "today": N, "avg": F}

n8n IF node: only send Telegram when alert == true.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest

# Reuse ga4_tool's creds helper to stay consistent on scopes/SA file
import importlib.util
spec = importlib.util.spec_from_file_location("ga4_tool", Path(__file__).parent / "ga4_tool.py")
ga4_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ga4_tool)

PROPERTY = "488531418"
THRESHOLD = 0.30  # 30% below average


def sessions_for_range(client, start, end):
    req = RunReportRequest(
        property=f"properties/{PROPERTY}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        metrics=[Metric(name="sessions")],
    )
    resp = client.run_report(req)
    if not resp.rows:
        return 0
    return int(resp.rows[0].metric_values[0].value)


def main():
    creds = ga4_tool.get_ga4_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    today = sessions_for_range(client, "today", "today")
    prior_total = sessions_for_range(client, "7daysAgo", "1daysAgo")
    avg = prior_total / 7

    if avg >= 5 and today < avg * (1 - THRESHOLD):
        drop_pct = (1 - today / avg) * 100 if avg else 0
        print(json.dumps({
            "alert": True,
            "today": today,
            "avg": round(avg, 1),
            "drop_pct": round(drop_pct, 1),
        }))
    else:
        print(json.dumps({"alert": False, "today": today, "avg": round(avg, 1)}))


if __name__ == "__main__":
    main()
