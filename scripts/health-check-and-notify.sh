#!/usr/bin/env bash
# health-check-and-notify.sh — Run Google API health check, notify on failure only, and include daily pollen count
set -uo pipefail

NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"
PYTHON="$HOME/.openclaw/venv/google/bin/python3"
SCRIPT="$HOME/.openclaw/scripts/google_health_check.py"
LOG="$HOME/.openclaw/logs/health-check.log"
POLLEN_SCRIPT="$HOME/.openclaw/workspace/scripts/get_pollen.py"

# --- Fetch Pollen Data ---
if POLLEN_OUTPUT=$(/opt/homebrew/bin/python3 "$POLLEN_SCRIPT" 2>&1); then
  POLLEN_MESSAGE="$POLLEN_OUTPUT"
else
  POLLEN_MESSAGE="Daily Pollen Count (Olympia, WA): unavailable
$POLLEN_OUTPUT"
fi

# --- Run Health Check ---
HEALTH_STATUS="✅ Google API Health: OK"
if OUTPUT=$("$PYTHON" "$SCRIPT" --save 2>&1); then
  echo "$(date -Iseconds) OK" >> "$LOG"
else
  echo "$(date -Iseconds) FAIL: $OUTPUT" >> "$LOG"
  HEALTH_STATUS="⚠️ Google API Health: FAILED
Details: $OUTPUT"
fi

# --- Send Combined Notification ---
FULL_MESSAGE="${POLLEN_MESSAGE}

${HEALTH_STATUS}"
"$NOTIFY" "$FULL_MESSAGE"
