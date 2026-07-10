#!/usr/bin/env python3
"""Discord websocket stall watchdog.

Detects the silent Discord stall pattern documented in
`memory/project_discord_websocket_stall_2026_05_18.md` and auto-restarts
the OpenClaw gateway when it fires.

Trigger condition (ALL must hold):
  1. `gateway.log` contains a `[discord] gateway: Gateway websocket closed: 1006|1000`
     line within the lookback window (default 30 min).
  2. The most recent such close is older than STALL_GRACE_SECONDS (default 300s).
  3. No `[discord]` activity AFTER that close line in the log.
  4. No auto-restart has fired in the last RESTART_COOLDOWN_SECONDS (default 600s).

When it fires:
  - Runs `openclaw gateway restart`.
  - Telegram-pings Chris via `notify-telegram.sh`.
  - Appends a structured entry to ~/.openclaw/logs/discord-watchdog.log.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
GATEWAY_LOG = HOME / "Library" / "Logs" / "openclaw" / "gateway.log"
WATCHDOG_LOG = HOME / ".openclaw" / "logs" / "discord-watchdog.log"
STATE_FILE = HOME / ".openclaw" / "logs" / ".discord-watchdog-state.json"
NOTIFY_SCRIPT = HOME / ".openclaw" / "scripts" / "notify-telegram.sh"
OPENCLAW_BIN = HOME / ".nvm" / "versions" / "node" / "v22.22.0" / "bin" / "openclaw"

LOOKBACK_SECONDS = 30 * 60
STALL_GRACE_SECONDS = 5 * 60
RESTART_COOLDOWN_SECONDS = 10 * 60

# Matches lines like:
# 2026-05-19T12:48:58.578-07:00 [discord] gateway: Gateway websocket closed: 1006
CLOSE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})\s+"
    r"\[discord\]\s+gateway: Gateway websocket closed:\s+(?P<code>1006|1000)\b"
)
# Any [discord] line — used to detect post-close activity.
DISCORD_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})\s+\[discord\]"
)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


def read_recent_lines(path: Path, window_seconds: int) -> list[str]:
    """Return log lines whose timestamp falls within the lookback window."""
    if not path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    # Tail-friendly read — file is ~200KB typically, full read is fine.
    lines = path.read_text(errors="replace").splitlines()
    out = []
    for line in lines:
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})", line)
        if not m:
            continue
        try:
            ts = parse_ts(m.group(1)).astimezone(timezone.utc)
        except ValueError:
            continue
        if ts >= cutoff:
            out.append(line)
    return out


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def log_event(level: str, message: str, **extra) -> None:
    WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
        **extra,
    }
    with WATCHDOG_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def notify(message: str) -> None:
    if not NOTIFY_SCRIPT.exists():
        return
    try:
        subprocess.run(
            [str(NOTIFY_SCRIPT), message],
            timeout=15,
            check=False,
            capture_output=True,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log_event("warn", "telegram notify failed", error=str(e))


def restart_gateway() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [str(OPENCLAW_BIN), "gateway", "restart"],
            timeout=60,
            check=False,
            capture_output=True,
            text=True,
        )
    except (subprocess.SubprocessError, OSError) as e:
        return False, f"exception: {e}"
    ok = result.returncode == 0
    tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
    return ok, "\n".join(tail)


def detect_stall(lines: list[str]) -> tuple[datetime, str] | None:
    """Return (close_ts, close_code) if a stall is currently active, else None."""
    closes: list[tuple[datetime, str, int]] = []
    last_discord_idx = -1
    for idx, line in enumerate(lines):
        m = CLOSE_RE.match(line)
        if m:
            ts = parse_ts(m.group("ts")).astimezone(timezone.utc)
            closes.append((ts, m.group("code"), idx))
        elif DISCORD_RE.match(line):
            last_discord_idx = idx
    if not closes:
        return None
    # Use the most recent close.
    close_ts, code, close_idx = closes[-1]
    # If any [discord] line appears AFTER the close, Discord recovered.
    if last_discord_idx > close_idx:
        return None
    # Close must be older than the grace window to count as a stall.
    age = (datetime.now(timezone.utc) - close_ts).total_seconds()
    if age < STALL_GRACE_SECONDS:
        return None
    return close_ts, code


def main() -> int:
    lines = read_recent_lines(GATEWAY_LOG, LOOKBACK_SECONDS)
    stall = detect_stall(lines)
    if not stall:
        return 0

    close_ts, code = stall
    state = load_state()
    last_restart = state.get("last_restart_epoch", 0)
    now_epoch = int(time.time())
    if now_epoch - last_restart < RESTART_COOLDOWN_SECONDS:
        log_event(
            "skip",
            "stall detected but within cooldown",
            close_ts=close_ts.isoformat(),
            code=code,
            seconds_since_last_restart=now_epoch - last_restart,
        )
        return 0

    log_event(
        "fire",
        "discord stall detected — restarting gateway",
        close_ts=close_ts.isoformat(),
        code=code,
    )
    ok, tail = restart_gateway()
    state["last_restart_epoch"] = now_epoch
    state["last_restart_close_ts"] = close_ts.isoformat()
    state["last_restart_ok"] = ok
    save_state(state)

    age_min = (datetime.now(timezone.utc) - close_ts).total_seconds() / 60
    status = "✅ restarted" if ok else "❌ restart failed"
    notify(
        f"🤖 *Discord Watchdog* — {status}\n"
        f"Stall: websocket closed {code} {age_min:.1f}m ago, no recovery.\n"
        f"`{tail or '(no output)'}`"
    )
    log_event(
        "done",
        "restart command completed",
        ok=ok,
        tail=tail,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
