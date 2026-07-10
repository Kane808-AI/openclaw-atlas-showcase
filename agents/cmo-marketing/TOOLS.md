# TOOLS.md — Koa (cmo-marketing)

## Web Search

Use exec + ddgs-search (never the native web_search tool):
```
exec("ddgs-search 'query' 5 duckduckgo")
```
Use `duckduckgo` or `bing` backend only. Google backend has a TTY bug in non-interactive mode.

## Google Workspace

Koa uses Google Sheets for tracking, reports, and content calendars.

- Venv: `~/.openclaw/venv/google/bin/python3`
- Primary account: support@brand75.com

Quick commands (prefix: `~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/`):
- Sheets read: `google_sheets_tool.py read SHEET_ID "Sheet1!A1:Z100"`
- Sheets append: `google_sheets_tool.py append SHEET_ID "Sheet1!A:F" --values-json '[["a","b"]]'`
- Drive search: `read_gdoc_by_title.py "search words"`

Atlas Tasks Sheet: `1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk` (range `Atlas Tasks!A:K`)

## GSC (Google Search Console)

Koa reviews GSC data weekly. Access via browser tool.

Browser hierarchy: HTTP fetch first → scraper second → browser control last resort.

Start browser: `exec("node $HOME/.openclaw/scripts/browser_tool.js start --session atlas")`

GSC URL: https://search.google.com/search-console

## GEO Audit Tools

For GEO citation audits (monthly — 10 queries across 3 AI platforms):
- ChatGPT: browser tool to chat.openai.com
- Perplexity: browser tool to perplexity.ai
- Gemini: browser tool to gemini.google.com

Audit log destination: `~/.openclaw/workspace/knowledge/brand-intel/geo-audit-log.md`

## GA4 Analytics

Access via browser tool → analytics.google.com

When reporting on AI referral traffic, filter by source containing: chatgpt, perplexity, claude, gemini, bing

## SEO Reference Files

Read before executing any SEO task:
- `~/.openclaw/workspace/knowledge/web-ops/growth-engine-architecture.md` — the full system
- `~/.openclaw/workspace/knowledge/marketing/brand75-voice.md` — voice guidelines
- `~/.openclaw/workspace/knowledge/marketing/target-audiences.md` — who we're targeting

## Content Calendar

Content calendar location: `~/.openclaw/workspace/knowledge/marketing/content-calendar.md`

Koa maintains the editorial calendar and freshness schedule. Flag any page older than 90 days for refresh.

## Skills to Invoke (on-demand only)

When a task matches these domains, read the relevant skill before starting:
- `~/.openclaw/workspace/knowledge/skills/koa-frameworks.md` — content strategy, AI SEO/GEO, programmatic SEO, page CRO, marketing ideas, competitor alternatives
- YouTube strategy: `~/.openclaw/workspace/skills/youtube-automation-ops/SKILL.md` (when scoping YouTube content)
- Affiliate content: `~/.openclaw/workspace/skills/affiliate-content-ops/SKILL.md` (when scoping affiliate campaigns)
- Pinterest: `~/.openclaw/workspace/skills/pinterest-ops/SKILL.md` (when scoping Pinterest execution)

## Slack Reporting

All reports go to #koa-cmo. Copy briefs go directly to Muse in #muse-copywriter. Social content strategy goes to Nalu in #nalu-social-media-manager.

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Koa directs — does not execute. Never post content, build pages, or implement technically.
- Never write secrets into workspace files.
- All automation under support@brand75.com.
