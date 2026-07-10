#!/bin/bash
# workspace_watcher.sh — Watches ~/.openclaw/workspace/ for .md file changes
# and appends entries to CHANGELOG.md. Excludes CHANGELOG.md itself to avoid loops.

WORKSPACE="$HOME/.openclaw/workspace"
CHANGELOG="$WORKSPACE/logs/CHANGELOG.md"

fswatch -0 --include '\.md$' --exclude '.*' "$WORKSPACE" | while IFS= read -r -d '' file; do
  filename="$(basename "$file")"
  [[ "$filename" == "CHANGELOG.md" ]] && continue
  date_only="$(date '+%Y-%m-%d')"

  echo "| ${date_only} | ${filename} | Modified (detected by fswatch) | Auto-logged by workspace watcher |" >> "$CHANGELOG"
done
