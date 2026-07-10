#!/bin/bash
# workspace-push-guard.sh — Block workspace commits containing files >50MB.
# GitHub hard-rejects >100MB; we cut off well below that to leave headroom.
# Scope: only files git would actually stage — gitignored files (backups,
# caches, venvs) are excluded so they can't trip the guard.
# Exits 1 and fires a Telegram alert if any oversized git-relevant files exist.

set -uo pipefail

MAX_SIZE_MB=50
MAX_SIZE_BYTES=$((MAX_SIZE_MB * 1024 * 1024))
WORKSPACE="$HOME/.openclaw/workspace"
NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"

cd "$WORKSPACE" || exit 1

# Files git would stage on `git add -A`: modified tracked + untracked-not-ignored.
# -m = modified, -o = other (untracked), --exclude-standard = respect .gitignore.
CANDIDATES=$(git ls-files -mo --exclude-standard)

[ -z "$CANDIDATES" ] && exit 0

LARGE_FILES=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  [ -f "$f" ] || continue
  size=$(stat -f%z "$f" 2>/dev/null || echo 0)
  if [ "$size" -gt "$MAX_SIZE_BYTES" ]; then
    LARGE_FILES="${LARGE_FILES}${f} ($(( size / 1024 / 1024 ))MB)
"
  fi
done <<< "$CANDIDATES"

if [ -n "$LARGE_FILES" ]; then
  MSG="🚨 Workspace push blocked — files over ${MAX_SIZE_MB}MB would be staged:
$LARGE_FILES"
  if [ -x "$NOTIFY" ]; then
    "$NOTIFY" "$MSG" >/dev/null 2>&1 || echo "$MSG" >&2
  else
    echo "$MSG" >&2
  fi
  exit 1
fi

exit 0
