#!/usr/bin/env bash
# git-sync.sh — Nightly auto commit + push for OpenClaw repos
# Iterates over both ~/.openclaw (openclaw-atlas) and ~/.openclaw/workspace
# (openclaw-workspace). Skips a repo when its working tree is clean and
# it has nothing to push. Telegram notify only on failure.
set -uo pipefail

REPOS=(
  "$HOME/.openclaw"
  "$HOME/.openclaw/workspace"
)

LOG="$HOME/.openclaw/logs/git-sync.log"
NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"
STAMP="$(date '+%Y-%m-%d %H:%M')"
ISO="$(date -Iseconds)"

log() { echo "$ISO $*" >> "$LOG"; }
notify_fail() { [ -x "$NOTIFY" ] && "$NOTIFY" "⚠️ git-sync failed: $*"; }

sync_repo() {
  local repo="$1"
  local name
  name="$(basename "$repo")"
  [ "$name" = ".openclaw" ] && name="openclaw-atlas"

  if [ ! -d "$repo/.git" ]; then
    log "SKIP [$name]: $repo is not a git repo"
    return 0
  fi

  cd "$repo" || { log "FAIL [$name]: cannot cd $repo"; notify_fail "$name: cannot cd"; return 1; }

  local branch
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || {
    log "FAIL [$name]: not a git repo"
    notify_fail "$name: not a git repo"
    return 1
  }

  local needs_push=0
  if [ -z "$(git status --porcelain)" ]; then
    # Clean tree — still push if we're ahead of origin.
    if git rev-parse "@{u}" >/dev/null 2>&1; then
      local ahead
      ahead="$(git rev-list --count "@{u}..HEAD" 2>/dev/null || echo 0)"
      if [ "$ahead" -gt 0 ]; then
        needs_push=1
        log "INFO [$name]: clean tree, $ahead commits ahead of origin — push only"
      else
        log "OK [$name]: clean working tree on $branch, no action"
        return 0
      fi
    else
      log "OK [$name]: clean working tree on $branch (no upstream), no action"
      return 0
    fi
  else
    git add -A 2>>"$LOG" || { log "FAIL [$name]: git add"; notify_fail "$name: git add"; return 1; }
    git commit -m "auto: $name sync $STAMP" 2>>"$LOG" || { log "FAIL [$name]: git commit"; notify_fail "$name: git commit"; return 1; }
    needs_push=1
  fi

  if [ "$needs_push" -eq 1 ]; then
    git push origin "$branch" 2>>"$LOG" || { log "FAIL [$name]: git push origin $branch"; notify_fail "$name: git push $branch"; return 1; }
    log "OK [$name]: pushed to origin/$branch"
  fi

  return 0
}

overall_status=0
for repo in "${REPOS[@]}"; do
  sync_repo "$repo" || overall_status=1
done

exit "$overall_status"
