# TOOLS.md — Atlas

## CRITICAL: Skill Invocation Rules

Skills are NOT callable tools. Use `exec` to run them as shell commands.
- Right: `exec` → `gog gmail search 'newer_than:7d' --max 10`
- Wrong: calling `gog(...)` as a tool name

## Web Search

Native `web_search` tool has no provider and always aborts. Do NOT use it.

Always use exec + ddgs-search:
- Right: `exec` → `ddgs-search "query" 5 duckduckgo`
- Never use `google` backend — TTY/pagination bug in non-interactive mode
- Use `duckduckgo` or `bing` only

## Claude Code Delegation

Use `exec` to delegate to Claude Code. Do NOT use sessions_spawn — it is unreliable.

**Sync (wait for result, up to 5 min):**
```
exec("bash $HOME/.openclaw/scripts/claude-code-delegate.sh --prompt 'task here'")
```

**Async (long tasks — returns task ID immediately):**
```
exec("bash $HOME/.openclaw/scripts/claude-code-delegate.sh --async --prompt 'task here'")
```

**Poll async result:**
```
exec("bash $HOME/.openclaw/scripts/claude-code-delegate.sh --status <task_id>")
```

Options: `--cwd <dir>` (default ~/.openclaw), `--model <model>`, `--timeout <seconds>` (default 300)

Output: `{"status":"complete","output":"...","exit_code":0,"duration_seconds":12}`

Rules:
- Hand off to Claude Code after 2+ terminal commands (per SOUL.md)
- Do NOT describe the handoff — execute it as a tool call immediately
- Notify Chris via Slack (#atlas) before handoff: "Handing to Claude Code: [what]. Back in ~X min."

## Google Workspace

- Auth: `~/.openclaw/scripts/google_auth.py`
- Venv: `~/.openclaw/venv/google/bin/python3`
- Primary account: support@brand75.com (never you@example.com for automation)
- Calendar ID: `primary` (always support@brand75.com primary calendar)

Quick commands (prefix: `~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/`):
- Sheets read: `google_sheets_tool.py read SHEET_ID "Sheet1!A1:Z100"`
- Sheets append: `google_sheets_tool.py append SHEET_ID "Sheet1!A:F" --values-json '[["a","b"]]'`
- Gmail search: `gmail_tool.py --account brand75 --action search --query "..." --max 20`
- Drive search: `read_gdoc_by_title.py "search words"`
- Health check: `google_health_check.py`
- Calendar: `add_calendar_event.py --summary "T" --start-time 2026-05-01T10:00:00 --end-time 2026-05-01T10:30:00`

Atlas Tasks Sheet: `1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk` (range `Atlas Tasks!A:K`)

## GoHighLevel (GHL) API

- Base URL: `https://services.leadconnectorhq.com`
- API Key: `~/.openclaw/.env` as `GHL_API_KEY` (pit- prefix is part of the key — never strip it)
- Location ID (Brand75): `WbjKV1nKqrMFAFBwAplZ`
- Version header: `2021-07-28`

Rules:
- `locationId` is ALWAYS a query parameter — NEVER a header
- Trailing slash on `/contacts/`
- Phone numbers in E.164 format
- 422 = duplicate = success, do not retry
- List contacts: `GET /contacts/?locationId={locationId}&limit=100`

## Browser Tool

Usage hierarchy — always follow this order:
1. `ddgs-search` or HTTP fetch for public info and static pages
2. Web scraper (`requests` + BeautifulSoup) for structured DOM extraction
3. Browser control ONLY when JS rendering, login/auth is required, or 1-2 fail

Start browser:
```
exec("node $HOME/.openclaw/scripts/browser_tool.js start --session atlas")
```

Always use `--session atlas`. Never per-site session names.

Core actions:
```
exec("node $HOME/.openclaw/scripts/browser_tool.js navigate --url 'https://example.com'")
exec("node $HOME/.openclaw/scripts/browser_tool.js read --selector 'div.main' --limit 5")
exec("node $HOME/.openclaw/scripts/browser_tool.js screenshot")
exec("node $HOME/.openclaw/scripts/browser_tool.js stop")
```

Screenshots save to: `~/.openclaw/workspace/browser_screenshots/`

## OpenClaw Config

Always use `openclaw config set` — never edit openclaw.json directly.

```bash
openclaw config set agents.defaults.model.primary "google/gemini-2.5-flash"
openclaw gateway status
openclaw logs --follow
```

NEVER run: `openclaw gateway install`, `openclaw doctor --fix`

## Activity Status Writes

Write status entries to `~/.openclaw/workspace/data/agent-activity.json` at task start, delegation, and completion. JSON fields: id, timestamp, agent, displayName, event, task, delegatedBy. Keep "feed" max 50 entries. Write atomically via .tmp rename.

## Slack Messaging

Chris chat ID: `7556461717`

All completion reports go to #atlas. Per-agent reports go to each agent's own channel (see AGENTS.md for channel list).

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Never write secrets into workspace files.
- Never use openrouter/auto.
- All state verification by reading filesystem. Never infer.
