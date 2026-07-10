# TOOLS.md — Nalu (social-media-manager)

## Social Monitor Scripts

| Script | Purpose |
|--------|---------|
| `~/.openclaw/workspace/scripts/social-monitor/youtube_monitor.py` | YouTube comments, mentions, engagement |
| `~/.openclaw/workspace/scripts/social-monitor/youtube_kpi.py` | YouTube subscriber/view KPIs |
| `~/.openclaw/workspace/scripts/social-monitor/tiktok_monitor.py` | TikTok monitoring via TikTokApi (jason94770 ms_token). Run with `~/.openclaw/venv/tiktok/bin/python3`. Own 4h cron: `ai.openclaw.tiktok-monitor`. |
| `~/.openclaw/workspace/scripts/social-monitor/x_monitor.py` | X/Twitter monitoring via Apify |
| `~/.openclaw/workspace/scripts/social-monitor/triage.py` | Engagement classification engine |
| `~/.openclaw/workspace/scripts/social-monitor/daily_digest.py` | Daily KPI digest compiler |
| `~/.openclaw/workspace/scripts/social-monitor/run_monitor.sh` | Full pipeline runner |

Not yet built:
- Instagram monitor — pending Meta Developer App setup by Chris
- Facebook monitor — shares Meta infra with Instagram
- LinkedIn monitor — pending LinkedIn Developer App approval
- Pinterest monitor — Phase 3, KPI-only

## Data Store

- Notifications DB: `~/.openclaw/workspace/social-monitor/notifications.db` (SQLite)
- DB utils: `~/.openclaw/workspace/scripts/social-monitor/db_utils.py`
- Last poll state: `~/.openclaw/workspace/social-monitor/last_poll.json`

## YouTube API

Full API access via YouTube Data API v3.

Run via Python venv:
```bash
~/.openclaw/venv/google/bin/python3 ~/.openclaw/workspace/scripts/social-monitor/youtube_kpi.py
```

Brand75 YouTube channel ID: check `~/.openclaw/workspace/memory/MEMORY.md` for current channel ID.

## X/Twitter

- Read: `x_monitor.py` (Apify-based)
- Write: `~/.openclaw/workspace/skills/twitter-api/` (cookie-based, Tier 2)

For write actions: notify Atlas before executing. 10-minute countermand window. Format Slack message: "Posting to X: [content preview]. 10 min to countermand."

## Skills to Invoke (on-demand only)

Read the relevant skill before executing these workflow types:
- YouTube content pipeline: `~/.openclaw/workspace/skills/youtube-automation-ops/SKILL.md`
- Pinterest operations: `~/.openclaw/workspace/skills/pinterest-ops/SKILL.md`
- Affiliate content scheduling: `~/.openclaw/workspace/skills/affiliate-content-ops/SKILL.md`

## Google Workspace

- Auth: `~/.openclaw/scripts/google_auth.py` (support@brand75.com service account)
- Venv: `~/.openclaw/venv/google/bin/python3`
- Sheets: `~/.openclaw/scripts/google_sheets_tool.py`
- Calendar: `~/.openclaw/scripts/add_calendar_event.py`
- All Google ops under support@brand75.com. Never you@example.com.

Content calendar lives in Google Sheets. Check Atlas Tasks Sheet for content queue:
- Sheet ID: `1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk`

## Slack Notifications

All KPI digests and reports go to #nalu-social-media-manager.
Lead signal alerts go to #atlas AND #nova-head-of-slaes via Atlas.

## Browser Tool Hierarchy

1. HTTP fetch for public data and static pages
2. Web scraper for structured DOM extraction
3. Browser control ONLY when JS rendering or auth required

```
exec("node $HOME/.openclaw/scripts/browser_tool.js start --session atlas")
exec("node $HOME/.openclaw/scripts/browser_tool.js navigate --url 'https://example.com'")
exec("node $HOME/.openclaw/scripts/browser_tool.js stop")
```

Always use `--session atlas`. Never per-site names.

## Web Search

Use exec + ddgs-search (never native web_search):
```
exec("ddgs-search 'query' 5 duckduckgo")
```

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- TikTok: manual posting only. Never post autonomously. ToS violation.
- Always confirm TikTok account (personal vs Brand75 vs DGC) before any action.
- All state verification by reading filesystem directly. Never infer from memory.
- Verify before reporting: read the DB, check the log, confirm the row.
- Never write secrets into workspace files.
- All automation under support@brand75.com account. Never you@example.com.
