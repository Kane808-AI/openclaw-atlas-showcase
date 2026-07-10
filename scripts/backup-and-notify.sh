#!/usr/bin/env bash
# backup-and-notify.sh — Run workspace backup, notify Telegram on result
set -uo pipefail

NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"
SNAPSHOT="$HOME/.openclaw/workspace/backups/snapshot.sh"
LOG="$HOME/.openclaw/logs/backup.log"

echo "$(date -Iseconds) Starting backup" >> "$LOG"

if OUTPUT=$("$SNAPSHOT" 2>&1); then
  echo "$(date -Iseconds) OK: $OUTPUT" >> "$LOG"
  "$NOTIFY" "📦 Backup complete: $OUTPUT"
else
  echo "$(date -Iseconds) FAIL: $OUTPUT" >> "$LOG"
  "$NOTIFY" "⚠️ Backup failed: $OUTPUT"
fi
