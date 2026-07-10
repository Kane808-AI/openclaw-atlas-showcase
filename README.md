# OpenClaw Atlas — a multi-agent AI operations system

This is a curated, sanitized snapshot of **Atlas**: a personal multi-agent AI
system I designed and run to operate several real businesses — a marketing
agency, a law-firm SEO client, an e-commerce brand, and my own content
pipelines. It runs continuously on a Mac mini, coordinating a team of
specialized AI agents that do real work: SEO audits, content generation,
CRM automation, competitor monitoring, and infrastructure health checks.

It is built on top of [OpenClaw](https://github.com/openclaw/openclaw), an
open-source agent gateway. This repo shows the **architecture and automation I
built on top of it** — the org design, the agent personas, and ~80 automation
scripts wired into live APIs.

> **Note on scope.** This is a showcase mirror, not the running system. Secrets,
> session logs, browser state, and credentials never leave the private repo. An
> allowlist export script (`tools/export-from-openclaw.sh`) copies only
> portfolio files, redacts identifiers, and runs a `gitleaks` gate before
> anything lands here. If the gate finds a secret, the export aborts.

## The idea: an AI company, not a chatbot

Instead of one general assistant, Atlas is structured like a small company. A
main orchestrator routes work to 15 specialized agents, each with its own
persona (`SOUL.md`), operating rules (`AGENTS.md`), and tool access (`TOOLS.md`).

| Agent | Role |
|-------|------|
| `main` | Orchestrator — routes work, owns the daily cadence |
| `ceo-strategy` | Strategic direction and prioritization |
| `coo-operations` | Runs recurring operational workflows |
| `cfo-finance` | Cost tracking and finance ops |
| `cmo-marketing` | Marketing strategy and campaign planning |
| `head-of-sales` | Lead research and sales prep |
| `copywriter` | Content and copy production |
| `brand-intelligence` | Brand monitoring and research |
| `social-media-manager` | Social content and scheduling |
| `scout` | Discovery and reconnaissance |
| `scraper` | Structured data collection |
| `builder` / `vibecoder` | Build and ship code and sites |
| `memory-agent` | Long-term memory curation |
| `sage` | Review and quality gate |

Each agent reads its own instruction files at startup, so behavior is defined in
version-controlled markdown, not buried in code. See
[`docs/AGENTS.md`](docs/AGENTS.md) for the master orchestration rules and
[`agents/`](agents/) for every persona.

## What's actually automated (`scripts/`, `automations/`)

~58 Python and ~18 shell scripts wired into production APIs. A sample of what
runs on a schedule:

- **SEO / GEO** — Google Search Console index triage and safe autofix, AI
  citation-rank tracking across ChatGPT / Gemini / Perplexity, GA4 anomaly
  detection, sitemap and schema checks.
- **Infrastructure health** — multi-zone Cloudflare monitoring, DNS drift
  detection, gateway watchdogs, model-health and failover tracking.
- **CRM & lead ops** — GoHighLevel contact loading, contact-form intake with
  webhook + notification fan-out.
- **Content pipelines** — TikTok idea backlog, Pinterest posting, brand and
  competitor monitoring, avatar-video generation.

Every script reads its credentials from environment variables — there are no
secrets in this repo, by design and by gate.

## MCP server (`mcp/vault-mcp`)

A custom [Model Context Protocol](https://modelcontextprotocol.io) server that
gives agents authenticated access to a shared knowledge vault, including RFC
7591 dynamic client registration and OAuth.

## How this repo stays clean

```
~/.openclaw  ──(private, everything: secrets, sessions, browser state)
     │
     └──(tools/export-from-openclaw.sh: allowlist + redact + gitleaks gate)──▶  this repo (public)
```

The public repo is never auto-synced. It updates only when the export script is
run by hand and passes the secret scan. That is the whole point: the failure
mode of "accidentally publish a credential" is designed out.

## Tech

Python · Node.js · Bash · OpenClaw agent gateway · Model Context Protocol ·
Cloudflare / GA4 / GSC / GoHighLevel / TikTok / Pinterest APIs · launchd
scheduling on macOS.

---

Built by Chris Kaneshiro. This is a portfolio snapshot; the live system is
private.
