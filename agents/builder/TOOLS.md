# TOOLS.md — Leo (builder)

## Claude Code Delegation

Leo uses Claude Code as the execution layer for multi-step terminal work. Leo owns the task end-to-end: read the relevant project files, plan the work, write a detailed Claude Code prompt with file paths and acceptance criteria, then delegate execution.

**Sync (up to 5 min):**
```
exec("bash $HOME/.openclaw/scripts/claude-code-delegate.sh --prompt 'task here'")
```

**Async (long builds):**
```
exec("bash $HOME/.openclaw/scripts/claude-code-delegate.sh --async --prompt 'task here'")
exec("bash $HOME/.openclaw/scripts/claude-code-delegate.sh --status <task_id>")
```

Output: `{"status":"complete","output":"...","exit_code":0,"duration_seconds":12}`

## Web Search

Use exec + ddgs-search (never native web_search):
```
exec("ddgs-search 'query' 5 duckduckgo")
```

## GitHub Repos

All Brand75 sites live under the `Kane808-AI/` org on GitHub.

Working directories:
- Brand75 site: TBD per project
- Callahan Law: DO NOT TOUCH (agents do not touch WordPress sites)

## Netlify

Deploy pipeline: CI/CD on git push to `main` branch (triggers auto-deploy).

Verification:
- Check deploy status in Netlify dashboard
- Curl the live URL: `curl -I https://<site>.netlify.app`
- Curl the API health endpoint if applicable

## Cloudflare

DNS and CDN for all Brand75 properties. Access via browser tool.

Robot access: ensure AI crawlers are NOT blocked in Cloudflare rules (no User-Agent blocking for GPTBot, Claude-Web, PerplexityBot, Googlebot-extended).

## GHL API

- Base URL: `https://services.leadconnectorhq.com`
- API Key: `~/.openclaw/.env` as `GHL_API_KEY` (pit- prefix is part of the key)
- Location ID (Brand75): `SHOWCASE_GHL_LOCATION_ID`
- Version header: `2021-07-28`
- `locationId` always a query parameter, never a header
- Trailing slash on `/contacts/`
- List contacts: `GET /contacts/?locationId={locationId}&limit=100`
- Create contact: `POST /contacts/` with locationId in body

## n8n

Local n8n instance: `http://127.0.0.1:5678`

API: `GET /api/v1/workflows` — check workflow status
Leo builds n8n workflows programmatically via API. Chris activates them via UI.

## Google Workspace

- Venv: `~/.openclaw/venv/google/bin/python3`
- Auth: `~/.openclaw/scripts/google_auth.py`
- Primary account: automation@example.com

Quick commands:
- Sheets: `google_sheets_tool.py read/append SHEET_ID "range"`
- Calendar: `add_calendar_event.py --summary "..." --start-time ... --end-time ...`
- Health check: `google_health_check.py`

## Site Health Checks

```bash
# Uptime check
curl -s -o /dev/null -w "%{http_code}" https://<site>/api/health

# SSL check
echo | openssl s_client -connect <domain>:443 2>/dev/null | openssl x509 -noout -dates

# Security headers check
curl -I https://<site>/ | grep -E "(Strict-Transport|X-Frame|X-Content|Content-Security)"

# Lighthouse (requires Chrome)
lighthouse https://<site>/ --output=json --quiet
```

## Schema Validation

Use Google Rich Results Test via browser tool: https://search.google.com/test/rich-results

Required schema stacks per page type (from growth-engine-architecture.md):
- Home: Organization + WebSite + LocalBusiness
- Service pages: Service + FAQPage + BreadcrumbList
- Blog/content: Article + FAQPage + BreadcrumbList
- Contact: LocalBusiness + ContactPoint

## Skills to Invoke (on-demand only)

When a task matches these domains, read the skill before starting:
- `~/.openclaw/workspace/knowledge/skills/leo-frameworks.md` — pre-deploy SEO checklist, schema implementation, technical SEO audit
- `~/.openclaw/workspace/knowledge/skills/brand-consistency.md` — Brand75 color tokens, typography, spacing system

## Browser Tool

Usage hierarchy:
1. `ddgs-search` or HTTP fetch first
2. `requests` + BeautifulSoup for structured DOM
3. Browser control ONLY when JS rendering or auth required

```
exec("node $HOME/.openclaw/scripts/browser_tool.js start --session atlas")
exec("node $HOME/.openclaw/scripts/browser_tool.js navigate --url 'https://example.com'")
exec("node $HOME/.openclaw/scripts/browser_tool.js screenshot")
```

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Never touch `.env` or `credentials/` directly.
- No secrets in client-side code.
- Environment variables in Netlify dashboard, never in repos.
- GHL workflows: build via API; UI activation by Chris only.
- Deploy approval from Ryan before merging to main — no exceptions.
- `trash` over `rm` for any file removal.
