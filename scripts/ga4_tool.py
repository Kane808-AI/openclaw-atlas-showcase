#!/usr/bin/env python3
"""GA4 reporting tool for Brand75.

GA4 note: Admin and Data APIs use the service account directly (no DWD).
The service account must be added as a Viewer on the GA4 property in the
Google Analytics UI (Admin > Account Access Management).

Commands:
    list-properties   List all GA4 properties accessible to this service account
    traffic           Sessions, users, pageviews, avg session duration
    pages             Top 10 landing pages by sessions
    sources           Traffic source breakdown
    events            All events with counts (checks conversion tracking)
    realtime          Active users right now
"""

import argparse
import sys
from pathlib import Path

from google.oauth2 import service_account
from google.analytics.admin import AnalyticsAdminServiceClient
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
    RunRealtimeReportRequest,
    OrderBy,
)

# ── Auth ──────────────────────────────────────────────────────────────────────

SA_FILE = Path.home() / ".openclaw" / "credentials" / "google" / "brand75-service-account.json"

GA4_SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
]


def get_ga4_credentials() -> service_account.Credentials:
    """Load service account creds scoped for GA4 (no DWD — GA4 doesn't support it)."""
    return service_account.Credentials.from_service_account_file(
        str(SA_FILE),
        scopes=GA4_SCOPES,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_num(n: str | int) -> str:
    return f"{int(n):,}"


def fmt_duration(seconds: str | float) -> str:
    s = int(float(seconds))
    return f"{s // 60}m {s % 60}s"


def print_table(headers: list[str], rows: list[list[str]], col_width: int = 40) -> None:
    if not rows:
        return
    widths = [max(len(h), max((len(str(r[i])) for r in rows), default=0)) for i, h in enumerate(headers)]
    widths = [min(w, col_width) for w in widths]
    sep = "  ".join("-" * w for w in widths)
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print(sep)
    for row in rows:
        print("  ".join(str(v).ljust(w)[:w] for v, w in zip(row, widths)))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list_properties(args) -> None:
    creds = get_ga4_credentials()
    client = AnalyticsAdminServiceClient(credentials=creds)

    print("Fetching GA4 properties...\n")
    rows = []
    try:
        for account in client.list_accounts():
            account_id = account.name.split("/")[-1]
            for prop in client.list_properties(request={"filter": f"parent:accounts/{account_id}"}):
                prop_id = prop.name.split("/")[-1]
                measurement_id = ""
                try:
                    # NOTE: data stream is configured for https://www.brand75.com but
                    # the live site is https://brand75.com (no www). This may cause
                    # measurement gaps if GA4 doesn't receive hits from the bare domain.
                    for stream in client.list_data_streams(request={"parent": prop.name}):
                        if hasattr(stream, "web_stream_data") and stream.web_stream_data.measurement_id:
                            measurement_id = stream.web_stream_data.measurement_id
                            break
                except Exception:
                    pass
                rows.append([prop_id, prop.display_name, measurement_id])
    except Exception as e:
        print(f"Error: {e}")
        print("\nThe service account needs Viewer access in GA4 > Admin > Account Access Management.")
        sys.exit(1)

    if not rows:
        print("No properties found. Service account may not have GA4 access yet.")
        return

    print_table(["Property ID", "Display Name", "Measurement ID"], rows)


def cmd_traffic(args) -> None:
    creds = get_ga4_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{args.property}",
        date_ranges=[DateRange(start_date=f"{args.days}daysAgo", end_date="today")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
            Metric(name="screenPageViews"),
            Metric(name="averageSessionDuration"),
        ],
    )

    try:
        response = client.run_report(request)
    except Exception as e:
        print(f"Error fetching traffic: {e}")
        sys.exit(1)

    if not response.rows:
        print("No data returned.")
        return

    row = response.rows[0].metric_values
    sessions, users, new_users, pageviews, avg_dur = [v.value for v in row]

    print(f"\nTraffic Summary — Last {args.days} days (property {args.property})")
    print("─" * 45)
    print(f"  Sessions:             {fmt_num(sessions)}")
    print(f"  Total users:          {fmt_num(users)}")
    print(f"  New users:            {fmt_num(new_users)}")
    print(f"  Pageviews:            {fmt_num(pageviews)}")
    print(f"  Avg session duration: {fmt_duration(avg_dur)}")


def cmd_pages(args) -> None:
    creds = get_ga4_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{args.property}",
        date_ranges=[DateRange(start_date=f"{args.days}daysAgo", end_date="today")],
        dimensions=[
            Dimension(name="landingPagePlusQueryString"),
            Dimension(name="pageTitle"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="screenPageViews"),
            Metric(name="bounceRate"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=10,
    )

    try:
        response = client.run_report(request)
    except Exception as e:
        print(f"Error fetching pages: {e}")
        sys.exit(1)

    if not response.rows:
        print("No data returned.")
        return

    print(f"\nTop 10 Landing Pages — Last {args.days} days (property {args.property})")
    rows = []
    for r in response.rows:
        path = r.dimension_values[0].value[:45]
        title = r.dimension_values[1].value[:30]
        sessions = fmt_num(r.metric_values[0].value)
        views = fmt_num(r.metric_values[1].value)
        bounce = f"{float(r.metric_values[2].value) * 100:.1f}%"
        rows.append([path, title, sessions, views, bounce])

    print_table(["Landing Page", "Title", "Sessions", "Views", "Bounce%"], rows, col_width=46)


def cmd_sources(args) -> None:
    creds = get_ga4_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{args.property}",
        date_ranges=[DateRange(start_date=f"{args.days}daysAgo", end_date="today")],
        dimensions=[
            Dimension(name="sessionDefaultChannelGroup"),
            Dimension(name="sessionSource"),
            Dimension(name="sessionMedium"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="newUsers"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
        limit=20,
    )

    try:
        response = client.run_report(request)
    except Exception as e:
        print(f"Error fetching sources: {e}")
        sys.exit(1)

    if not response.rows:
        print("No data returned.")
        return

    print(f"\nTraffic Sources — Last {args.days} days (property {args.property})")
    rows = []
    for r in response.rows:
        channel = r.dimension_values[0].value
        source = r.dimension_values[1].value
        medium = r.dimension_values[2].value
        sessions = fmt_num(r.metric_values[0].value)
        users = fmt_num(r.metric_values[1].value)
        new_users = fmt_num(r.metric_values[2].value)
        rows.append([channel, source, medium, sessions, users, new_users])

    print_table(["Channel", "Source", "Medium", "Sessions", "Users", "New Users"], rows, col_width=25)


def cmd_events(args) -> None:
    creds = get_ga4_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{args.property}",
        date_ranges=[DateRange(start_date=f"{args.days}daysAgo", end_date="today")],
        dimensions=[Dimension(name="eventName")],
        metrics=[
            Metric(name="eventCount"),
            Metric(name="totalUsers"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="eventCount"), desc=True)],
    )

    try:
        response = client.run_report(request)
    except Exception as e:
        print(f"Error fetching events: {e}")
        sys.exit(1)

    if not response.rows:
        print("No data returned.")
        return

    # Conversion events to track
    conversion_events = {"form_submit", "phone_click", "contact_form", "generate_lead", "contact"}

    print(f"\nEvents — Last {args.days} days (property {args.property})")
    rows = []
    for r in response.rows:
        name = r.dimension_values[0].value
        count = fmt_num(r.metric_values[0].value)
        users = fmt_num(r.metric_values[1].value)
        flag = " <-- CONVERSION" if name in conversion_events else ""
        rows.append([name + flag, count, users])

    print_table(["Event Name", "Count", "Users"], rows, col_width=50)

    fired = {r.dimension_values[0].value for r in response.rows}
    missing = conversion_events - fired
    if missing:
        print(f"\n  WARNING: Conversion events NOT firing: {', '.join(sorted(missing))}")
    else:
        print(f"\n  OK: All tracked conversion events are firing")


def cmd_realtime(args) -> None:
    creds = get_ga4_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunRealtimeReportRequest(
        property=f"properties/{args.property}",
        dimensions=[Dimension(name="unifiedScreenName")],
        metrics=[Metric(name="activeUsers")],
        limit=10,
    )

    try:
        response = client.run_realtime_report(request)
    except Exception as e:
        print(f"Error fetching realtime data: {e}")
        sys.exit(1)

    total = sum(int(r.metric_values[0].value) for r in response.rows) if response.rows else 0

    print(f"\nRealtime — Active Users Now (property {args.property})")
    print(f"  Total active: {total}")

    if response.rows:
        print()
        rows = [[r.dimension_values[0].value, r.metric_values[0].value] for r in response.rows]
        print_table(["Page", "Active Users"], rows, col_width=60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GA4 reporting tool for Brand75")
    parser.add_argument(
        "--property", "-p",
        default="488531418",
        help="GA4 numeric property ID (default: 488531418 = Brand75). Pass before the subcommand.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-properties", help="List GA4 properties accessible to service account")

    p_traffic = sub.add_parser("traffic", help="Traffic summary")
    p_traffic.add_argument("--days", type=int, default=28)

    p_pages = sub.add_parser("pages", help="Top 10 landing pages")
    p_pages.add_argument("--days", type=int, default=28)

    p_sources = sub.add_parser("sources", help="Traffic sources breakdown")
    p_sources.add_argument("--days", type=int, default=28)

    p_events = sub.add_parser("events", help="Events with counts")
    p_events.add_argument("--days", type=int, default=28)

    sub.add_parser("realtime", help="Active users right now")

    args = parser.parse_args()

    dispatch = {
        "list-properties": cmd_list_properties,
        "traffic": cmd_traffic,
        "pages": cmd_pages,
        "sources": cmd_sources,
        "events": cmd_events,
        "realtime": cmd_realtime,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
