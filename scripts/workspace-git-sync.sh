#!/bin/bash
# workspace-git-sync.sh — fswatch-driven auto-commit/push for ~/.openclaw/workspace.
# Runs under launchd (ai.openclaw.workspace-sync). Handles EPIPE to avoid
# throttle-induced respawn loops when stdout/stderr pipes close.

set -uo pipefail
trap '' PIPE

WORKSPACE="$HOME/.openclaw/workspace"
GUARD="$HOME/.openclaw/scripts/workspace-push-guard.sh"
LOG="$HOME/.openclaw/logs/workspace-sync.log"
NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"
DEBOUNCE_SECONDS=120

mkdir -p "$(dirname "$LOG")"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG"
}

notify_fail() {
  [ -x "$NOTIFY" ] && "$NOTIFY" "$1" >/dev/null 2>&1 || true
}

push_if_changed() {
  cd "$WORKSPACE" || { log "FAIL: cannot cd $WORKSPACE"; return 1; }

  if ! "$GUARD"; then
    log "Push blocked by guard script"
    return 1
  fi

  # Secret-shaped file guard: refuse to stage anything that looks like a
  # credential. `git add -A` would otherwise pick up new files an upgrade,
  # plugin, or stray write deposited. Even with a private repo, we never
  # want secrets in history.
  local suspect
  suspect=$(git status --porcelain | awk '$1 ~ /^(A|\?\?|M)/ {print $2}' | \
    grep -iE '(\.env(\..*)?$|.*\.key$|.*\.pem$|secret|token|credential|auth\.json$|cookies?\.txt$|recovery-token)' || true)
  if [ -n "$suspect" ]; then
    log "BLOCKED: secret-shaped files present, refusing to stage:"
    echo "$suspect" | while read -r f; do log "  $f"; done
    notify_fail "🚨 workspace-sync blocked: secret-shaped files staged — check $LOG"
    return 1
  fi

  git add -A
  if git diff --cached --quiet; then
    log "No changes to commit"
    return 0
  fi

  local commit_msg="auto-sync: $(date '+%Y-%m-%d %H:%M:%S')"
  if ! git commit -m "$commit_msg" >> "$LOG" 2>&1; then
    log "Commit failed"
    return 1
  fi

  # Fetch only main and rebase explicitly onto origin/main. Using `git pull --rebase`
  # with the default refspec writes every remote branch into FETCH_HEAD; with multiple
  # entries present, `pull --rebase` can fail with "Cannot rebase onto multiple branches"
  # even though only one ref is marked for merge. Explicit fetch+rebase is immune.
  local fetch_ok=0 fetch_wait=2
  for attempt in 1 2 3 4; do
    if git fetch origin main >> "$LOG" 2>&1; then
      fetch_ok=1
      break
    fi
    log "Fetch attempt $attempt failed — retrying in ${fetch_wait}s"
    sleep "$fetch_wait"
    fetch_wait=$((fetch_wait * 2))
  done
  if [ "$fetch_ok" -eq 0 ]; then
    log "Fetch failed after 4 attempts — alerting"
    local fetch_tail
    fetch_tail=$(tail -5 "$LOG" | tr '\n' ' ')
    notify_fail "🚨 Workspace git fetch failed after 4 attempts. Last log: $fetch_tail Check $LOG"
    return 1
  fi
  if ! git rebase --autostash origin/main >> "$LOG" 2>&1; then
    log "Rebase failed — aborting and alerting"
    git rebase --abort >> "$LOG" 2>&1 || true
    notify_fail "🚨 Workspace rebase conflict. Resolve manually. Check $LOG"
    return 1
  fi

  if ! git push >> "$LOG" 2>&1; then
    log "Push failed — alerting"
    notify_fail "🚨 Workspace git push failed. Check $LOG"
    return 1
  fi

  log "Pushed successfully"
  return 0
}

log "workspace-git-sync starting"
push_if_changed

fswatch -o -l "$DEBOUNCE_SECONDS" \
  --exclude '\.git' \
  --exclude '\.obsidian/workspace\.json' \
  --exclude '\.obsidian/workspace-mobile\.json' \
  --exclude '\.DS_Store' \
  "$WORKSPACE" | while read -r _; do
  log "Change detected — debouncing"
  sleep 5
  push_if_changed
done
