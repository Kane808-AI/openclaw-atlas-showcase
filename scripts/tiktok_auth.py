#!/usr/bin/env python3
"""One-time TikTok OAuth flow.

Opens TikTok auth in your browser, catches the callback on localhost:8888,
exchanges the code for tokens, and writes them to ~/.openclaw/.env.

Run once:
  ~/.openclaw/venv/google/bin/python3 ~/.openclaw/scripts/tiktok_auth.py
"""

import json
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

CLIENT_KEY    = "sbawdsd5ixvxaqsh2d"
CLIENT_SECRET = "REDACTED_SET_VIA_ENV"
REDIRECT_URI  = "http://localhost:8888/tiktok/callback"
SCOPES        = "user.info.basic,user.info.stats,video.list,video.comment"
ENV_FILE      = Path.home() / ".openclaw" / ".env"

AUTH_URL  = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

_code  = None
_state = secrets.token_urlsafe(16)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _code
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if "code" in params:
            _code = params["code"]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Done. You can close this tab.</h2>")
        else:
            err = params.get("error_description", params.get("error", "unknown error"))
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(f"<h2>Error: {err}</h2>".encode())

    def log_message(self, *_):
        pass


def _exchange(code: str) -> dict:
    body = urllib.parse.urlencode({
        "client_key":    CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code":          code,
        "grant_type":    "authorization_code",
        "redirect_uri":  REDIRECT_URI,
    }).encode()
    req = Request(TOKEN_URL, data=body,
                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                  method="POST")
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _update_env(key: str, value: str) -> None:
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def main():
    params = urllib.parse.urlencode({
        "client_key":    CLIENT_KEY,
        "scope":         SCOPES,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "state":         _state,
    })
    auth_url = f"{AUTH_URL}?{params}"

    print("Opening TikTok auth in your browser...")
    print(f"If it doesn't open automatically:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for callback on localhost:8888 (120s timeout)...")
    server = HTTPServer(("localhost", 8888), _Handler)
    server.timeout = 120
    while _code is None:
        server.handle_request()

    print("Code received. Exchanging for tokens...")
    try:
        result = _exchange(_code)
    except HTTPError as e:
        print(f"Token exchange failed {e.code}: {e.read().decode()}")
        return

    data = result.get("data", result)
    access_token  = data.get("access_token")
    refresh_token = data.get("refresh_token")
    open_id       = data.get("open_id", "")
    scope         = data.get("scope", "")

    if not access_token:
        print(f"ERROR: no access_token in response:\n{json.dumps(result, indent=2)}")
        return

    _update_env("TIKTOK_CLIENT_KEY",    CLIENT_KEY)
    _update_env("TIKTOK_CLIENT_SECRET", CLIENT_SECRET)
    _update_env("TIKTOK_ACCESS_TOKEN",  access_token)
    _update_env("TIKTOK_OPEN_ID",       open_id)
    if refresh_token:
        _update_env("TIKTOK_REFRESH_TOKEN", refresh_token)

    print(f"\nSaved to {ENV_FILE}")
    print(f"  open_id:  {open_id}")
    print(f"  scope:    {scope}")
    print(f"  token:    {access_token[:20]}...")


if __name__ == "__main__":
    main()
