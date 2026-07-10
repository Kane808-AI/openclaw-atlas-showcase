#!/usr/bin/env python3
"""ryan_verify_server.py — HTTP wrapper for ryan_verify.py.

Used by the n8n 'Atlas - Verification Trigger' workflow since n8n does not
have a shell-command node available on this installation. The server receives
HTTP calls from n8n and runs ryan_verify.py against real systems.

Endpoints:
    POST /scan    — scan verify-inbox/ for pending files, return list
    POST /verify  — run ryan_verify.py --from-file on the given filepath
    POST /process — scan + verify all pending files in one call (used by n8n)
    GET  /health  — liveness check

Port: 18794 (localhost only)
"""

import sys
import os
import json
import subprocess
import traceback
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

PYTHON = str(Path.home() / ".openclaw" / "venv" / "google" / "bin" / "python3")
SCRIPT = str(Path.home() / ".openclaw" / "scripts" / "ryan_verify.py")
INBOX = Path.home() / ".openclaw" / "workspace" / "verify-inbox"
RESULTS = Path.home() / ".openclaw" / "workspace" / "verify-results"
NOTIFY = str(Path.home() / ".openclaw" / "scripts" / "notify-telegram.sh")
PORT = 18794


def run_verify(filepath):
    try:
        proc = subprocess.run(
            [PYTHON, SCRIPT, "--from-file", filepath],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = proc.stdout + proc.stderr
        exit_code = proc.returncode

        # Parse JSON result from output
        result = None
        try:
            # Find the last JSON object in output (the result)
            import re
            matches = list(re.finditer(r'\{[^{}]*"verified_by"[^{}]*\}', output, re.DOTALL))
            if matches:
                result = json.loads(matches[-1].group())
        except Exception:
            pass

        if not result:
            result = {
                "task_id": Path(filepath).stem.replace("verify-", ""),
                "task_type": "unknown",
                "status": "UNVERIFIED" if exit_code != 0 else "UNVERIFIED",
                "evidence": f"Script exit {exit_code}. Output: {output[:300]}",
                "quality_flags": [],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "verified_by": "ryan_verify.py",
                "retry_recommended": True,
            }
            # Write UNVERIFIED result
            RESULTS.mkdir(parents=True, exist_ok=True)
            with open(RESULTS / f"{result['task_id']}.json", "w") as f:
                json.dump(result, f, indent=2)

        return result, exit_code
    except subprocess.TimeoutExpired:
        task_id = Path(filepath).stem.replace("verify-", "")
        result = {
            "task_id": task_id,
            "task_type": "unknown",
            "status": "UNVERIFIED",
            "evidence": "ryan_verify.py timed out after 120s",
            "quality_flags": [],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_by": "ryan_verify.py",
            "retry_recommended": True,
        }
        RESULTS.mkdir(parents=True, exist_ok=True)
        with open(RESULTS / f"{task_id}.json", "w") as f:
            json.dump(result, f, indent=2)
        return result, 1
    except Exception as e:
        task_id = Path(filepath).stem.replace("verify-", "")
        result = {
            "task_id": task_id,
            "task_type": "unknown",
            "status": "UNVERIFIED",
            "evidence": f"Server error: {traceback.format_exc()[:300]}",
            "quality_flags": [],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_by": "ryan_verify.py",
            "retry_recommended": True,
        }
        RESULTS.mkdir(parents=True, exist_ok=True)
        with open(RESULTS / f"{task_id}.json", "w") as f:
            json.dump(result, f, indent=2)
        return result, 1


def send_alert(message):
    try:
        subprocess.run(
            ["/bin/bash", NOTIFY, message],
            timeout=15,
            capture_output=True,
        )
    except Exception as e:
        print(f"[alert] Telegram send failed: {e}", file=sys.stderr)


def process_inbox():
    results = []
    if not INBOX.exists():
        return {"processed": 0, "results": []}

    files = sorted(INBOX.glob("*.json"))
    for f in files:
        filepath = str(f)
        result, exit_code = run_verify(filepath)
        status = result.get("status", "UNVERIFIED")
        task_type = result.get("task_type", "unknown")
        evidence = result.get("evidence", "")[:200]

        if status == "FAIL":
            msg = f"[VERIFICATION FAIL] {task_type} -- {evidence}"
            threading.Thread(target=send_alert, args=(msg,), daemon=True).start()
        elif status == "UNVERIFIED" or exit_code != 0:
            msg = f"[VERIFICATION ERROR] {task_type} -- {evidence} -- auto-retrying in 10 min"
            threading.Thread(target=send_alert, args=(msg,), daemon=True).start()

        # Delete inbox file
        try:
            f.unlink()
        except Exception as e:
            print(f"[process] Failed to delete {filepath}: {e}", file=sys.stderr)

        results.append(result)

    return {"processed": len(results), "results": results}


class VerifyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        msg = fmt % args
        stream = sys.stdout
        # Only route 4xx/5xx to stderr; access logs are not errors.
        for arg in args:
            s = str(arg)
            if s.startswith(("4", "5")) and len(s) == 3 and s.isdigit():
                stream = sys.stderr
                break
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", file=stream, flush=True)

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b"{}"

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok", "service": "ryan_verify_server", "port": PORT})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        try:
            body = json.loads(self.read_body())
        except Exception:
            body = {}

        if self.path == "/process":
            result = process_inbox()
            self.send_json(200, result)

        elif self.path == "/scan":
            if not INBOX.exists():
                self.send_json(200, {"files": []})
                return
            files = [str(f) for f in sorted(INBOX.glob("*.json"))]
            self.send_json(200, {"files": files, "count": len(files)})

        elif self.path == "/verify":
            filepath = body.get("filepath")
            if not filepath:
                self.send_json(400, {"error": "filepath required"})
                return
            result, exit_code = run_verify(filepath)
            self.send_json(200, result)

        else:
            self.send_json(404, {"error": "Unknown endpoint"})


def main():
    print(f"[ryan_verify_server] Starting on localhost:{PORT}", file=sys.stderr)
    server = HTTPServer(("127.0.0.1", PORT), VerifyHandler)
    print(f"[ryan_verify_server] Ready", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
