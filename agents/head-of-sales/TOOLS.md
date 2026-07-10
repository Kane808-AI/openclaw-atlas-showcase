# TOOLS.md — Nova (head-of-sales)
# Agent ID: head-of-sales
# Last updated: 2026-04-23

## CRITICAL: Skill Invocation Rules

Skills are NOT callable tools. Use `exec` to run them as shell commands.
- Right: `exec` -> `ddgs-search "your query" 5 duckduckgo`
- Wrong: calling `ddgs-search(...)` as a tool name

---

## GHL (GoHighLevel) — Primary CRM

- **Base URL:** `https://services.leadconnectorhq.com`
- **API key:** `~/.openclaw/.env` as `GHL_API_KEY` (pit- prefix is part of the key, never strip it)
- **Location ID:** `WbjKV1nKqrMFAFBwAplZ` (Brand75)
- **Version header:** `2021-07-28`
- **Full reference:** `~/.openclaw/workspace/memory/ghl/`

### Key Endpoints

| Action | Method | Endpoint | Notes |
|--------|--------|----------|-------|
| Search contacts | GET | `/contacts/` | `locationId` as query param |
| Create contact | POST | `/contacts/` | 422 = duplicate = success, stop retrying |
| Update contact | PUT | `/contacts/{contactId}` | |
| Add tags | POST | `/contacts/{contactId}/tags` | NOT PATCH (returns 404) |
| Get opportunities | GET | `/opportunities/` | Pipeline stage tracking |
| Update opportunity | PUT | `/opportunities/{opportunityId}` | |

### Critical GHL Rules
- `locationId` is ALWAYS a query param, NEVER a header
- `/v1/contacts` and `/api/v3` do NOT exist
- 422 on contact create = duplicate. That's a success. Do not retry.
- Never edit GHL workflows via API. Only Chris does workflow edits via UI.
- Always apply source tags on contact creation. No untagged contacts.

### Source Tags

| Lead Source | Tag |
|-------------|-----|
| Website form | `source:website-form` |
| Chat widget | `source:website-chat` |
| Click-to-call | `source:website-call` |
| Lead magnet | `source:lead-magnet` |
| Booking request | `source:website-booking` |
| Voice agent | `source:voice-agent` |
| Social signal | `source:social` |
| Google Ads | `source:google-ads` |
| Meta Ads | `source:meta-ads` |

---

## Telegram — Reporting

All lead notifications and reports go through Telegram via the Atlas integration.
- **Chat ID:** 7556461717
- Use for: new lead alerts, pipeline status updates, weekly reports

Report format:
```
🐆 New Lead: [Name]
Source: [tag]
Looking for: [brief description]
Next step: [action]
```

---

## Google Sheets — Pipeline Tracking

- **Atlas Tasks sheet:** `1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk`
- **Auth:** `~/.openclaw/scripts/google_auth.py`
- **Venv:** `~/.openclaw/venv/google/bin/python3`

Quick commands:
- Read: `~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/google_sheets_tool.py read SHEET_ID "Sheet1!A1:Z100"`
- Append: `~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/google_sheets_tool.py append SHEET_ID "Sheet1!A:F" --values-json '[["a","b"]]'`

---

## SMS Sequences

Active SMS copy lives at: `~/.openclaw/workspace/knowledge/marketing/sms-sequences.md`
Read this before any outreach. Muse owns the copy. You follow it.

Changes to SMS sequences: update `sms-sequences.md` AND notify Chris to update the GHL workflow. Only Chris edits GHL workflows.

---

## Claude Code Delegation

For complex CRM operations (bulk updates, pipeline migration, report generation):
```
exec("bash ~/.openclaw/scripts/claude-code-delegate.sh --prompt 'task description'")
```
