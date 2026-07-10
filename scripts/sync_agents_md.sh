#!/bin/bash
# sync_agents_md.sh — Propagates master ~/.openclaw/workspace/AGENTS.md
# to every sub-agent workspace defined in openclaw.json agents.list.
#
# Rules:
#   - Source of truth: ~/.openclaw/workspace/AGENTS.md (main / Atlas workspace root)
#   - Targets: each agent's `workspace` from openclaw.json agents.list
#   - Skips 'main' (its workspace IS the master location)
#   - Skips ~/.openclaw/workspace/codex/ (different lineage, intentionally left alone)
#   - Preserves any content between <!-- ROLE-SPECIFIC:START --> and
#     <!-- ROLE-SPECIFIC:END --> markers on the target side.
#   - Writes a .bak.<timestamp> before touching any diverged target with no markers.
#   - Triggered by launchd ai.openclaw.sync-agents-md on WatchPaths change.
#
# Idempotent: safe to run anytime.

set -euo pipefail

MASTER="$HOME/.openclaw/workspace/AGENTS.md"
CONFIG="$HOME/.openclaw/openclaw.json"
LOG="$HOME/.openclaw/logs/sync_agents_md.log"
TS="$(date '+%Y%m%d-%H%M%S')"
SKIP_PATHS=( "$HOME/.openclaw/workspace/codex" )

mkdir -p "$(dirname "$LOG")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

if [[ ! -f "$MASTER" ]]; then
  log "ERROR master missing: $MASTER"
  exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
  log "ERROR config missing: $CONFIG"
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  log "ERROR jq not found on PATH"
  exit 1
fi

MASTER_HASH="$(md5 -q "$MASTER")"
log "sync start — master hash=$MASTER_HASH"

# Extract every agent's `workspace` (skip `main` — has no workspace override, uses root).
# Using while-read for bash 3.2 compatibility (macOS default).
TARGETS=()
while IFS= read -r line; do
  [[ -n "$line" ]] && TARGETS+=("$line")
done < <(jq -r '.agents.list[] | select(.id != "main") | .workspace // empty' "$CONFIG")

for ws in "${TARGETS[@]}"; do
  # Skip opt-outs
  skip=0
  for s in "${SKIP_PATHS[@]}"; do
    if [[ "$ws" == "$s" ]]; then skip=1; break; fi
  done
  if [[ $skip -eq 1 ]]; then
    log "skip (opt-out): $ws"
    continue
  fi

  if [[ ! -d "$ws" ]]; then
    log "skip (missing dir): $ws"
    continue
  fi

  target="$ws/AGENTS.md"

  # Case A: target missing — write master verbatim.
  if [[ ! -f "$target" ]]; then
    cp "$MASTER" "$target"
    log "created: $target"
    continue
  fi

  target_hash="$(md5 -q "$target")"

  # Case B: already in sync — noop.
  if [[ "$target_hash" == "$MASTER_HASH" ]]; then
    continue
  fi

  # Case C: target has ROLE-SPECIFIC markers — preserve block, refresh master portion.
  if grep -q "<!-- ROLE-SPECIFIC:START -->" "$target" && grep -q "<!-- ROLE-SPECIFIC:END -->" "$target"; then
    role_block="$(awk '/<!-- ROLE-SPECIFIC:START -->/,/<!-- ROLE-SPECIFIC:END -->/' "$target")"
    tmp="$(mktemp)"
    cp "$MASTER" "$tmp"
    printf '\n\n%s\n' "$role_block" >> "$tmp"
    # Only replace target if the composed file actually changed vs current target.
    new_hash="$(md5 -q "$tmp")"
    if [[ "$new_hash" != "$target_hash" ]]; then
      cp "$target" "$target.bak.$TS"
      mv "$tmp" "$target"
      log "merged (preserved ROLE-SPECIFIC): $target (bak: $target.bak.$TS)"
    else
      rm -f "$tmp"
    fi
    continue
  fi

  # Case D: target has diverged with no markers — do NOT overwrite. Back up and log.
  cp "$target" "$target.bak.$TS"
  log "WARN diverged target with no ROLE-SPECIFIC markers — manual review needed: $target (bak: $target.bak.$TS)"
done

log "sync end"
