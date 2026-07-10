#!/usr/bin/env bash
# health-watchdog.sh — Zero-token system health check (runs via launchd every 6h)
# Checks: gateway alive, Gmail watch active, Telegram reachable
# Silent on success, alerts on failure
set -uo pipefail

source ~/.openclaw/.env

NOTIFY="$HOME/.openclaw/scripts/notify-telegram.sh"
LOG="$HOME/.openclaw/logs/watchdog.log"
FAILURES=""

log() { echo "$(date -Iseconds) $1" >> "$LOG"; }

# --- Check 1: Gateway process alive ---
if pgrep -f "openclaw" > /dev/null 2>&1; then
  log "OK: gateway process alive"
else
  FAILURES="${FAILURES}• Gateway process not found\n"
  log "FAIL: gateway process not found"
fi

# --- Check 2: Gateway port responding ---
if curl -s --max-time 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:18789/" 2>/dev/null | grep -qE "^[234]"; then
  log "OK: gateway port 18789 responding"
else
  FAILURES="${FAILURES}• Gateway port 18789 not responding\n"
  log "FAIL: gateway port 18789 not responding"
fi

# --- Check 3: Gmail watch status (uses google_auth.py, not gog CLI) ---
VENV_PYTHON="$HOME/.openclaw/venv/google/bin/python3"
WATCH_SCRIPT="$HOME/.openclaw/scripts/gmail_watch_check.py"

if [[ -x "$VENV_PYTHON" && -f "$WATCH_SCRIPT" ]]; then
  WATCH_OUT=$("$VENV_PYTHON" "$WATCH_SCRIPT" 2>&1)
  WATCH_EXIT=$?
  if [ $WATCH_EXIT -ne 0 ]; then
    # Parse failures from stderr lines
    while IFS= read -r line; do
      if [[ "$line" == FAIL:* ]]; then
        FAILURES="${FAILURES}• Gmail watch ${line#FAIL: }\n"
        log "FAIL: Gmail watch ${line#FAIL: }"
      fi
    done <<< "$WATCH_OUT"
    # If no FAIL lines parsed, include raw output
    if ! echo "$WATCH_OUT" | grep -q "^FAIL:"; then
      FAILURES="${FAILURES}• Gmail watch check failed: ${WATCH_OUT}\n"
      log "FAIL: Gmail watch check: $WATCH_OUT"
    fi
  else
    log "OK: Gmail watches active"
  fi
else
  log "SKIP: gmail_watch_check.py or venv not found, skipping Gmail watch checks"
fi

# --- Check 4: Telegram bot reachable ---
if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  TG_RESPONSE=$(curl -s --max-time 10 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>&1)
  if echo "$TG_RESPONSE" | grep -q '"ok":true'; then
    log "OK: Telegram bot reachable"
  else
    FAILURES="${FAILURES}• Telegram bot unreachable or token invalid\n"
    log "FAIL: Telegram bot check failed: $TG_RESPONSE"
  fi
else
  FAILURES="${FAILURES}• TELEGRAM_BOT_TOKEN not set in .env\n"
  log "FAIL: TELEGRAM_BOT_TOKEN not set"
fi

# --- Report ---
if [[ -n "$FAILURES" ]]; then
  log "ALERT: sending failure report"
  # Try notify script first, fall back to direct curl if Telegram itself is the issue
  ALERT_MSG="🔴 Watchdog Alert — $(date +%Y-%m-%d\ %H:%M)

System health check failed:
$(echo -e "$FAILURES")
Run health-watchdog.sh manually to recheck."

  "$NOTIFY" "$ALERT_MSG" 2>/dev/null || \
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="${TELEGRAM_CHAT_ID:-SHOWCASE_TELEGRAM_CHAT_ID}" \
      -d text="$ALERT_MSG" > /dev/null 2>&1 || \
    log "CRITICAL: could not send alert via any method"
else
  log "ALL OK"
fi
