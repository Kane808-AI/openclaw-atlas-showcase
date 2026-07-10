#!/bin/bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: handoff <slug> [summary]" >&2
  exit 1
fi

RAW_SLUG="$1"
SUMMARY="${2:-}"

SLUG=$(echo "$RAW_SLUG" \
  | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')

if [ -z "$SLUG" ]; then
  echo "Error: slug produced empty kebab-case string" >&2
  exit 1
fi

TS=$(date +"%Y-%m-%d-%H%M")
DATE_HUMAN=$(date +"%Y-%m-%d %H:%M %Z")

HANDOFF_DIR="$HOME/.openclaw/workspace/handoffs"
mkdir -p "$HANDOFF_DIR"

OUT="$HANDOFF_DIR/HANDOFF_${TS}-${SLUG}.md"

cat > "$OUT" <<EOF
# Handoff: ${RAW_SLUG}

- **Date:** ${DATE_HUMAN}
- **Session Source:** Claude Code

## Summary

${SUMMARY}

## State

_TODO: capture current state — what's done, what's in flight, where files live._

## Next Session

_TODO: what to pick up next, blockers, decisions pending._
EOF

echo "$OUT"
