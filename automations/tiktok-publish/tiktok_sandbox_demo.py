#!/usr/bin/env python3
"""
Brand75 TikTok Content Posting API — Sandbox Demo
App ID: 7630899380840777729
"""

import os
import sys
import time
import json
import math
import secrets
import webbrowser
import urllib.parse
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
DOTENV_PATH = Path(__file__).parents[2] / ".env"

def _load_dotenv(path):
    if not path.exists():
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

_load_dotenv(DOTENV_PATH)

CLIENT_KEY    = os.getenv("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.getenv("TIKTOK_CLIENT_SECRET", "")
APP_ID        = "7630899380840777729"
REDIRECT_URI  = "http://localhost:8765/callback"
SCOPES        = "video.publish,video.upload"

OAUTH_URL     = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL     = "https://open.tiktokapis.com/v2/oauth/token/"
INIT_URL      = "https://open.tiktokapis.com/v2/post/publish/video/init/"
UPLOAD_URL_T  = "https://open.tiktokapis.com/v2/post/publish/video/upload/"

TEST_VIDEO    = Path(__file__).parents[2] / "workspace/outputs/tiktok/pp_1_sender_device_pc_web_id_7480225279694145066/video.mp4"

CHUNK_SIZE    = 5 * 1024 * 1024  # 5 MB

# ── Helpers ──────────────────────────────────────────────────────────────────
def banner(text, char="═", width=60):
    line = char * width
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")

def step(num, text):
    print(f"\n[Step {num}] {text}")
    time.sleep(0.5)

def ok(msg):
    print(f"  ✓  {msg}")

def info(msg):
    print(f"     {msg}")

def fail(msg):
    print(f"\n  ✗  ERROR: {msg}", file=sys.stderr)
    sys.exit(1)

# ── OAuth callback server ─────────────────────────────────────────────────────
auth_code_holder = {"code": None, "state": None}

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        auth_code_holder["code"]  = params.get("code",  [None])[0]
        auth_code_holder["state"] = params.get("state", [None])[0]

        body = b"<h2>Authorization successful. Return to your terminal.</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass  # silence server noise

def start_callback_server():
    server = HTTPServer(("localhost", 8765), CallbackHandler)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    return server, t

# ── Main demo ─────────────────────────────────────────────────────────────────
def main():
    # ── Step 0: Banner ────────────────────────────────────────────────────
    banner("Brand75 TikTok Content Posting Demo", "═", 60)
    info(f"App Name : Brand75")
    info(f"App ID   : {APP_ID}")
    info(f"Mode     : SANDBOX")
    info(f"Date     : {time.strftime('%Y-%m-%d %H:%M %Z')}")
    time.sleep(2)

    # ── Step 1: Preflight ────────────────────────────────────────────────
    step(1, "Preflight checks")

    if not CLIENT_KEY or not CLIENT_SECRET:
        fail(
            "Missing env vars. Add to ~/.openclaw/.env:\n"
            "    TIKTOK_CLIENT_KEY=<your-client-key>\n"
            "    TIKTOK_CLIENT_SECRET=<your-client-secret>"
        )
    ok("TIKTOK_CLIENT_KEY found")
    ok("TIKTOK_CLIENT_SECRET found")

    if not TEST_VIDEO.exists():
        fail(f"Test video not found at: {TEST_VIDEO}")
    video_size = TEST_VIDEO.stat().st_size
    ok(f"Test video found: {TEST_VIDEO.name} ({video_size / 1024 / 1024:.1f} MB)")
    time.sleep(1)

    # ── Step 2: OAuth ────────────────────────────────────────────────────
    step(2, "Starting OAuth 2.0 authorization flow")

    csrf_state = secrets.token_urlsafe(16)
    params = {
        "client_key":     CLIENT_KEY,
        "scope":          SCOPES,
        "response_type":  "code",
        "redirect_uri":   REDIRECT_URI,
        "state":          csrf_state,
    }
    auth_url = OAUTH_URL + "?" + urllib.parse.urlencode(params)

    info("Starting local callback server on http://localhost:8765/callback")
    server, thread = start_callback_server()
    time.sleep(0.5)

    info("Opening TikTok authorization URL in your browser...")
    info(f"URL: {auth_url}")
    time.sleep(1)
    webbrowser.open(auth_url)

    print("\n  Waiting for you to authorize in the browser...")
    deadline = time.time() + 120
    while auth_code_holder["code"] is None and time.time() < deadline:
        time.sleep(1)

    if auth_code_holder["code"] is None:
        fail("Timed out waiting for OAuth callback (120s). Check your browser.")

    if auth_code_holder["state"] != csrf_state:
        fail("CSRF state mismatch — authorization aborted.")

    ok("Authorization code received")
    time.sleep(1)

    # ── Step 3: Token exchange ───────────────────────────────────────────
    step(3, "Exchanging authorization code for access token")

    resp = requests.post(TOKEN_URL, data={
        "client_key":     CLIENT_KEY,
        "client_secret":  CLIENT_SECRET,
        "code":           auth_code_holder["code"],
        "grant_type":     "authorization_code",
        "redirect_uri":   REDIRECT_URI,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})

    if resp.status_code != 200:
        fail(f"Token exchange failed: HTTP {resp.status_code}\n{resp.text}")

    token_data = resp.json()
    if "access_token" not in token_data:
        fail(f"No access_token in response:\n{json.dumps(token_data, indent=2)}")

    ACCESS_TOKEN = token_data["access_token"]
    ok("Authorization successful — access token obtained")
    info(f"Token type : {token_data.get('token_type', 'bearer')}")
    info(f"Scope      : {token_data.get('scope', SCOPES)}")
    info(f"Expires in : {token_data.get('expires_in', '?')} seconds")
    time.sleep(2)

    # ── Step 4: Init upload ──────────────────────────────────────────────
    step(4, "Initializing video upload via Content Posting API (sandbox)")

    chunk_count = math.ceil(video_size / CHUNK_SIZE)
    init_payload = {
        "post_info": {
            "title":         "Brand75 API Demo — Sandbox Test",
            "privacy_level": "SELF_ONLY",
            "disable_duet":  True,
            "disable_stitch": True,
            "disable_comment": True,
        },
        "source_info": {
            "source":         "FILE_UPLOAD",
            "video_size":     video_size,
            "chunk_size":     CHUNK_SIZE,
            "total_chunk_count": chunk_count,
        },
    }

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type":  "application/json; charset=UTF-8",
    }

    init_resp = requests.post(INIT_URL, json=init_payload, headers=headers)

    if init_resp.status_code != 200:
        fail(
            f"Upload init failed: HTTP {init_resp.status_code}\n"
            f"{json.dumps(init_resp.json(), indent=2)}"
        )

    init_data = init_resp.json()
    if init_data.get("error", {}).get("code", "ok") != "ok":
        fail(f"API error during init:\n{json.dumps(init_data, indent=2)}")

    publish_id  = init_data["data"]["publish_id"]
    upload_url  = init_data["data"]["upload_url"]
    ok(f"Upload initialized — publish_id: {publish_id}")
    info(f"Chunks     : {chunk_count}")
    info(f"Upload URL : {upload_url[:60]}...")
    time.sleep(1.5)

    # ── Step 5: Upload chunks ────────────────────────────────────────────
    step(5, f"Uploading video ({chunk_count} chunk{'s' if chunk_count > 1 else ''})")

    with open(TEST_VIDEO, "rb") as fh:
        for chunk_idx in range(chunk_count):
            chunk_data = fh.read(CHUNK_SIZE)
            start_byte = chunk_idx * CHUNK_SIZE
            end_byte   = start_byte + len(chunk_data) - 1

            upload_headers = {
                "Authorization":  f"Bearer {ACCESS_TOKEN}",
                "Content-Type":   "video/mp4",
                "Content-Range":  f"bytes {start_byte}-{end_byte}/{video_size}",
                "Content-Length": str(len(chunk_data)),
            }

            up_resp = requests.put(upload_url, data=chunk_data, headers=upload_headers)
            if up_resp.status_code not in (200, 201, 206):
                fail(
                    f"Chunk {chunk_idx + 1} upload failed: HTTP {up_resp.status_code}\n"
                    f"{up_resp.text[:500]}"
                )
            ok(f"Chunk {chunk_idx + 1}/{chunk_count} uploaded")
            time.sleep(0.5)

    time.sleep(1)

    # ── Step 6: Show response ────────────────────────────────────────────
    step(6, "TikTok API response")

    print("\n  Raw API response from upload init:")
    display = {k: v for k, v in init_data.items() if k != "access_token"}
    print(json.dumps(display, indent=4))
    time.sleep(2)

    # ── Done ─────────────────────────────────────────────────────────────
    banner("Demo complete. Video submitted to TikTok via Content Posting API.", "─", 60)
    info(f"Publish ID : {publish_id}")
    info("Status     : Submitted to sandbox (not published to live account)")
    info("")
    time.sleep(1)

if __name__ == "__main__":
    main()
