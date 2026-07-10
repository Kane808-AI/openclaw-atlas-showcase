#!/usr/bin/env python3
"""Fiverr Product Server — Lane 2 delivery on port 18793.

n8n calls POST /deliver with a Fiverr product order.
Server looks up the product in catalog.json, assembles the delivery package,
uploads to Google Drive under "Fiverr Products/{order_id}/", sends a Telegram
notification to Chris with the Drive link, and returns the result.

Chris reviews the Drive folder, then delivers the link manually on Fiverr.

Endpoints:
  GET  /health    -> {"status": "ok", "port": 18793}
  GET  /catalog   -> list of available products
  POST /deliver   -> {status, order_id, product_id, drive_link, telegram_sent}

POST /deliver body (JSON):
  {
    "order_id":    "FO1234567",         # Required
    "product_id":  "ghl-lead-capture",  # Required — must match catalog entry
    "buyer_name":  "johndoe",           # Optional
    "email_id":    "18f3a2b1c...",      # Optional — Gmail message ID for dedup
    "notes":       "buyer said..."      # Optional — any special instructions
  }

Deduplication: processed order_ids stored in
  ~/.openclaw/workspace/data/fiverr-processed-products.json

Start:  python3 ~/.openclaw/scripts/fiverr_product_server.py
Stop:   launchctl stop ai.openclaw.fiverr-product
Health: curl http://127.0.0.1:18793/health
"""

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 18793

_HOME = Path.home()
CATALOG_FILE   = _HOME / ".openclaw" / "workspace" / "automations" / "fiverr-products" / "catalog.json"
PRODUCTS_DIR   = _HOME / ".openclaw" / "workspace" / "automations" / "fiverr-products" / "products"
DRIVE_SCRIPT   = _HOME / ".openclaw" / "scripts" / "google_drive_tool.py"
ENV_FILE       = _HOME / ".openclaw" / ".env"
PROCESSED_FILE = _HOME / ".openclaw" / "workspace" / "data" / "fiverr-processed-products.json"
TMP_DIR        = _HOME / ".openclaw" / "tmp" / "products"
LOG_DIR        = _HOME / ".openclaw" / "logs"
LOG_FILE       = LOG_DIR / "fiverr-product-stdout.log"
VENV_PYTHON    = _HOME / ".openclaw" / "venv" / "google" / "bin" / "python3"

DRIVE_PARENT_FOLDER = "Fiverr Products"

_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers (mirrors fiverr_thumbnail_server.py patterns)
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


def _load_catalog() -> dict:
    try:
        return json.loads(CATALOG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Cannot load catalog: {e}")


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
# Assembly: copy product files, inject buyer-specific README
# ---------------------------------------------------------------------------

def _assemble_package(product: dict, order_id: str, buyer_name: str, notes: str) -> Path:
    """Copy product template to a tmp working dir, inject buyer README. Returns dir path."""
    product_id = product["id"]
    src_dir = PRODUCTS_DIR / product_id
    if not src_dir.exists():
        raise RuntimeError(f"Product template dir not found: {src_dir}")

    out_dir = TMP_DIR / order_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(src_dir, out_dir)

    # Inject buyer-specific cover note
    cover = out_dir / "DELIVERY.md"
    cover.write_text(
        f"# Order Delivery — {product['name']}\n\n"
        f"**Order ID:** {order_id}\n"
        f"**Buyer:** {buyer_name or 'N/A'}\n"
        f"**Delivered:** {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} PT\n"
        + (f"**Special Notes:** {notes}\n" if notes else "")
        + "\n---\n\n"
        f"{product.get('delivery_note', 'See README.md for setup instructions.')}\n"
    )

    _log(f"Package assembled: {out_dir} ({sum(1 for _ in out_dir.rglob('*') if _.is_file())} files)")
    return out_dir


def _upload_folder_to_drive(src_dir: Path, order_id: str) -> dict:
    """Upload all files in src_dir to Drive under Fiverr Products/{order_id}/. Returns last upload result."""
    env = dict(os.environ)
    for k, v in _load_env().items():
        env.setdefault(k, v)

    results = []
    for file_path in sorted(src_dir.rglob("*")):
        if not file_path.is_file():
            continue
        cmd = [
            str(VENV_PYTHON), str(DRIVE_SCRIPT),
            "upload", str(file_path),
            "--folder-name", order_id,
            "--parent-folder", DRIVE_PARENT_FOLDER,
        ]
        _log(f"Uploading {file_path.name} to Drive/{DRIVE_PARENT_FOLDER}/{order_id}/")
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=90)
        if result.returncode != 0:
            raise RuntimeError(f"Drive upload failed for {file_path.name}: {result.stderr[:300]}")
        data = json.loads(result.stdout)
        if "error" in data:
            raise RuntimeError(f"Drive error uploading {file_path.name}: {data['error']}")
        results.append(data)

    if not results:
        raise RuntimeError("No files uploaded — product dir may be empty")

    # Return folder-level link (Drive link for the first file's parent folder)
    # The parent folder URL is derived from the folder ID returned by the last upload
    folder_link = results[-1].get("folderLink") or results[-1].get("webViewLink", "")
    folder_id   = results[-1].get("folderId", "")
    _log(f"Drive upload complete: {len(results)} files → {DRIVE_PARENT_FOLDER}/{order_id}/")
    return {"webViewLink": folder_link, "folderId": folder_id, "fileCount": len(results)}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class ProductHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
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
        elif self.path == "/catalog":
            try:
                catalog = _load_catalog()
                # Return simplified list for n8n / external callers
                products = [
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "description": p.get("description", ""),
                        "keywords": p.get("keywords", []),
                    }
                    for p in catalog.get("products", [])
                ]
                self._send_json(200, {"products": products})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/deliver":
            self._send_json(404, {"error": "not found"})
            return

        try:
            data = json.loads(self._read_body())
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        order_id   = (data.get("order_id") or "").strip()
        product_id = (data.get("product_id") or "").strip()
        if not order_id:
            self._send_json(400, {"error": "order_id required"})
            return
        if not product_id:
            self._send_json(400, {"error": "product_id required"})
            return

        # Dedup check
        with _lock:
            processed = _load_processed()
            if order_id in processed:
                _log(f"Skip duplicate product order: {order_id}")
                self._send_json(200, {"status": "already_processed", "order_id": order_id})
                return

        buyer_name = (data.get("buyer_name") or "").strip()
        notes      = (data.get("notes") or "").strip()

        _log(f"Processing product order: {order_id}  product={product_id}  buyer={buyer_name or 'unknown'}")

        try:
            catalog = _load_catalog()
            product = next(
                (p for p in catalog.get("products", []) if p["id"] == product_id),
                None,
            )
            if product is None:
                self._send_json(400, {"error": f"Unknown product_id: {product_id}"})
                return

            pkg_dir    = _assemble_package(product, order_id, buyer_name, notes)
            drive_data = _upload_folder_to_drive(pkg_dir, order_id)
            drive_link = drive_data.get("webViewLink", "")
            file_count = drive_data.get("fileCount", 0)

            # Telegram notification
            env_vars  = _load_env()
            bot_token = env_vars.get("TELEGRAM_BOT_TOKEN", "")
            chat_id   = env_vars.get("TELEGRAM_CHAT_ID", "SHOWCASE_TELEGRAM_CHAT_ID")
            tg_sent   = False
            if bot_token:
                msg = (
                    "<b>Fiverr Product Ready to Deliver</b>\n\n"
                    f"Order: <code>{order_id}</code>\n"
                    f"Product: {product['name']}\n"
                    f"Buyer: {buyer_name or 'unknown'}\n"
                    f"Files: {file_count}\n\n"
                    + (f"Notes: {notes}\n\n" if notes else "")
                    + (f'<a href="{drive_link}">View Package on Google Drive</a>\n\n' if drive_link else "")
                    + "Review, then deliver the Drive link manually on Fiverr."
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
                "product_id":    product_id,
                "product_name":  product["name"],
                "drive_link":    drive_link,
                "file_count":    file_count,
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
    _log(f"Fiverr Product Server starting on http://127.0.0.1:{PORT}")

    if not CATALOG_FILE.exists():
        _log(f"WARNING: catalog.json not found at {CATALOG_FILE}")
    if not PRODUCTS_DIR.exists():
        _log(f"WARNING: products/ dir not found at {PRODUCTS_DIR}")

    server = ThreadingHTTPServer(("127.0.0.1", PORT), ProductHandler)
    _log("Ready. Ctrl-C or launchctl stop to exit.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Stopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
