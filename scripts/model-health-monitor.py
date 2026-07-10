#!/usr/bin/env python3
"""
model-health-monitor.py

Probes LLM provider APIs directly and maintains a health score per model.
Automatically switches agents.defaults.model.primary via `openclaw config set`
when the current primary degrades below a threshold.

Handles the two failure modes OpenClaw does NOT auto-failover on:
  - HTTP 503 (Groq overloaded / capacity)
  - HTTP 400 (billing block / quota exhausted)

Runs every 20 minutes via LaunchAgent: ai.openclaw.model-health.plist
"""

import json
import os
import re
import shlex
import subprocess
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME = Path.home()
OPENCLAW_DIR = HOME / ".openclaw"
ENV_FILE = OPENCLAW_DIR / ".env"
OPENCLAW_JSON = OPENCLAW_DIR / "openclaw.json"
GATEWAY_ERR_LOG = OPENCLAW_DIR / "logs" / "gateway.err.log"
STATE_FILE = OPENCLAW_DIR / "logs" / "model-health-state.json"
LOG_FILE = OPENCLAW_DIR / "logs" / "model-health.log"
SWITCH_LOG = OPENCLAW_DIR / "logs" / "model-switches.log"
NOTIFY_SCRIPT = OPENCLAW_DIR / "scripts" / "notify-telegram.sh"
OPENCLAW_BIN = HOME / ".nvm" / "versions" / "node" / "v22.22.0" / "bin" / "openclaw"

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
SWITCH_THRESHOLD = 45       # Switch primary if score drops below this
RECOVERY_THRESHOLD = 75     # Restore original primary if score exceeds this
MIN_HEALTHY_PROBES = 2      # Consecutive successes before restoring original
PROBE_TIMEOUT_S = 60        # Seconds before a probe is marked as timed out (DeepSeek on NVIDIA can be slow)
MAX_HISTORY = 10            # Probe history entries to keep per model

# Score deltas per event type
SCORE_SUCCESS = +5
SCORE_SLOW = -10            # Response > 8 000 ms
SCORE_VERY_SLOW = -20       # Response > 15 000 ms
SCORE_TIMEOUT = -15
SCORE_RATE_LIMIT = -20      # HTTP 429
SCORE_OVERLOAD = -30        # HTTP 503 — not handled by OpenClaw
SCORE_BILLING_BLOCK = -50   # HTTP 400 billing / quota — not handled by OpenClaw
SCORE_AUTH_ERROR = -40      # HTTP 401 / 403
SCORE_SERVER_ERROR = -15    # Other 5xx

# ---------------------------------------------------------------------------
# Model roster
# Models not listed here are not actively probed (but may still be in fallback chain).
# max_score caps the model's health ceiling — lower cap = last resort even when healthy.
# ---------------------------------------------------------------------------
MODELS = {
    "deepseek/deepseek-chat": {
        "api": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "model_id": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "max_score": 100,
        "initial_score": 80,
    },
    "google/gemini-2.5-flash": {
        "api": "google",
        "model_id": "gemini-2.5-flash",
        "env_key": "GOOGLE_API_KEY",
        "max_score": 100,
        "initial_score": 80,
    },
    "xai/grok-4-1-fast": {
        "api": "openai_compat",
        "base_url": "https://api.x.ai/v1",
        "model_id": "grok-4-1-fast",
        "env_key": "XAI_API_KEY",
        "max_score": 100,
        "initial_score": 75,
    },
    "groq/llama-3.3-70b-versatile": {
        "api": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1",
        "model_id": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        # Capped at 55: known tool-call hallucination issues, emergency use only
        "max_score": 55,
        "initial_score": 40,
    },
    # OAuth-only via codex extension; no HTTP probe possible.
    # Health is inferred from gateway.err.log scan for recent `model=gpt-5.5 isError=true`.
    "openai-codex/gpt-5.5": {
        "api": "log_scan",
        "model_id": "gpt-5.5",
        "max_score": 100,
        "initial_score": 80,
    },
}

# Ordered preference for primary model selection.
# First model in this list with score >= SWITCH_THRESHOLD wins.
PREFERRED_PRIMARY_ORDER = [
    "openai-codex/gpt-5.5",
    "deepseek/deepseek-chat",
    "xai/grok-4-1-fast",
    "google/gemini-2.5-flash",
    "groq/llama-3.3-70b-versatile",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def load_env() -> dict:
    """Parse ~/.openclaw/.env into a dict (no shell sourcing needed)."""
    env = {}
    if not ENV_FILE.exists():
        return env
    for raw in ENV_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_openclaw_config() -> dict:
    return json.loads(OPENCLAW_JSON.read_text())


def get_config_primary(config: dict) -> str:
    return config["agents"]["defaults"]["model"]["primary"]


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "version": 1,
        "originalPrimary": None,
        "currentPrimary": None,
        "switchedAt": None,
        "switchReason": None,
        "models": {},
    }


def save_state(state: dict):
    state["lastUpdated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_score(state: dict, model_id: str) -> float:
    model_cfg = MODELS.get(model_id, {})
    max_s = model_cfg.get("max_score", 100)
    default = min(model_cfg.get("initial_score", 70), max_s)
    if model_id not in state["models"]:
        return float(default)
    return float(state["models"][model_id].get("score", default))


def record_probe(state: dict, model_id: str, delta: float, result: dict):
    model_cfg = MODELS.get(model_id, {})
    max_s = float(model_cfg.get("max_score", 100))
    initial = float(min(model_cfg.get("initial_score", 70), max_s))

    if model_id not in state["models"]:
        state["models"][model_id] = {
            "score": initial,
            "consecutiveSuccesses": 0,
            "consecutiveFailures": 0,
            "lastProbe": None,
            "lastError": None,
            "lastErrorCode": None,
            "history": [],
        }

    m = state["models"][model_id]
    old_score = float(m.get("score", initial))
    m["score"] = round(max(0.0, min(max_s, old_score + delta)), 1)
    m["lastProbe"] = datetime.now(timezone.utc).isoformat()

    if result.get("success"):
        m["consecutiveSuccesses"] = m.get("consecutiveSuccesses", 0) + 1
        m["consecutiveFailures"] = 0
        m["lastError"] = None
        m["lastErrorCode"] = None
    else:
        m["consecutiveFailures"] = m.get("consecutiveFailures", 0) + 1
        m["consecutiveSuccesses"] = 0
        m["lastError"] = result.get("error", "")[:200]
        m["lastErrorCode"] = result.get("status_code")

    history_entry = {
        "ts": m["lastProbe"],
        "success": result.get("success", False),
        "latency_ms": result.get("latency_ms"),
        "status_code": result.get("status_code"),
        "error": (result.get("error") or "")[:100],
    }
    m["history"] = (m.get("history", []) + [history_entry])[-MAX_HISTORY:]


# ---------------------------------------------------------------------------
# Model probing
# ---------------------------------------------------------------------------

def probe_google(model_id: str, api_key: str) -> dict:
    """Minimal probe against Google Generative Language API."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta"
        f"/models/{model_id}:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": "Reply with exactly one word: PONG"}]}],
        "generationConfig": {"maxOutputTokens": 10, "temperature": 0},
    }
    start = time.monotonic()
    try:
        resp = requests.post(
            url, json=body, params={"key": api_key}, timeout=PROBE_TIMEOUT_S
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            return {"success": True, "latency_ms": latency_ms, "status_code": 200}
        err_msg = ""
        try:
            err_msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            err_msg = resp.text[:200]
        return {
            "success": False,
            "latency_ms": latency_ms,
            "status_code": resp.status_code,
            "error": err_msg,
        }
    except requests.Timeout:
        return {
            "success": False,
            "latency_ms": PROBE_TIMEOUT_S * 1000,
            "status_code": None,
            "error": "timeout",
        }
    except Exception as exc:
        return {"success": False, "latency_ms": None, "status_code": None, "error": str(exc)}


def probe_openai_compat(base_url: str, model_id: str, api_key: str) -> dict:
    """Minimal probe against any OpenAI-compatible API (xAI, Groq, etc.)."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with exactly one word: PONG"}],
        "max_tokens": 10,
        "temperature": 0,
    }
    start = time.monotonic()
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=PROBE_TIMEOUT_S)
        latency_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            return {"success": True, "latency_ms": latency_ms, "status_code": 200}
        err_msg = ""
        try:
            data = resp.json()
            err_msg = (data.get("error") or {}).get("message", "") or str(data)[:200]
        except Exception:
            err_msg = resp.text[:200]
        return {
            "success": False,
            "latency_ms": latency_ms,
            "status_code": resp.status_code,
            "error": err_msg,
        }
    except requests.Timeout:
        return {
            "success": False,
            "latency_ms": PROBE_TIMEOUT_S * 1000,
            "status_code": None,
            "error": "timeout",
        }
    except Exception as exc:
        return {"success": False, "latency_ms": None, "status_code": None, "error": str(exc)}


def probe_log_scan(model_id: str, window_minutes: int = 25) -> dict:
    """Infer health from gateway.err.log scan.

    Used for models that can't be probed via HTTP (e.g., codex OAuth-only).
    Counts `model=<model_id>` lines with `isError=true` vs total in the recent window.
    Returns synthetic-200 on no failures, synthetic-500 with error detail on failures.
    """
    if not GATEWAY_ERR_LOG.exists():
        return {"success": True, "latency_ms": 0, "status_code": 200, "error": "no log yet"}
    cutoff = time.time() - window_minutes * 60
    # Fields appear in arbitrary order in log lines; match independently.
    pattern_model = re.compile(rf'model={re.escape(model_id)}\b')
    pattern_iserr = re.compile(r'isError=true\b')
    pattern_err_detail = re.compile(r'error=(\{.*?\})')
    ts_re = re.compile(r'^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})')
    errors = []
    total = 0
    try:
        # Read last ~2MB to bound work
        size = GATEWAY_ERR_LOG.stat().st_size
        with open(GATEWAY_ERR_LOG, "rb") as f:
            if size > 2_000_000:
                f.seek(size - 2_000_000)
                f.readline()  # discard partial
            for raw in f:
                line = raw.decode("utf-8", errors="ignore")
                m = ts_re.match(line)
                if m:
                    try:
                        line_ts = datetime.fromisoformat(m.group(1)).timestamp()
                        if line_ts < cutoff:
                            continue
                    except Exception:
                        pass
                if not pattern_model.search(line):
                    continue
                total += 1
                if pattern_iserr.search(line):
                    detail = pattern_err_detail.search(line)
                    errors.append(detail.group(1)[:120] if detail else "unknown error")
    except Exception as exc:
        return {"success": False, "latency_ms": None, "status_code": None, "error": f"log scan failed: {exc}"}
    if not errors:
        return {"success": True, "latency_ms": 0, "status_code": 200}
    # Treat repeated identical errors as one root cause; key off the first
    return {
        "success": False,
        "latency_ms": 0,
        "status_code": 500,
        "error": f"{len(errors)}/{total} calls failed: {errors[0]}",
    }


def probe_model(model_key: str, env: dict) -> Optional[dict]:
    """Dispatch probe based on model config. Returns None if API key missing."""
    cfg = MODELS.get(model_key)
    if not cfg:
        return None
    if cfg["api"] == "log_scan":
        return probe_log_scan(cfg["model_id"])
    api_key = env.get(cfg["env_key"])
    if not api_key:
        log.warning(f"  {model_key}: SKIP (no {cfg['env_key']} in .env)")
        return None
    if cfg["api"] == "google":
        return probe_google(cfg["model_id"], api_key)
    if cfg["api"] == "openai_compat":
        return probe_openai_compat(cfg["base_url"], cfg["model_id"], api_key)
    return None


def score_delta(result: dict) -> float:
    """Compute score delta from a probe result."""
    if result.get("success"):
        ms = result.get("latency_ms") or 0
        if ms > 15_000:
            return SCORE_VERY_SLOW
        if ms > 8_000:
            return SCORE_SLOW
        return SCORE_SUCCESS

    code = result.get("status_code")
    err = (result.get("error") or "").lower()

    if code == 429 or "rate limit" in err or "rate_limit" in err:
        return SCORE_RATE_LIMIT
    if code == 503 or "overload" in err or "capacity" in err or "unavailable" in err:
        return SCORE_OVERLOAD
    if code == 400 and any(w in err for w in ("billing", "quota", "payment", "insufficient")):
        return SCORE_BILLING_BLOCK
    if code in (401, 403):
        return SCORE_AUTH_ERROR
    if "timeout" in err:
        return SCORE_TIMEOUT
    if code and code >= 500:
        return SCORE_SERVER_ERROR
    return SCORE_TIMEOUT  # Unknown failure — penalize conservatively


# ---------------------------------------------------------------------------
# Gateway error log parsing
# ---------------------------------------------------------------------------

def parse_gateway_errors_for_model(model_key: str, window_minutes: int = 30) -> list:
    """
    Scan gateway.err.log for recent error lines referencing the given model.
    Catches HTTP 400 / 503 errors that OpenClaw treats as terminal (no auto-failover).
    Returns list of {status_code, line} dicts.
    """
    results = []
    if not GATEWAY_ERR_LOG.exists():
        return results

    # Match on the model slug (e.g. "gemini-2.5-flash") or provider ("google")
    parts = model_key.split("/")
    model_slug = parts[-1]
    provider = parts[0]
    cutoff = time.time() - (window_minutes * 60)

    try:
        with open(GATEWAY_ERR_LOG, "r", errors="replace") as fh:
            for line in fh:
                if model_slug not in line and provider not in line:
                    continue
                if "isError=true" not in line and "statusCode=" not in line:
                    continue

                # Parse timestamp from line
                ts_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
                if ts_match:
                    try:
                        ts = datetime.fromisoformat(ts_match.group(1)).replace(
                            tzinfo=timezone.utc
                        )
                        if ts.timestamp() < cutoff:
                            continue
                    except Exception:
                        pass

                sc_match = re.search(r"statusCode=(\d+)", line)
                status_code = int(sc_match.group(1)) if sc_match else None
                results.append({"status_code": status_code, "line": line.strip()[:300]})
    except Exception as exc:
        log.warning(f"Gateway log parse error: {exc}")

    return results


# ---------------------------------------------------------------------------
# Switching
# ---------------------------------------------------------------------------

def openclaw_set_primary(model: str) -> bool:
    """Call `openclaw config set agents.defaults.model.primary <model>` via CLI."""
    try:
        result = subprocess.run(
            [
                str(OPENCLAW_BIN),
                "config",
                "set",
                "agents.defaults.model.primary",
                model,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "HOME": str(HOME)},
        )
        if result.returncode == 0:
            return True
        log.error(
            f"openclaw config set failed (rc={result.returncode}): "
            f"{result.stderr.strip()[:300]}"
        )
        return False
    except Exception as exc:
        log.error(f"openclaw config set exception: {exc}")
        return False


def notify(message: str):
    """Fire-and-forget Telegram notification."""
    try:
        subprocess.run(
            [str(NOTIFY_SCRIPT), message],
            timeout=15,
            capture_output=True,
        )
    except Exception as exc:
        log.warning(f"Telegram notify failed: {exc}")


def select_best_primary(state: dict, exclude: list) -> Optional[str]:
    """
    Return the highest-scoring model from PREFERRED_PRIMARY_ORDER
    that is above SWITCH_THRESHOLD and not in the exclude list.
    """
    best_model = None
    best_score = -1.0
    for model_id in PREFERRED_PRIMARY_ORDER:
        if model_id in exclude:
            continue
        s = get_score(state, model_id)
        if s > best_score:
            best_score = s
            best_model = model_id
    if best_model and best_score >= SWITCH_THRESHOLD:
        return best_model
    return None


def do_switch(
    old_primary: str,
    new_primary: str,
    reason: str,
    state: dict,
) -> bool:
    """Execute a model switch: update config, update state, log, notify."""
    log.info(f"SWITCH {old_primary} -> {new_primary} | {reason}")

    if not openclaw_set_primary(new_primary):
        log.error("Config set failed — aborting switch")
        return False

    state["currentPrimary"] = new_primary
    state["switchedAt"] = datetime.now(timezone.utc).isoformat()
    state["switchReason"] = reason

    # Append to switch log
    entry = {
        "ts": state["switchedAt"],
        "from": old_primary,
        "to": new_primary,
        "reason": reason,
        "scores": {m: get_score(state, m) for m in PREFERRED_PRIMARY_ORDER},
    }
    with open(SWITCH_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")

    # Build score summary for notification
    score_lines = "\n".join(
        f"  {m.split('/')[-1]}: {get_score(state, m):.0f}"
        for m in PREFERRED_PRIMARY_ORDER
    )
    notify(
        f"Model Switch\n\n"
        f"From: {old_primary}\n"
        f"To: {new_primary}\n"
        f"Reason: {reason}\n\n"
        f"Health scores:\n{score_lines}"
    )
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("=== model-health-monitor start ===")

    env = load_env()
    config = load_openclaw_config()
    state = load_state()

    config_primary = get_config_primary(config)

    # Sync state to what's actually in config (handles out-of-band changes)
    if state.get("currentPrimary") != config_primary:
        log.info(f"State/config drift — syncing currentPrimary to {config_primary}")
        state["currentPrimary"] = config_primary
    if state.get("originalPrimary") is None:
        state["originalPrimary"] = config_primary

    current_primary = state["currentPrimary"]
    log.info(f"Current primary: {current_primary}")

    # -----------------------------------------------------------------------
    # Phase 1: Probe all monitored models
    # -----------------------------------------------------------------------
    for model_id in MODELS:
        result = probe_model(model_id, env)
        if result is None:
            continue

        delta = score_delta(result)
        record_probe(state, model_id, delta, result)
        score = get_score(state, model_id)

        if result["success"]:
            latency = result.get("latency_ms", 0)
            log.info(
                f"  {model_id}: OK {latency}ms | score={score:.0f} ({delta:+.0f})"
            )
        else:
            log.info(
                f"  {model_id}: FAIL "
                f"http={result.get('status_code', 'timeout')} "
                f"err={result.get('error', '')[:80]} | "
                f"score={score:.0f} ({delta:+.0f})"
            )

    # -----------------------------------------------------------------------
    # Phase 2: Parse gateway error log for unhandled failure codes
    # HTTP 400 and 503 from the current primary do NOT trigger OpenClaw failover,
    # so we detect them here and penalize the primary's health score.
    # -----------------------------------------------------------------------
    gateway_errors = parse_gateway_errors_for_model(current_primary, window_minutes=30)
    if gateway_errors:
        log.info(
            f"Gateway log: {len(gateway_errors)} error line(s) for "
            f"{current_primary} in last 30m"
        )
    for err in gateway_errors:
        code = err.get("status_code")
        if code == 503:
            record_probe(
                state,
                current_primary,
                SCORE_OVERLOAD,
                {
                    "success": False,
                    "status_code": 503,
                    "error": f"gateway_log:{err['line'][:80]}",
                },
            )
            log.info(f"  Gateway penalty: 503 overload ({SCORE_OVERLOAD:+.0f})")
        elif code == 400:
            record_probe(
                state,
                current_primary,
                SCORE_BILLING_BLOCK,
                {
                    "success": False,
                    "status_code": 400,
                    "error": f"gateway_log:{err['line'][:80]}",
                },
            )
            log.info(f"  Gateway penalty: 400 billing block ({SCORE_BILLING_BLOCK:+.0f})")

    # -----------------------------------------------------------------------
    # Phase 3: Switch decision
    # -----------------------------------------------------------------------
    primary_score = get_score(state, current_primary)
    log.info(f"Primary score: {current_primary} = {primary_score:.0f}")

    if primary_score < SWITCH_THRESHOLD:
        # Primary is unhealthy — find best alternative
        best = select_best_primary(state, exclude=[current_primary])
        if best:
            best_score = get_score(state, best)
            reason = (
                f"primary {current_primary.split('/')[-1]} score "
                f"{primary_score:.0f} < threshold {SWITCH_THRESHOLD}; "
                f"{best.split('/')[-1]} score={best_score:.0f}"
            )
            do_switch(current_primary, best, reason, state)
        else:
            # No healthy alternative — alert but don't switch
            log.warning("All models below threshold — no safe swap, alerting only")
            notify(
                f"Model Health Alert\n\n"
                f"Primary ({current_primary.split('/')[-1]}) score: "
                f"{primary_score:.0f}\n"
                f"No healthy alternative above threshold. Manual fix needed."
            )

    elif (
        state.get("switchedAt") is not None
        and current_primary != state.get("originalPrimary")
    ):
        # We're currently on a fallback — check if original has recovered
        original = state["originalPrimary"]
        orig_score = get_score(state, original)
        orig_consecutive = state["models"].get(original, {}).get("consecutiveSuccesses", 0)

        log.info(
            f"On fallback. Original ({original}) score={orig_score:.0f}, "
            f"consecutive successes={orig_consecutive}"
        )

        if orig_score >= RECOVERY_THRESHOLD and orig_consecutive >= MIN_HEALTHY_PROBES:
            reason = (
                f"original primary {original.split('/')[-1]} recovered "
                f"(score={orig_score:.0f}, {orig_consecutive} consecutive OK)"
            )
            if do_switch(current_primary, original, reason, state):
                state["switchedAt"] = None
                state["switchReason"] = None
    else:
        log.info("Primary healthy — no switch needed")

    save_state(state)
    log.info("=== model-health-monitor done ===")


if __name__ == "__main__":
    main()
