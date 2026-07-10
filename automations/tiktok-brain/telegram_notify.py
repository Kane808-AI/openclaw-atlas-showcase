#!/usr/bin/env python3
"""Send a Telegram message via the Atlas bot.

Bot token read from ~/.openclaw/secrets/telegram-bot-token. Raises on any
non-200 response. Used by the ingestion pipeline to notify Chris when the
ElevenLabs URL path fails and a manual video upload is needed.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TOKEN_PATH = os.path.expanduser("~/.openclaw/secrets/telegram-bot-token")


class TelegramNotifyError(Exception):
    pass


def _read_token() -> str:
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return f.read().strip()


def send(chat_id: int, text: str, timeout: int = 15) -> None:
    token = _read_token()
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise TelegramNotifyError(f"HTTP {e.code}: {err}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise TelegramNotifyError(f"Network error: {e}") from None

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        raise TelegramNotifyError(f"Non-JSON response: {e}") from None
    if not data.get("ok"):
        raise TelegramNotifyError(f"Telegram API error: {data}")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: telegram_notify.py <chat_id> <text>", file=sys.stderr)
        return 1
    try:
        send(int(sys.argv[1]), sys.argv[2])
        return 0
    except (TelegramNotifyError, ValueError) as e:
        print(f"Telegram notify failed: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
