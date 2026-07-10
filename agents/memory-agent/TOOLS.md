# TOOLS.md — Memory Agent

## Primary Write Target

All Memory Agent writes go to: `~/.openclaw/workspace/memory/`

Never write outside this directory.

## Daily Logs

Path pattern: `~/.openclaw/workspace/memory/YYYY-MM-DD.md`

Format for each entry:
```
## [HH:MM PT] Agent — Task Title

[YYYY-MM-DD HH:MM] agent_id | status | one-line summary
  → KPI: metric = value (if present)
  → Flag: description (if present)
  → Next: next_action
```

## Archive

Archive daily logs older than 7 days to: `memory/archive/YYYY-MM/`

Move files (do not delete). Never delete memory files.

```bash
mv ~/.openclaw/workspace/memory/YYYY-MM-DD.md \
   ~/.openclaw/workspace/memory/archive/YYYY-MM/YYYY-MM-DD.md
```

## Loop A Outbound Log

Path: `~/.openclaw/workspace/memory/loop_a_outbound_log.md`

One row per batch. Format:
```
| YYYY-MM-DD HH:MM | batch_id | contacts_sent | opt_outs | failures | variant | notes |
```

## Compliance Cross-Reference

Read before logging any Nova send batch:
```bash
cat ~/.openclaw/workspace/memory/loop_a_compliance_audit.md
```

If a contact ID is not listed as CLEAR — escalate to Atlas as Tier 1. Do not log.

## Reading Agent Output

Agent output schema: `~/.openclaw/workspace/schemas/agent_output.json`

Read agent outputs from:
- `~/.openclaw/workspace/data/agent-activity.json` — activity feed
- Task-specific output files as referenced in each agent report

## Google Sheets (for cross-referencing)

Atlas Tasks Sheet: `1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk`

Read via:
```bash
~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/google_sheets_tool.py \
  read 1XSZ1xrjx0mhrLP9Z7eBMP6pPCZ4H__QCTfUSFzKPqGk "Atlas Tasks!A:K"
```

## Memory Files Reference

| File | Purpose |
|------|---------|
| `memory/MEMORY.md` | Durable facts — human-written, append-only |
| `memory/PATTERNS.md` | Behavioral lessons ([PATTERN] entries) |
| `memory/KNOWN_ISSUES.md` | Active bugs (remove when resolved) |
| `memory/YYYY-MM-DD.md` | Daily session logs |
| `memory/loop_a_compliance_audit.md` | Contacts cleared for Loop A outreach |
| `memory/loop_a_outbound_log.md` | Loop A send history |
| `memory/archive/YYYY-MM/` | Archived daily logs |
| `memory/*.sqlite` | OpenClaw internal databases — DO NOT TOUCH |

## Pattern Detection

When compressing agent outputs, watch for:
- Same error 3+ times across sessions → flag as pattern, proactively notify Atlas
- KPI trending down across 3+ consecutive logs → flag immediately
- Pipeline stage stalled (no Nova activity 48+ hours) → flag to Atlas
- Agent not reporting on schedule → flag to Atlas

## Key Constraints

- TOOLS.md hard limit: 10,000 characters. Silent truncation above this.
- Write access: `~/.openclaw/workspace/memory/` only.
- Never modify `memory/*.sqlite` files.
- Never delete memory files — archive instead.
- Never compress Tier 1 outputs — pass through verbatim.
- Batch non-urgent compressions — run once per hour during active hours (8 AM–11 PM PT).
- Process Tier 1 and Tier 2 immediately on receipt.
