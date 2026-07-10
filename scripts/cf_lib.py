"""Shared helpers for Cloudflare monitoring scripts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import requests

HOME = Path.home()
ENV_FILE = HOME / ".openclaw" / ".env"
NOTIFY = HOME / ".openclaw" / "scripts" / "notify-telegram.sh"
CONFIG = HOME / ".openclaw" / "config" / "cf_zones.json"
STATE_DIR = HOME / ".openclaw" / "state"
DNS_BASELINE = HOME / ".openclaw" / "config" / "cf_dns_baseline.json"
API = "https://api.cloudflare.com/client/v4"


def load_env(var: str) -> str:
    pat = re.compile(rf"^\s*{re.escape(var)}=(.*)$")
    for line in ENV_FILE.read_text().splitlines():
        m = pat.match(line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise RuntimeError(f"{var} missing in .env")


def load_zones() -> list[dict]:
    return json.loads(CONFIG.read_text())["zones"]


def cf_get(token: str, path: str, params: dict | None = None) -> dict:
    r = requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def cf_graphql(token: str, query: str, variables: dict) -> dict:
    r = requests.post(
        f"{API}/graphql",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def notify(msg: str) -> None:
    subprocess.run([str(NOTIFY), msg], check=False)


def state_path(name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / name


def write_last_run(name: str) -> None:
    state_path(f"{name}.last_run").write_text(str(int(time.time())))


def read_last_run(name: str) -> int | None:
    p = state_path(f"{name}.last_run")
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except Exception:
        return None


def load_dns_baseline() -> dict:
    if not DNS_BASELINE.exists():
        return {}
    return json.loads(DNS_BASELINE.read_text())


def save_dns_baseline(data: dict) -> None:
    DNS_BASELINE.parent.mkdir(parents=True, exist_ok=True)
    DNS_BASELINE.write_text(json.dumps(data, indent=2, sort_keys=True))
