# Iris — Brand Intelligence Tools

## Web Search

- Tool: `ddgs-search` (DuckDuckGo backend — never use google backend)
- Use for: brand mention scans, competitor research, directory listing checks, industry site monitoring
- Always try ddgs-search before any browser or scraper tool

## HTTP Fetch

- Use for: checking directory listing pages (Clutch, DesignRush, UpCity, GoodFirms), review platform profiles, robots.txt checks
- HTTP fetch before scraper. Scraper before browser.

## Google APIs

- Auth: `~/.openclaw/scripts/google_auth.py` (service account: automation@example.com)
- Python interpreter: `~/.openclaw/venv/google/bin/python3`
- GA4 reporting: via Brand75 service account
- Google Business Profile: via Google My Business API (Places API key: GOOGLE_PLACES_API_KEY)
- Sheets: `~/.openclaw/scripts/google_sheets_tool.py`
- All Google ops under automation@example.com. Never you@example.com.

## Telegram Notification

- Script: `~/.openclaw/workspace/scripts/social-monitor/telegram_notify.py`
- Bot token: `~/.openclaw/.env` as `TELEGRAM_BOT_TOKEN`
- Chris chat ID: SHOWCASE_TELEGRAM_CHAT_ID (also in .env as `TELEGRAM_CHAT_ID`)
- Telegram group: SHOWCASE_TELEGRAM_GROUP_ID
- Use for: negative GMB review alerts (immediate), lead signal routing to Nova, critical citation losses

## State File

- Iris monitoring state: `~/.openclaw/workspace/knowledge/web-ops/iris-monitoring-state.md`
- GEO audit log: `~/.openclaw/workspace/seo/geo-audit-log.md`
- Update state file every session. Never infer state from memory.

## Google Workspace

- Auth module: `~/.openclaw/scripts/google_auth.py`
- Calendar: `~/.openclaw/scripts/add_calendar_event.py`
- Docs: `~/.openclaw/scripts/google_docs_tool.py`
- Health check: `~/.openclaw/scripts/google_health_check.py`

## Browser Tool Hierarchy

HTTP fetch first → Firecrawl second (Cloudflare/anti-bot walls) → web scraper third → browser control last resort (JS/auth-wall only)

## Firecrawl (anti-bot scraping)

- Script: `~/.openclaw/workspace/scripts/firecrawl.py`
- Free tier: 1,000 pages/month, 2 concurrent. Use sparingly — prefer HTTP fetch when target is open.
- Use when HTTP fetch returns 403/challenge HTML (Clutch, Perplexity, G2, Capterra, Yelp, etc.)
- Commands:
  - `python3 ~/.openclaw/workspace/scripts/firecrawl.py scrape <url>` → clean markdown of one page
  - `python3 ~/.openclaw/workspace/scripts/firecrawl.py map <url>` → list URLs on a domain
  - `python3 ~/.openclaw/workspace/scripts/firecrawl.py crawl <url> --limit 10` → multi-page crawl
- API key lives in `~/.openclaw/.env` as `FIRECRAWL_API_KEY`. Never echo it.

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Never write secrets into workspace files.
- Never post, publish, or respond to reviews. Surface only — Chris responds.
- Verify before reporting: read the file, check the API response, confirm the row.
- All state verification by reading filesystem directly. Never infer from memory.
- GEO audit results append-only: never overwrite previous months in geo-audit-log.md.
