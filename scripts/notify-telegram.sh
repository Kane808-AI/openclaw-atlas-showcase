#!/usr/bin/env bash
# notify-telegram.sh — Send a message to Chris via Telegram bot API
# Usage: notify-telegram.sh "message text"
#
# Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env via targeted
# grep — does NOT `source` the whole file. Sourcing was fragile because
# .env contains unquoted paths with spaces that shell-parse incorrectly.

set -uo pipefail

ENV_FILE="$HOME/.openclaw/.env"

# Extract VALUE from a VAR=VALUE line in .env.
# Skips commented lines, ignores leading whitespace, strips surrounding
# matched quotes. Returns 1 if the var is not present.
read_env_var() {
  local key="$1"
  local line value
  line=$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null | head -1) || true
  [ -z "$line" ] && return 1
  value="${line#*=}"
  # Strip matching surrounding quotes (double or single)
  if [[ "$value" == \"*\" ]]; then
    value="${value#\"}"; value="${value%\"}"
  elif [[ "$value" == \'*\' ]]; then
    value="${value#\'}"; value="${value%\'}"
  fi
  # Strip trailing carriage return (CRLF-safe)
  value="${value%$'\r'}"
  printf '%s' "$value"
}

if [ ! -r "$ENV_FILE" ]; then
  echo "ERROR: cannot read $ENV_FILE" >&2
  exit 1
fi

TELEGRAM_BOT_TOKEN=$(read_env_var "TELEGRAM_BOT_TOKEN" || true)
TELEGRAM_CHAT_ID=$(read_env_var "TELEGRAM_CHAT_ID" || true)

if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN not set in $ENV_FILE" >&2
  exit 1
fi

CHAT_ID="${TELEGRAM_CHAT_ID:-7556461717}"
MESSAGE="${1:?Usage: notify-telegram.sh \"message text\"}"

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="${CHAT_ID}" \
  -d text="${MESSAGE}" \
  -d parse_mode="Markdown" > /dev/null
