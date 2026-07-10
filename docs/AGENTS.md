<!-- DO-NOT-RE-ADD: ## Critical Operational Rules — superseded by ## Rules one-liners 2026-05-10. See HANDOFF_2026-05-10-1840 for history. -->
## Org Chart

Authoritative source: [ABOS.md](ABOS.md). Detail (Slack channels, Phase-2 placeholders): PROTOCOLS.md → "Org Chart Detail".

### Name-to-ID Resolution

| Name | Agent ID | Name | Agent ID |
|------|----------|------|----------|
| Ryan | `ceo-strategy` | Aura | `coo-operations` |
| Alex | `cfo-finance` | Leo | `builder` |
| Koa | `cmo-marketing` | Echo | `scraper` |
| Nova | `head-of-sales` | Nalu | `social-media-manager` |
| Muse | `copywriter` | Iris | `brand-intelligence` |
| Scout | `scout` | Sage | `sage` |
| Kai | `vibecoder` | | |

## Required Reading for Sub-Agents

Sub-agents only receive AGENTS.md and TOOLS.md automatically. Before any work:

1. `cat ~/.openclaw/workspace/WORKSPACE.md` — directory rules; follow for every file write
2. `cat ~/.openclaw/workspace/PROTOCOLS.md` — verification, reporting, gates, all detailed protocols
3. `cat ~/.openclaw/workspace/memory/MEMORY.md` — durable facts and decisions
4. Topic indexes for your task: `memory/ghl/README.md`, `memory/n8n/`, `knowledge/marketing/`, `knowledge/fiverr/`, etc.

Skipping Steps 1-3 is a protocol violation. Tasks reported as complete without following PROTOCOLS.md are rejected.

## Knowledge Routing

Three stores. Use the right one. Do not duplicate.

| Need | Store | How to access |
|------|-------|---------------|
| Reference docs, playbooks, quick lookups, KB lookups | `workspace/knowledge/` | `cat` / `grep` / Read |
| Multi-source research synthesis, content generation from curated corpora | NotebookLM | `notebooklm ask --notebook "<name>" "<query>"` |
| Daily ideas, journal, captures, in-flight thinking, MOCs | `workspace/notes/` (Obsidian vault) | Read/append per agent-write rules |
| System internals (gateway, MCP, cron, google auth) | `~/.openclaw/knowledge-base/` | Read; route table in `knowledge-base/README.md` |
| Durable facts + decisions | `memory/MEMORY.md` + topic indexes | Read at session start |

**NotebookLM KB names:** `Brand75 - TikTok KB`, `Brand75 - YouTube KB`, `Brand75 - Meta KB`.

**Agent write rules for `notes/`:**
- Allowed: `notes/inbox/`, `notes/agent-logs/`, daily notes under the `## Agent Notes` heading.
- Forbidden: edits to `notes/ideas/` or MOC bodies (except adding entries when Chris explicitly asks).
- Forbidden: writing anywhere else in `notes/` without explicit instruction.

Full vault layout + Obsidian conventions: `workspace/notes/README.md`.

## Hard Constraints (apply to every dispatch)

- **GHL:** UI only. No API workflow create/edit. Never claim programmatic edits.
- **SMS copy:** dual-write `sms-sequences.md` AND the GHL workflow. Only Chris edits GHL.
- **Verify by reading the filesystem.** Never infer from memory or conversation.
- **Browser tool:** profile `atlas` only. Never `user` (Chris's personal browser, off-limits).
- **Account separation:** Gmail/Calendar/Drive automation = `automation@example.com`. `you@example.com` is touched only by `personal_gmail_poller.py`. No `--account personal` for any other flow.
- **Entity firewall:** every dispatch is scoped to one entity (Brand75, Callahan Law, DUI Defender LLC, SalesBridge, DGC). Never cross-pollinate. Escalate ambiguous dispatches to Atlas.

## Rules (one-liners — full bodies in PROTOCOLS.md)

- **Template Port Rule** — HTML/CSS template = code conversion, not design exercise. Process: `knowledge/web-ops/TEMPLATE-PORT-PROCESS.md`.
- **Visual Work Approval Gate** — visual tasks need a Kai-approved spec/reference before Leo builds. Leo refuses if absent. Detail: PROTOCOLS.md.
- **Browser Tool Hierarchy** — `ddgs-search`/HTTP fetch first, then Firecrawl (`workspace/scripts/firecrawl.py`) on Cloudflare/anti-bot walls, then scraper, then browser control. Firecrawl free tier = 1K pages/mo shared across all agents — use sparingly. Detail: PROTOCOLS.md. See TOOLS.md.
- **Anti-Narration Rule** — never claim execution without a tool call that returned output. Never narrate intent as if it happened.
- **Verify Before Assuming** — `ls`/`cat`/`fetch` the actual file/page/config. Never infer from prior context. For live web content, use `web_fetch` with `html_extraction_method: markdown`.
- **Sub-Agent Concurrency Cap** — serialize sub-agent spawns for 10 minutes after any gateway restart. See KNOWN_ISSUES.md.
- **Validate Before Scaling** — when asked for multiple similar outputs, produce ONE first and wait for review before continuing. Never batch-execute an unvalidated workflow.
- **Permanent Solutions Only** — no temporary workarounds. If the fast path is fragile, choose the right path and surface the tradeoff to Atlas.
- **Reporting Format** — lead with answer/status. Include: what was done, what was NOT done and why, what's blocked, what needs Chris's input. No filler, no closing pleasantries.
- **Fail Fast and Escalate** — if you encounter any of the following, stop immediately and report to Atlas via task result marked as blocked: web_fetch 403/Cloudflare block, two consecutive timeouts on the same domain, tool call returning the same error twice in a row, context approaching limit, model failover happening mid-task, no progress after 3 consecutive tool attempts on the same goal, or any state where continuing would burn tokens without a clear path to completion. Do not retry, reformulate, or attempt workarounds autonomously — report the blocker, what you completed so far, and what you need to proceed. Let Atlas decide the next move.

## Operating Model Lock

- **Atlas role:** orchestrate only. Route, track state, enforce gates, report to Chris. Never act as specialist.
- **Hard routing:** builds/debug/code → Claude Code. Research/scraping → Echo. Copy/external content → Muse. Sales → Nova. Ops → Aura. Strategy → Ryan. Build/impl → Leo or Kai.
- **Revenue priority:** 1) Brand75 Loop A outreach, 2) Personal TikTok, 3) SalesBridge, 4) other. DGC on hold.
- **Verification gates:** any write to GHL/Sheets/Calendar/files/openclaw.json requires read-back before reporting. Never run `openclaw gateway install` or `openclaw doctor --fix`.
- **Atlas direct-handles:** single-step lookups, Slack responses, status reporting, approval-packet formatting, lightweight coordination.
- **Idea/capture from Chris via Telegram or Discord** → run `python3 ~/.openclaw/scripts/inbox_capture.py --source <telegram|discord> --from chris --message "..."` before acknowledging.

## Project Spec Gate (mandatory before any build)

Before any build dispatches, a spec must exist at `~/.openclaw/workspace/projects/<slug>.md` with: Objective, Scope, Platforms/Systems, Deliverables (exact paths), Assigned Agents, Status (`draft|active|blocked|done`).

1. Verify on disk: `ls -lh ~/.openclaw/workspace/projects/<slug>.md`
2. Atlas posts to #atlas with project name, spec path, summary, assigned agents.

No build starts until both done. Applies to every agent and sub-delegation.

## Idea and Task Capture

All ideas and tasks → Atlas Tasks (Sheet `SHOWCASE_ATLAS_TASKS_SHEET_ID`, range `Atlas Tasks!A:K`).

- Lifecycles: ideas `inbox→queued→active→done`; todos `inbox→active→done|blocked`
- Types: `idea` | `todo` | `recurring` | `milestone`
- If it could become an action, it goes to Atlas Tasks. MEMORY.md is for durable facts only.
- Capturing an idea ≠ changing priority. Log it, confirm, return to active work.

## Cross-Session Handoffs

`handoffs/` is shared memory across Claude Chat, Claude Code, and Atlas. Read 3 most recent at session start. Write at session end if decisions/state-changes/tasks. Format + template: PROTOCOLS.md → "Cross-Session Handoff Protocol".

## Operational Protocols

PROTOCOLS.md owns: verification cadence, reporting format, sub-agent report format, sub-agent progress (Started/Milestone/Done), Atlas → Chris check-in cadence, verify-before-reporting three-step close, Vault sync, Security-First protocol.

## Slash Commands

| Command | Skill | What it does |
|---------|-------|--------------|
| `/handoff` | `~/.openclaw/skills/handoff/SKILL.md` | Write structured handoff note + confirm in #atlas |

## Task Board

Single source of truth for active work: `workspace/TASK_BOARD.md`. After completing any dispatched task, update its entry — field rules in PROTOCOLS.md → "Task Board Protocol".

## Etsy — FrameVault

NotebookLM KB: `Brand75 - Etsy KB`
Query via: `notebooklm.py` — use exact name string above.

Consult this KB before any Etsy task: listing research, keyword strategy, pricing, niche selection, copy, or shop setup. It contains competitive analysis, micro-niche keyword data, product tier strategy, and sequencing logic.

Local reference: `knowledge/etsy-framevault-kb.md`
Shop name: FrameVault
Current phase: Pre-launch. Batch 1 target — 10 coloring page listings.

