#!/usr/bin/env bash
# Daily guard: alert if "## Critical Operational Rules" reappears in workspace/AGENTS.md.
# Was superseded by "## Rules" one-liners 2026-05-10 (see HANDOFF_2026-05-10-1840).

set -uo pipefail

AGENTS_MD="$HOME/.openclaw/workspace/AGENTS.md"
NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"

if grep -qE '^## Critical Operational Rules' "$AGENTS_MD"; then
  "$NOTIFY" "ALERT: '## Critical Operational Rules' reappeared in workspace/AGENTS.md. Superseded 2026-05-10 — investigate who re-added it."
fi
