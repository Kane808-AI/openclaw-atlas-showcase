# TOOLS.md — Aura (coo-operations)
# Agent ID: coo-operations
# Last updated: 2026-04-23

## CRITICAL: Skill Invocation Rules

Skills are NOT callable tools. Use `exec` to run them as shell commands.
- Right: `exec` -> `ddgs-search "your query" 5 duckduckgo`
- Wrong: calling `ddgs-search(...)` as a tool name

---

## Monitoring Tools

### Site Health Checks

Uptime monitoring via cron + curl:
```bash
curl -s -o /dev/null -w "%{http_code}" https://brand75.com/api/health
```
Expected: HTTP 200. Two consecutive non-200 responses = alert.

### Lighthouse CI

Run performance audits:
```bash
npx lighthouse https://brand75.com --output json --output-path ./lighthouse-report.json
```

Key metrics to extract: LCP, CLS, TTFB, Performance score, Accessibility score.

### SSL Check

```bash
echo | openssl s_client -servername brand75.com -connect brand75.com:443 2>/dev/null | openssl x509 -noout -dates
```
Alert if expiry < 14 days from today.

### Broken Link Scan

Use `linkchecker` or equivalent:
```bash
pip install linkchecker --break-system-packages
linkchecker https://brand75.com --no-warnings
```

---

## Infrastructure

### Mac Mini Services

Atlas and supporting services run on the Mac Mini. Key services to monitor:

| Service | Check Command | Expected |
|---------|---------------|----------|
| n8n | `curl -s http://127.0.0.1:5678/healthz` | 200 OK |
| Atlas | Check Telegram responsiveness | Responds within 60s |

### n8n

- **Local URL:** `http://127.0.0.1:5678`
- **API base:** `http://127.0.0.1:5678/api/v1/`
- **API key:** `~/.openclaw/secrets/n8n-api-key` (header: `X-N8N-API-KEY`)
- **Service:** `com.openclaw.n8n` (auto-start, KeepAlive enabled)

Check if workflows are executing on schedule:
```bash
curl -s -H "X-N8N-API-KEY: $(cat ~/.openclaw/secrets/n8n-api-key)" \
  http://127.0.0.1:5678/api/v1/executions?limit=5
```

---

## Telegram — Alerting

All alerts route through Telegram via Atlas integration.
- **Chat ID:** 7556461717

Alert format by severity:
```
🔴 CRITICAL: [Site down / Data breach / Lead flow broken]
Action: [what's happening]
Assigned: [who's on it]

🟡 MEDIUM: [SSL warning / GSC error spike / Integration hiccup]
Action: [what's happening]
ETA: [expected resolution]

🟢 LOW: [Content stale / Schema warning]
Action: [what needs to happen]
Owner: [responsible agent]
```

---

## Google Workspace

- **Auth:** `~/.openclaw/scripts/google_auth.py`
- **Venv:** `~/.openclaw/venv/google/bin/python3`
- **GCP project:** `openclaw-brand75-488404`
- **Account:** support@brand75.com

Use for: checking service account health, verifying token refreshes, reading operational data from Sheets.

---

## Process Compliance Checks

### Handoff Protocol
Verify handoff briefs exist at: `~/.openclaw/workspace/handoffs/`
Check: most recent files sorted by date in filename. Flag sessions that changed state but left no handoff.

### Project Spec Gate
Verify specs exist at: `~/.openclaw/workspace/projects/<project-slug>.md`
Before any build starts, confirm the file exists on disk: `ls -lh ~/.openclaw/workspace/projects/<slug>.md`

### Agent Reporting Cadence
Track whether scheduled reports were delivered:
- Koa: weekly GSC/GA4, monthly GEO audit
- Nova: real-time lead alerts, weekly pipeline status
- Leo: per-task completion reports
- Iris: daily GMB monitoring, weekly brand mentions

---

## Claude Code Delegation

For complex monitoring setup, script creation, or infrastructure tasks:
```
exec("bash ~/.openclaw/scripts/claude-code-delegate.sh --prompt 'task description'")
```
