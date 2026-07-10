# TOOLS.md — Ryan (ceo-strategy)
# Agent ID: ceo-strategy
# Last updated: 2026-04-23

## CRITICAL: Skill Invocation Rules

Skills are NOT callable tools. Use `exec` to run them as shell commands.
- Right: `exec` -> `ddgs-search "your query" 5 duckduckgo`
- Wrong: calling `ddgs-search(...)` as a tool name

---

## Pre-Deploy Review Tools

### Netlify Preview URLs

Every feature branch pushed to GitHub generates a Netlify preview URL. This is where you review builds before approving merge to `main`.

Preview URL pattern: `https://<branch-name>--<site-name>.netlify.app`

What to check on preview:
- All checklist items from SOUL.md
- Mobile responsive (resize browser or use dev tools device emulation)
- Forms actually submit (test with dummy data)
- Schema validates (paste URL into Google Rich Results Test)

### Google Rich Results Test

URL: `https://search.google.com/test/rich-results`

Paste the Netlify preview URL. Verify:
- No schema errors
- Correct schema types detected per page type (see growth engine architecture for triple stacks)
- FAQ, Service, Organization, LocalBusiness all rendering

### Lighthouse

Run against preview URL:
```bash
npx lighthouse <preview-url> --output json
```

Check: Performance > 90, Accessibility > 90, SEO > 90, Page load < 3s.

### robots.txt and AI Crawler Check

On preview, verify:
```bash
curl -s <preview-url>/robots.txt
```

Must explicitly allow: Googlebot, GPTBot, ChatGPT-User, ClaudeBot, PerplexityBot, GoogleOther, Applebot-Extended.

### llms.txt Check

```bash
curl -s <preview-url>/llms.txt
```

Must be present, formatted per llmstxt.org spec, and accurate to current site content.

---

## Prioritization Framework Reference

When evaluating competing tasks:

| Tier | Category | Examples |
|------|----------|----------|
| T1 | Compliance and safety | Legal exposure, data breach, broken security headers |
| T2 | Revenue proximity | Broken lead form, blocked checkout, client deliverable |
| T3 | Client-facing quality | Copy errors, design bugs, slow pages |
| T4 | Internal improvement | Agent upgrades, docs, automation efficiency |

Within the same tier: closer to completion wins. Finishing beats starting.

---

## Telegram — Reporting

All deploy approvals/rejections go through Telegram.
- **Chat ID:** SHOWCASE_TELEGRAM_CHAT_ID

Approval format:
```
✅ DEPLOY APPROVED: [site/branch]
Checklist: PASS (all items)
Ready to merge to main.
```

Rejection format:
```
❌ DEPLOY REJECTED: [site/branch]
Failing items:
- [specific item 1]
- [specific item 2]
Returned to Leo for fixes.
```

---

## Google Sheets — Task Tracking

- **Atlas Tasks sheet:** `SHOWCASE_ATLAS_TASKS_SHEET_ID`
- **Auth:** `~/.openclaw/scripts/google_auth.py`
- **Venv:** `~/.openclaw/venv/google/bin/python3`

Use for reviewing active task assignments, checking agent workload, flagging resource conflicts.

---

## Claude Code Delegation

For tasks requiring file system access or running validation scripts:
```
exec("bash ~/.openclaw/scripts/claude-code-delegate.sh --prompt 'task description'")
```
