#!/usr/bin/env python3
"""Fiverr Thumbnail Server — local HTTP wrapper on port 18792.

n8n calls POST /generate with Fiverr order data.
Server generates a thumbnail via gen.py (Imagen 4), uploads to Drive
under "Fiverr Thumbnails/{order_id}", sends a Telegram notification,
and returns the Drive link.

Endpoints:
  GET  /health        -> {"status": "ok", "port": 18792}
  POST /generate      -> {status, order_id, drive_link, file_id, image_path, telegram_sent}
  POST /gmail-search  -> {"messages": [...]} — wraps gmail_tool.py so n8n can call
                         it via httpRequest instead of executeCommand

POST /generate body (JSON):
  {
    "order_id":     "FO1234567",         # Required — Fiverr order number or email ID
    "channel_name": "MrBeast",           # Optional — YouTube channel name
    "video_title":  "I Tried Everything",# Optional — video title
    "style":        "photo",             # Optional — gen.py style preset (default: photo)
    "engine":       "imagen",            # Optional — gemini|imagen (default: imagen)
    "aspect":       "16:9",              # Optional — aspect ratio (default: 16:9)
    "email_id":     "18f3a2b1c...",      # Optional — Gmail message ID for dedup
  }

Deduplication: processed order_ids are stored in
  ~/.openclaw/workspace/data/fiverr-processed-orders.json
Re-posting the same order_id returns {"status": "already_processed"} without regenerating.

Start:  python3 ~/.openclaw/scripts/fiverr_thumbnail_server.py
Stop:   launchctl stop ai.openclaw.fiverr-thumbnail
Health: curl http://127.0.0.1:18792/health
"""

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 18792

# Script paths — all relative to home so they survive username changes
_HOME = Path.home()
VENV_PYTHON    = _HOME / ".openclaw" / "venv" / "google" / "bin" / "python3"
GEN_SCRIPT     = _HOME / ".openclaw" / "workspace" / "skills" / "gemini-image-gen" / "scripts" / "gen.py"
DRIVE_SCRIPT   = _HOME / ".openclaw" / "scripts" / "google_drive_tool.py"
GMAIL_SCRIPT   = _HOME / ".openclaw" / "scripts" / "gmail_tool.py"
ENV_FILE       = _HOME / ".openclaw" / ".env"
PROCESSED_FILE = _HOME / ".openclaw" / "workspace" / "data" / "fiverr-processed-orders.json"
TMP_DIR        = _HOME / ".openclaw" / "tmp" / "thumbnails"
LOG_DIR        = _HOME / ".openclaw" / "logs"
LOG_FILE       = LOG_DIR / "fiverr-thumbnail-stdout.log"

DRIVE_PARENT_FOLDER = "Fiverr Thumbnails"

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}"
    print(line, flush=True)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _load_env() -> dict:
    """Parse ~/.openclaw/.env into a dict. Never raises."""
    env: dict = {}
    try:
        for raw in ENV_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return env


def _load_processed() -> set:
    try:
        data = json.loads(PROCESSED_FILE.read_text())
        return set(data.get("ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_processed(ids: set) -> None:
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text(json.dumps({"ids": sorted(ids)}, indent=2))


def _send_telegram(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as e:
        _log(f"Telegram send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def _build_prompt(channel_name: str, video_title: str) -> str:
    channel = channel_name.strip() if channel_name and channel_name not in ("Unknown", "") else ""
    if channel:
        return (
            f'YouTube thumbnail for a video titled "{video_title}" on the channel "{channel}". '
            "Eye-catching, high contrast, bold typography space, professional YouTube "
            "thumbnail aesthetic, vibrant colors, engaging composition."
        )
    return (
        f'YouTube thumbnail for a video titled "{video_title}". '
        "Eye-catching, high contrast, bold typography space, professional YouTube "
        "thumbnail aesthetic, vibrant colors, engaging composition."
    )


def _generate_thumbnail(
    prompt: str,
    order_id: str,
    engine: str,
    aspect: str,
    style: str,
) -> Path:
    """Run gen.py and return path to the first generated PNG."""
    out_dir = TMP_DIR / order_id
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(VENV_PYTHON), str(GEN_SCRIPT),
        "--prompt", prompt,
        "--engine", engine,
        "--count", "1",
        "--out-dir", str(out_dir),
    ]
    if aspect and aspect != "1:1":
        cmd.extend(["--aspect", aspect])
    if style and style not in ("none", ""):
        cmd.extend(["--style", style])

    # Inherit full environment so GEMINI_API_KEY passes through
    env = dict(os.environ)
    # Also inject from .env file for keys not already set
    for k, v in _load_env().items():
        env.setdefault(k, v)

    _log(f"gen.py: engine={engine} aspect={aspect} style={style}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=150
    )
    if result.returncode != 0:
        raise RuntimeError(f"gen.py failed (exit {result.returncode}): {result.stderr[:500]}")

    pngs = sorted(out_dir.glob("*.png"))
    if not pngs:
        raise RuntimeError(f"gen.py ran but no PNG found in {out_dir}")
    _log(f"Image generated: {pngs[0].name} ({pngs[0].stat().st_size // 1024}KB)")
    return pngs[0]


def _upload_to_drive(file_path: Path, order_id: str) -> dict:
    """Upload PNG to Drive under Fiverr Thumbnails/{order_id}. Returns {id, webViewLink}."""
    cmd = [
        str(VENV_PYTHON), str(DRIVE_SCRIPT),
        "upload", str(file_path),
        "--folder-name", order_id,
        "--parent-folder", DRIVE_PARENT_FOLDER,
    ]
    env = dict(os.environ)
    for k, v in _load_env().items():
        env.setdefault(k, v)

    _log(f"Uploading {file_path.name} to Drive: {DRIVE_PARENT_FOLDER}/{order_id}/")
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=90
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"google_drive_tool.py failed (exit {result.returncode}): {result.stderr[:500]}"
        )
    data = json.loads(result.stdout)
    if "error" in data:
        raise RuntimeError(f"Drive upload error: {data['error']}")
    _log(f"Drive upload OK: {data.get('webViewLink', 'no-link')}")
    return data


def _gmail_search(query: str, max_results: int, account: str) -> list:
    """Shell out to gmail_tool.py. Returns parsed JSON list (or raises)."""
    cmd = [
        str(VENV_PYTHON), str(GMAIL_SCRIPT),
        "--account", account,
        "--action", "search",
        "--query", query,
        "--max", str(max_results),
    ]
    env = dict(os.environ)
    for k, v in _load_env().items():
        env.setdefault(k, v)

    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"gmail_tool.py failed (exit {result.returncode}): {result.stderr[:300]}")
    data = json.loads(result.stdout)
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"gmail_tool.py error: {data['error']}")
    if not isinstance(data, list):
        raise RuntimeError(f"gmail_tool.py returned unexpected shape: {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class ThumbnailHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default stderr logging
        pass

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "port": PORT})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/generate", "/gmail-search"):
            self._send_json(404, {"error": "not found"})
            return

        try:
            data = json.loads(self._read_body())
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        if self.path == "/gmail-search":
            query = (data.get("query") or "").strip()
            if not query:
                self._send_json(400, {"error": "query required"})
                return
            max_results = int(data.get("max") or 20)
            account     = (data.get("account") or "brand75").strip()
            try:
                messages = _gmail_search(query, max_results, account)
                self._send_json(200, {"messages": messages, "count": len(messages)})
            except Exception as exc:
                _log(f"gmail-search error: {exc}")
                self._send_json(500, {"error": str(exc)})
            return

        order_id = (data.get("order_id") or "").strip()
        if not order_id:
            self._send_json(400, {"error": "order_id required"})
            return

        # Dedup check
        with _lock:
            processed = _load_processed()
            if order_id in processed:
                _log(f"Skip duplicate: {order_id}")
                self._send_json(200, {"status": "already_processed", "order_id": order_id})
                return

        channel_name = (data.get("channel_name") or "Unknown").strip()
        video_title  = (data.get("video_title")  or "YouTube Thumbnail").strip()
        style        = (data.get("style")  or "photo").strip()
        engine       = (data.get("engine") or "imagen").strip()
        aspect       = (data.get("aspect") or "16:9").strip()

        _log(f"Processing order: {order_id}  title='{video_title}'  channel='{channel_name}'")

        try:
            prompt     = _build_prompt(channel_name, video_title)
            image_path = _generate_thumbnail(prompt, order_id, engine, aspect, style)
            drive_data = _upload_to_drive(image_path, order_id)
            drive_link = drive_data.get("webViewLink", "")
            file_id    = drive_data.get("id", "")

            # Telegram notification
            env_vars   = _load_env()
            bot_token  = env_vars.get("TELEGRAM_BOT_TOKEN", "")
            chat_id    = env_vars.get("TELEGRAM_CHAT_ID", "SHOWCASE_TELEGRAM_CHAT_ID")
            tg_sent    = False
            if bot_token:
                msg = (
                    "<b>Fiverr Thumbnail Ready</b>\n\n"
                    f"Order: <code>{order_id}</code>\n"
                    f"Channel: {channel_name}\n"
                    f"Title: {video_title}\n\n"
                    f'<a href="{drive_link}">View on Google Drive</a>\n\n'
                    "Approve thumbnail, then deliver on Fiverr manually."
                )
                tg_sent = _send_telegram(bot_token, chat_id, msg)
                _log(f"Telegram: {'sent' if tg_sent else 'failed'}")

            # Mark processed
            with _lock:
                processed = _load_processed()
                processed.add(order_id)
                _save_processed(processed)

            self._send_json(200, {
                "status":        "ok",
                "order_id":      order_id,
                "drive_link":    drive_link,
                "file_id":       file_id,
                "image_path":    str(image_path),
                "telegram_sent": tg_sent,
            })

        except Exception as exc:
            _log(f"ERROR for {order_id}: {exc}")
            self._send_json(500, {"error": str(exc), "order_id": order_id})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log(f"Fiverr Thumbnail Server starting on http://127.0.0.1:{PORT}")

    if not GEN_SCRIPT.exists():
        _log(f"WARNING: gen.py not found at {GEN_SCRIPT}")
    if not DRIVE_SCRIPT.exists():
        _log(f"WARNING: google_drive_tool.py not found at {DRIVE_SCRIPT}")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), ThumbnailHandler)
    _log("Ready. Ctrl-C or launchctl stop to exit.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
