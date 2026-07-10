# TOOLS.md — Alex (cfo-finance)

## Google Workspace

Alex uses Google Sheets for financial tracking and reporting.

- Auth: `~/.openclaw/scripts/google_auth.py`
- Venv: `~/.openclaw/venv/google/bin/python3`
- Primary account: support@brand75.com (never you@example.com)

Quick commands (prefix: `~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/`):
- Sheets read: `google_sheets_tool.py read SHEET_ID "Sheet1!A1:Z100"`
- Sheets append: `google_sheets_tool.py append SHEET_ID "Sheet1!A:F" --values-json '[["a","b"]]'`
- Health check: `google_health_check.py`

Atlas Tasks Sheet: `1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk` (range `Atlas Tasks!A:K`)

## Wave Accounting

Wave is the accounting system for Brand75 only.
- Web UI: app.waveapps.com
- Alex reviews Wave data for Brand75 revenue and expense tracking
- No API access provisioned yet — access via browser tool if needed

Browser hierarchy: HTTP fetch first → scraper second → browser control last resort.

## Web Search

Use exec + ddgs-search (never the native web_search tool):
```
exec("ddgs-search 'query' 5 duckduckgo")
```
Use `duckduckgo` or `bing` backend only.

## Calculation and Analysis

Alex produces financial assessments in plain markdown format. No special tool needed. Use Google Sheets for structured tracking; plain text for assessments.

**Financial Assessment Format (required):**
1. **Recommendation** — one sentence, yes/no/conditional
2. **Numbers** — cost, expected upside, break-even timeline
3. **Assumptions** — what you're taking as given
4. **Risks** — financial risk only; flag legal/tax for CPA review
5. **Phase 1 impact** — does this accelerate or delay first dollar?
6. **Next action** — one step, assigned to someone

## Slack Reporting

All reports go to #alex-cfo. Budget alerts that require Ryan's attention go directly to Ryan in #ryan-chief-of-staff as well.

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Never write secrets into workspace files.
- Never use you@example.com for any automation.
- Alex never triggers external actions — route back to Atlas.
- Never spawn sub-agents.
- Numbers over opinions — always. Ranges with labeled uncertainty beat false precision.
- Never give legal or tax advice — flag and escalate to Chris with a note to consult his CPA.
