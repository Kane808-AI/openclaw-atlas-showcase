#!/usr/bin/env bash
# error-log-check.sh — Check gateway.err.log for new errors since last check
# Sends Telegram alert only if errors found, otherwise silent
set -uo pipefail

NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"
ERR_LOG="$HOME/.openclaw/logs/gateway.err.log"
STATE_FILE="$HOME/.openclaw/logs/.error-check-last-ts"
LOG="$HOME/.openclaw/logs/error-check.log"

# Get last check timestamp (default: 24h ago)
if [[ -f "$STATE_FILE" ]]; then
  LAST_TS=$(cat "$STATE_FILE")
else
  LAST_TS=$(date -v-24H -Iseconds 2>/dev/null || date -d '24 hours ago' -Iseconds)
fi

echo "$(date -Iseconds) Checking for errors since $LAST_TS" >> "$LOG"

if [[ ! -f "$ERR_LOG" ]]; then
  echo "$(date -Iseconds) No error log found" >> "$LOG"
  date -Iseconds > "$STATE_FILE"
  exit 0
fi

# Find error/fail lines newer than last check (exclude secrets warnings and info lines)
ERRORS=$(grep -E '\[agent/embedded\].*isError=true|\[diagnostic\].*error=' "$ERR_LOG" \
  | while IFS= read -r line; do
      LINE_TS=$(echo "$line" | grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}')
      if [[ -n "$LINE_TS" && "$LINE_TS" > "$LAST_TS" ]]; then
        echo "$line"
      fi
    done)

# Update timestamp
date -Iseconds > "$STATE_FILE"

if [[ -z "$ERRORS" ]]; then
  echo "$(date -Iseconds) No new errors" >> "$LOG"
  exit 0
fi

ERROR_COUNT=$(echo "$ERRORS" | wc -l | tr -d ' ')

# Separate critical errors (all models exhausted) from warnings (successful failovers)
CRITICAL=$(echo "$ERRORS" | grep -E 'exhausted|all.*(failed|unavailable)|no.*fallback|FailoverError' | grep -v 'decision=fallback_model' || true)
CRITICAL_COUNT=0
if [[ -n "$CRITICAL" ]]; then
  CRITICAL_COUNT=$(echo "$CRITICAL" | wc -l | tr -d ' ')
fi
WARNING_COUNT=$((ERROR_COUNT - CRITICAL_COUNT))

echo "$(date -Iseconds) Found $ERROR_COUNT total ($CRITICAL_COUNT critical, $WARNING_COUNT warnings)" >> "$LOG"

if [[ "$CRITICAL_COUNT" -gt 0 ]]; then
  SUMMARY=$(echo "$CRITICAL" | head -5 | sed 's/^/  /')
  "$NOTIFY" "⚠️ Error Report — $(date +%Y-%m-%d)
${CRITICAL_COUNT} critical error(s), ${WARNING_COUNT} failover warning(s):

${SUMMARY}

Check gateway.err.log for full details."
elif [[ "$WARNING_COUNT" -gt 5 ]]; then
  "$NOTIFY" "⚠️ Warning — $(date +%Y-%m-%d)
${WARNING_COUNT} failover events (all recovered). Primary model may be rate-limited."
fi
