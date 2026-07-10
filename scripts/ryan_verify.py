#!/usr/bin/env python3
"""ryan_verify.py — Atlas accountability layer verification authority.

The script signs its own output. verified_by is always 'ryan_verify.py'.
Ryan cannot override or alter results.

Usage:
    python3 ryan_verify.py --type fiverr --order-id "order-001"
    python3 ryan_verify.py --type seo-content --client "callahan-law" --keyword "DUI attorney"
    python3 ryan_verify.py --type loop-a --contact-id "abc123" --tag "loop-a-contacted"
    python3 ryan_verify.py --type landing-page --url "https://links.brand75.com/offer"
    python3 ryan_verify.py --type email-sequence --workflow-name "Loop A - Welcome"
    python3 ryan_verify.py --type pdf --workflow-name "PDF Delivery" --client "client-name"
    python3 ryan_verify.py --type consulting --client "callahan-law"
    python3 ryan_verify.py --type content --path "/path/to/script.txt"
    python3 ryan_verify.py --type sms-copy --contact-id "abc123" --path "/path/to/file.txt"
    python3 ryan_verify.py --type code --path "~/.openclaw/scripts/new_script.py"
    python3 ryan_verify.py --type daily-summary
    python3 ryan_verify.py --from-file ~/.openclaw/workspace/verify-inbox/verify-{task_id}.json
"""

import sys
import os
import json
import argparse
import traceback
import subprocess
import re
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path.home() / ".openclaw" / "scripts"))

import requests

# --- Paths ---
OPENCLAW = Path.home() / ".openclaw"
ENV_PATH = OPENCLAW / ".env"
WORKSPACE = OPENCLAW / "workspace"
VERIFY_INBOX = WORKSPACE / "verify-inbox"
VERIFY_RESULTS = WORKSPACE / "verify-results"
CURRENT_STATE = WORKSPACE / "CURRENT_STATE.md"
MEMORY_DIR = WORKSPACE / "memory"
DELIVERABLES_CMO = WORKSPACE / "agents" / "cmo" / "deliverables"
DELIVERABLES_COPY = WORKSPACE / "agents" / "copywriter" / "deliverables"

# --- GHL ---
GHL_BASE = "https://services.leadconnectorhq.com"
GHL_VERSION = "2021-07-28"
GHL_LOCATION_ID = "SHOWCASE_GHL_LOCATION_ID"

# --- Placeholder patterns ---
PLACEHOLDER_PATTERNS = ["[INSERT", "TODO", "PLACEHOLDER", "###", "[YOUR"]

# --- Load env ---
_env = {}
if ENV_PATH.exists():
    with open(ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                _env[_k.strip()] = _v.strip().strip('"').strip("'")

GHL_KEY = _env.get("GHL_API_KEY", "")
LOCATION_ID = _env.get("GHL_LOCATION_ID", GHL_LOCATION_ID)
TELEGRAM_TOKEN = _env.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env.get("TELEGRAM_CHAT_ID", "SHOWCASE_TELEGRAM_CHAT_ID")


def ghl_headers():
    return {
        "Authorization": f"Bearer {GHL_KEY}",
        "Version": GHL_VERSION,
        "Content-Type": "application/json",
    }


def make_result(task_id, task_type, status, evidence, quality_flags=None, retry_recommended=False):
    return {
        "task_id": task_id,
        "task_type": task_type,
        "status": status,
        "evidence": evidence,
        "quality_flags": quality_flags or [],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "verified_by": "ryan_verify.py",
        "retry_recommended": retry_recommended,
    }


def write_result(result):
    VERIFY_RESULTS.mkdir(parents=True, exist_ok=True)
    out_path = VERIFY_RESULTS / f"{result['task_id']}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    return out_path


def scan_placeholders(text):
    found = []
    for pat in PLACEHOLDER_PATTERNS:
        if pat in text:
            found.append(pat)
    return found


def word_count(text):
    return len(text.split())


def load_drive_service():
    from google_auth import get_brand75_credentials
    from googleapiclient.discovery import build
    creds = get_brand75_credentials()
    return build("drive", "v3", credentials=creds)


def drive_find_folder(service, name, parent_id=None):
    q = f"name = {json.dumps(name)} and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    resp = service.files().list(
        q=q,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora="allDrives",
    ).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def drive_list_files(service, folder_id):
    resp = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, size, mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        corpora="allDrives",
    ).execute()
    return resp.get("files", [])


def drive_download_text(service, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    import io
    req = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue().decode("utf-8", errors="replace")


# --- Verifiers ---

def verify_fiverr(task_id, order_id, expected_count=None):
    try:
        service = load_drive_service()
        root_id = drive_find_folder(service, "Fiverr Thumbnails")
        if not root_id:
            return make_result(task_id, "fiverr", "FAIL",
                               "Folder 'Fiverr Thumbnails' not found in Drive")
        order_folder_id = drive_find_folder(service, f"order-{order_id}", parent_id=root_id)
        if not order_folder_id:
            # Also try without "order-" prefix
            order_folder_id = drive_find_folder(service, order_id, parent_id=root_id)
        if not order_folder_id:
            return make_result(task_id, "fiverr", "FAIL",
                               f"Order folder 'order-{order_id}' not found under Fiverr Thumbnails")
        files = drive_list_files(service, order_folder_id)
        if not files:
            return make_result(task_id, "fiverr", "FAIL",
                               f"Order folder order-{order_id} exists but contains no files")

        flags = []
        zero_byte_files = []
        suspicious_names = []
        bad_format_files = []
        ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf"}
        SUSPICIOUS_KEYWORDS = ["placeholder", "test", "sample"]

        for f in files:
            name_lower = f["name"].lower()
            size = int(f.get("size", 0))
            if size == 0:
                zero_byte_files.append(f["name"])
            if any(kw in name_lower for kw in SUSPICIOUS_KEYWORDS):
                suspicious_names.append(f["name"])
            ext = Path(f["name"]).suffix.lower()
            if ext not in ALLOWED_EXT:
                bad_format_files.append(f["name"])

        if suspicious_names:
            flags.append(f"suspicious_filename_detected: {suspicious_names}")
        if zero_byte_files:
            return make_result(task_id, "fiverr", "FAIL",
                               f"Zero-byte files found: {zero_byte_files}", flags)
        if suspicious_names:
            return make_result(task_id, "fiverr", "FAIL",
                               f"Suspicious filenames detected: {suspicious_names}", flags)

        if expected_count and len(files) != expected_count:
            return make_result(task_id, "fiverr", "FAIL",
                               f"File count mismatch: expected {expected_count}, found {len(files)}", flags)

        return make_result(task_id, "fiverr", "PASS",
                           f"order-{order_id}: {len(files)} files, all non-zero, no suspicious names",
                           flags)
    except Exception:
        return make_result(task_id, "fiverr", "UNVERIFIED",
                           f"Drive check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_seo_content(task_id, client, keyword):
    try:
        service = load_drive_service()
        root_id = drive_find_folder(service, "SEO Content")
        if not root_id:
            return make_result(task_id, "seo-content", "FAIL",
                               "Folder 'SEO Content' not found in Drive")
        client_folder_id = drive_find_folder(service, client, parent_id=root_id)
        if not client_folder_id:
            return make_result(task_id, "seo-content", "FAIL",
                               f"Client folder '{client}' not found under SEO Content")
        files = drive_list_files(service, client_folder_id)
        if not files:
            return make_result(task_id, "seo-content", "FAIL",
                               f"No files found in SEO Content/{client}/")

        # Use most recent doc/text file
        doc_file = None
        for f in files:
            mime = f.get("mimeType", "")
            if "document" in mime or "text" in mime or f["name"].endswith((".txt", ".md", ".docx")):
                doc_file = f
                break
        if not doc_file:
            doc_file = files[0]

        text = drive_download_text(service, doc_file["id"])
        wc = word_count(text)
        flags = []

        if wc < 1000:
            return make_result(task_id, "seo-content", "FAIL",
                               f"Word count {wc} below 1000 minimum. File: {doc_file['name']}", flags)

        if keyword:
            kw_count = text.lower().count(keyword.lower())
            if kw_count < 3:
                return make_result(task_id, "seo-content", "FAIL",
                                   f"Keyword '{keyword}' appears {kw_count} times (need 3+). Word count: {wc}", flags)
        else:
            kw_count = "N/A (no keyword specified)"

        placeholders = scan_placeholders(text)
        if placeholders:
            return make_result(task_id, "seo-content", "FAIL",
                               f"Placeholder patterns found: {placeholders}. File: {doc_file['name']}", flags)

        return make_result(task_id, "seo-content", "PASS",
                           f"{doc_file['name']}: {wc} words, keyword '{keyword}' x{kw_count}, no placeholders",
                           flags)
    except Exception:
        return make_result(task_id, "seo-content", "UNVERIFIED",
                           f"Drive check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_loop_a(task_id, contact_id, tag):
    if not GHL_KEY:
        return make_result(task_id, "loop-a", "UNVERIFIED", "GHL_API_KEY not set in .env")
    try:
        # Tags are in the contact object (not a separate /tags endpoint)
        contact_resp = requests.get(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=ghl_headers(),
            timeout=10,
        )
        if contact_resp.status_code != 200:
            return make_result(task_id, "loop-a", "UNVERIFIED",
                               f"GHL contact API returned {contact_resp.status_code}: {contact_resp.text[:200]}",
                               retry_recommended=True)

        contact_data = contact_resp.json().get("contact", contact_resp.json())
        contact_tags = contact_data.get("tags", [])
        tag_found = tag in contact_tags

        # Check SMS in timeline via conversations
        conv_resp = requests.get(
            f"{GHL_BASE}/conversations/search",
            headers=ghl_headers(),
            params={"contactId": contact_id, "locationId": LOCATION_ID},
            timeout=10,
        )

        sms_found = False
        sms_evidence = "No conversation found"
        if conv_resp.status_code == 200:
            conv_data = conv_resp.json()
            convs = conv_data.get("conversations", [])
            if convs:
                conv_id = convs[0].get("id")
                if conv_id:
                    msg_resp = requests.get(
                        f"{GHL_BASE}/conversations/{conv_id}/messages",
                        headers=ghl_headers(),
                        timeout=10,
                    )
                    if msg_resp.status_code == 200:
                        msgs = msg_resp.json().get("messages", {}).get("messages", [])
                        outbound_sms = [
                            m for m in msgs
                            if m.get("type") in (1, "TYPE_SMS", "SMS") or
                            (m.get("direction") == "outbound" and
                             m.get("messageType", "").upper() in ("SMS", ""))
                        ]
                        if outbound_sms:
                            sms_found = True
                            sms_evidence = f"Outbound SMS found ({len(outbound_sms)} messages)"
                        else:
                            sms_evidence = f"Conversation {conv_id} exists but no outbound SMS messages"
            else:
                sms_evidence = "No conversations found for contact"

        if not tag_found:
            return make_result(task_id, "loop-a", "FAIL",
                               f"Tag '{tag}' NOT on contact {contact_id}. Tags: {contact_tags}. SMS: {sms_evidence}")
        if not sms_found:
            return make_result(task_id, "loop-a", "FAIL",
                               f"Tag '{tag}' found. SMS check: {sms_evidence}. Contact: {contact_id}")

        return make_result(task_id, "loop-a", "PASS",
                           f"Tag '{tag}' confirmed. {sms_evidence}. Contact: {contact_id}")
    except Exception:
        return make_result(task_id, "loop-a", "UNVERIFIED",
                           f"GHL API check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_landing_page(task_id, url):
    try:
        resp = requests.get(url, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return make_result(task_id, "landing-page", "FAIL",
                               f"HTTP {resp.status_code} from {url}")
        body = resp.text
        LOGIN_MARKERS = ["/login", "Sign In to HighLevel", "highlevel.com/login", "app.gohighlevel.com"]
        for marker in LOGIN_MARKERS:
            if marker in body:
                return make_result(task_id, "landing-page", "FAIL",
                                   f"Login redirect detected — marker '{marker}' found in body. URL: {url}")
        return make_result(task_id, "landing-page", "PASS",
                           f"HTTP 200, no login markers. URL: {url}")
    except Exception:
        return make_result(task_id, "landing-page", "UNVERIFIED",
                           f"HTTP check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_email_sequence(task_id, workflow_name):
    if not GHL_KEY:
        return make_result(task_id, "email-sequence", "UNVERIFIED", "GHL_API_KEY not set in .env")
    try:
        resp = requests.get(
            f"{GHL_BASE}/workflows",
            headers=ghl_headers(),
            params={"locationId": LOCATION_ID},
            timeout=10,
        )
        if resp.status_code != 200:
            return make_result(task_id, "email-sequence", "UNVERIFIED",
                               f"GHL workflows API returned {resp.status_code}: {resp.text[:200]}",
                               retry_recommended=True)
        workflows = resp.json().get("workflows", [])
        match = None
        for wf in workflows:
            if workflow_name.lower() in wf.get("name", "").lower():
                match = wf
                break
        if not match:
            return make_result(task_id, "email-sequence", "FAIL",
                               f"Workflow '{workflow_name}' not found. Available: {[w['name'] for w in workflows[:10]]}")

        status = match.get("status", "").lower()
        step_count = len(match.get("actions", []))

        if status != "published":
            return make_result(task_id, "email-sequence", "FAIL",
                               f"Workflow '{match['name']}' status='{status}' (need published). Steps: {step_count}")
        if step_count == 0:
            return make_result(task_id, "email-sequence", "FAIL",
                               f"Workflow '{match['name']}' is published but has 0 steps")

        return make_result(task_id, "email-sequence", "PASS",
                           f"Workflow '{match['name']}' — status={status}, steps={step_count}")
    except Exception:
        return make_result(task_id, "email-sequence", "UNVERIFIED",
                           f"GHL API check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_pdf(task_id, workflow_name, client):
    if not GHL_KEY:
        return make_result(task_id, "pdf", "UNVERIFIED", "GHL_API_KEY not set in .env")
    try:
        # Check GHL workflow
        wf_result = verify_email_sequence(task_id, workflow_name)
        if wf_result["status"] == "FAIL":
            return make_result(task_id, "pdf", "FAIL",
                               f"GHL delivery workflow check failed: {wf_result['evidence']}")
        if wf_result["status"] == "UNVERIFIED":
            return make_result(task_id, "pdf", "UNVERIFIED",
                               f"GHL workflow check unverified: {wf_result['evidence']}", retry_recommended=True)

        # Check Drive PDF
        service = load_drive_service()
        root_id = drive_find_folder(service, "Lead Magnets") or drive_find_folder(service, "PDFs")
        pdf_found = False
        pdf_evidence = "Drive folder 'Lead Magnets' or 'PDFs' not found"

        if root_id:
            client_id = drive_find_folder(service, client, parent_id=root_id)
            search_folder = client_id or root_id
            files = drive_list_files(service, search_folder)
            pdfs = [f for f in files if f["name"].lower().endswith(".pdf") or
                    f.get("mimeType", "") == "application/pdf"]
            if pdfs:
                pdf_size = int(pdfs[0].get("size", 0))
                if pdf_size > 10240:
                    pdf_found = True
                    pdf_evidence = f"PDF '{pdfs[0]['name']}' found, size={pdf_size} bytes"
                else:
                    pdf_evidence = f"PDF '{pdfs[0]['name']}' found but size={pdf_size} bytes (< 10KB, likely empty)"

        if not pdf_found:
            return make_result(task_id, "pdf", "FAIL",
                               f"GHL workflow OK. Drive PDF check: {pdf_evidence}")

        return make_result(task_id, "pdf", "PASS",
                           f"GHL workflow published. {pdf_evidence}")
    except Exception:
        return make_result(task_id, "pdf", "UNVERIFIED",
                           f"Check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_consulting(task_id, client):
    try:
        service = load_drive_service()
        consulting_id = drive_find_folder(service, "Consulting")
        if not consulting_id:
            return make_result(task_id, "consulting", "FAIL",
                               "Folder 'Consulting' not found in Drive")
        deliverables_id = drive_find_folder(service, "Deliverables", parent_id=consulting_id)
        if not deliverables_id:
            return make_result(task_id, "consulting", "FAIL",
                               "Folder 'Consulting/Deliverables' not found in Drive")
        client_id = drive_find_folder(service, client, parent_id=deliverables_id)
        if not client_id:
            return make_result(task_id, "consulting", "FAIL",
                               f"Client folder '{client}' not found under Consulting/Deliverables/")
        files = drive_list_files(service, client_id)
        if not files:
            return make_result(task_id, "consulting", "FAIL",
                               f"No files found in Consulting/Deliverables/{client}/")

        doc_file = None
        for f in files:
            mime = f.get("mimeType", "")
            if "document" in mime or "text" in mime or f["name"].endswith((".txt", ".md", ".docx")):
                doc_file = f
                break
        if not doc_file:
            doc_file = files[0]

        text = drive_download_text(service, doc_file["id"])
        wc = word_count(text)
        if wc < 500:
            return make_result(task_id, "consulting", "FAIL",
                               f"Word count {wc} below 500 minimum. File: {doc_file['name']}")
        placeholders = scan_placeholders(text)
        if placeholders:
            return make_result(task_id, "consulting", "FAIL",
                               f"Placeholder patterns found: {placeholders}. File: {doc_file['name']}")
        return make_result(task_id, "consulting", "PASS",
                           f"{doc_file['name']}: {wc} words, no placeholders")
    except Exception:
        return make_result(task_id, "consulting", "UNVERIFIED",
                           f"Drive check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_content(task_id, file_path, min_words=150):
    try:
        if file_path:
            p = Path(os.path.expanduser(file_path))
        else:
            # Look for most recent file in cmo deliverables
            p = None
            if DELIVERABLES_CMO.exists():
                files = sorted(DELIVERABLES_CMO.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
                if files:
                    p = files[0]
        if not p or not p.exists():
            return make_result(task_id, "content", "FAIL",
                               f"File not found: {file_path or str(DELIVERABLES_CMO)}")
        text = p.read_text(errors="replace")
        wc = word_count(text)
        if wc < min_words:
            return make_result(task_id, "content", "FAIL",
                               f"Word count {wc} below {min_words} minimum. File: {p.name}")
        placeholders = scan_placeholders(text)
        if placeholders:
            return make_result(task_id, "content", "FAIL",
                               f"Placeholder patterns found: {placeholders}. File: {p.name}")
        return make_result(task_id, "content", "PASS",
                           f"{p.name}: {wc} words, no placeholders")
    except Exception:
        return make_result(task_id, "content", "UNVERIFIED",
                           f"File check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_sms_copy(task_id, contact_id, file_path):
    if not GHL_KEY:
        return make_result(task_id, "sms-copy", "UNVERIFIED", "GHL_API_KEY not set in .env")
    try:
        flags = []

        # Local file check
        file_ok = False
        file_evidence = "No file path provided"
        if file_path:
            p = Path(os.path.expanduser(file_path))
            if p.exists():
                text = p.read_text(errors="replace")
                placeholders = scan_placeholders(text)
                if placeholders:
                    return make_result(task_id, "sms-copy", "FAIL",
                                       f"Placeholder patterns in local file: {placeholders}. File: {p.name}")
                file_ok = True
                file_evidence = f"Local file '{p.name}' exists, no placeholders"
            else:
                file_evidence = f"Local file not found: {file_path}"

        # GHL timeline SMS check
        conv_resp = requests.get(
            f"{GHL_BASE}/conversations/search",
            headers=ghl_headers(),
            params={"contactId": contact_id, "locationId": LOCATION_ID},
            timeout=10,
        )
        sms_found = False
        sms_evidence = "No conversation found"
        if conv_resp.status_code == 200:
            convs = conv_resp.json().get("conversations", [])
            if convs:
                conv_id = convs[0].get("id")
                if conv_id:
                    msg_resp = requests.get(
                        f"{GHL_BASE}/conversations/{conv_id}/messages",
                        headers=ghl_headers(),
                        timeout=10,
                    )
                    if msg_resp.status_code == 200:
                        msgs = msg_resp.json().get("messages", {}).get("messages", [])
                        outbound = [
                            m for m in msgs
                            if m.get("direction") == "outbound" or
                            m.get("type") in (1, "SMS", "TYPE_SMS")
                        ]
                        if outbound:
                            sms_found = True
                            sms_evidence = f"Outbound SMS found in conversation {conv_id}"
                        else:
                            sms_evidence = f"No outbound SMS in conversation {conv_id}"

        if not file_ok:
            return make_result(task_id, "sms-copy", "FAIL",
                               f"File check: {file_evidence}. SMS: {sms_evidence}", flags)
        if not sms_found:
            return make_result(task_id, "sms-copy", "FAIL",
                               f"{file_evidence}. SMS check: {sms_evidence}", flags)

        return make_result(task_id, "sms-copy", "PASS",
                           f"{file_evidence}. {sms_evidence}", flags)
    except Exception:
        return make_result(task_id, "sms-copy", "UNVERIFIED",
                           f"SMS copy check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_code(task_id, file_path, launchd_label=None):
    try:
        p = Path(os.path.expanduser(file_path))
        if not p.exists():
            return make_result(task_id, "code", "FAIL",
                               f"File not found: {file_path}")

        # Smoke test
        venv_python = str(OPENCLAW / "venv" / "google" / "bin" / "python3")
        python_bin = venv_python if Path(venv_python).exists() else sys.executable
        try:
            proc = subprocess.run(
                [python_bin, str(p), "--help"],
                capture_output=True, text=True, timeout=15
            )
            smoke_ok = proc.returncode == 0
            smoke_evidence = f"--help exit code {proc.returncode}"
            if not smoke_ok:
                smoke_evidence += f". stderr: {proc.stderr[:200]}"
        except subprocess.TimeoutExpired:
            return make_result(task_id, "code", "FAIL",
                               f"Smoke test timed out after 15s. File: {file_path}")
        except Exception as e:
            return make_result(task_id, "code", "UNVERIFIED",
                               f"Smoke test error: {e}", retry_recommended=True)

        if not smoke_ok:
            return make_result(task_id, "code", "FAIL",
                               f"Smoke test failed ({smoke_evidence}). File: {file_path}")

        # launchd check
        launchd_evidence = ""
        if launchd_label:
            try:
                lc = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
                if launchd_label in lc.stdout:
                    launchd_evidence = f" launchd '{launchd_label}' loaded."
                else:
                    return make_result(task_id, "code", "FAIL",
                                       f"File exists, smoke test passed, but launchd label '{launchd_label}' not loaded")
            except Exception as e:
                return make_result(task_id, "code", "UNVERIFIED",
                                   f"launchctl check failed: {e}", retry_recommended=True)

        return make_result(task_id, "code", "PASS",
                           f"{p.name}: exists, smoke test passed.{launchd_evidence}")
    except Exception:
        return make_result(task_id, "code", "UNVERIFIED",
                           f"Code check failed: {traceback.format_exc()}", retry_recommended=True)


def verify_daily_summary(task_id):
    try:
        today = datetime.now()
        days = []
        for offset in range(2, -1, -1):
            from datetime import timedelta
            d = today - timedelta(days=offset)
            d_str = d.strftime("%Y-%m-%d")
            result_files = list(VERIFY_RESULTS.glob("*.json")) if VERIFY_RESULTS.exists() else []

            claimed = 0
            passed = 0
            failed = 0
            unverified = 0
            blocked = 0

            for rf in result_files:
                try:
                    with open(rf) as f:
                        r = json.load(f)
                    ts = r.get("timestamp", "")
                    if ts.startswith(d_str):
                        claimed += 1
                        s = r.get("status", "")
                        if s == "PASS":
                            passed += 1
                        elif s == "FAIL":
                            failed += 1
                            blocked += 1
                        elif s == "UNVERIFIED":
                            unverified += 1
                except Exception:
                    pass

            days.append({
                "date": d_str,
                "claimed": claimed,
                "pass": passed,
                "fail": failed,
                "unverified": unverified,
                "blocked": blocked,
            })

        # Build CURRENT_STATE.md
        now_str = today.strftime("%Y-%m-%d %H:%M")
        trend_rows = ""
        for d in days:
            trend_rows += f"| {d['date']} | {d['claimed']} | {d['pass']} | {d['fail']} | {d['unverified']} | {d['blocked']} |\n"

        content = f"""# Current State
_Last updated: {now_str} PT — source: ryan_verify.py_

## 3-Day Trend
| Date | Claimed | PASS | FAIL | UNVERIFIED | Blocked |
|------|---------|------|------|------------|---------|
{trend_rows.rstrip()}

## Active Revenue Pushes
- Loop A: [status] — [last verified action] — [next step]
- Fiverr: [status] — [last order / pending] — [blocker if any]
- TikTok: [follower count] — [last post] — [next action]

## Verified Complete Today
- (populated from verify-results/ — see {days[-1]['pass']} PASS results above)

## Needs Attention
- (populated from verify-results/ — see {days[-1]['fail']} FAIL, {days[-1]['unverified']} UNVERIFIED above)

## Infrastructure
- OpenClaw gateway: [up/down]
- TikTok Brain: [active/inactive]
- Vault MCP server: [up/down]
- GitHub backup: [last sync date]
- Verify inbox: [pending files: {len(list(VERIFY_INBOX.glob('*.json'))) if VERIFY_INBOX.exists() else 0}]

## Blockers for Chris
- (none recorded — check FAIL/UNVERIFIED results above for active blockers)
"""
        CURRENT_STATE.write_text(content)
        today_stats = days[-1]
        return make_result(task_id, "daily-summary", "PASS",
                           f"CURRENT_STATE.md written. Today ({today_stats['date']}): "
                           f"claimed={today_stats['claimed']}, pass={today_stats['pass']}, "
                           f"fail={today_stats['fail']}, unverified={today_stats['unverified']}")
    except Exception:
        return make_result(task_id, "daily-summary", "UNVERIFIED",
                           f"Daily summary failed: {traceback.format_exc()}", retry_recommended=True)


# --- Main dispatch ---

def dispatch(args):
    task_type = args.task_type
    now_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    task_id = f"{task_type}-{now_ts}"

    if task_type == "fiverr":
        if not args.order_id:
            return make_result(task_id, task_type, "UNVERIFIED", "--order-id required for fiverr")
        return verify_fiverr(task_id, args.order_id, args.expected_count)

    elif task_type == "seo-content":
        if not args.client:
            return make_result(task_id, task_type, "UNVERIFIED", "--client required for seo-content")
        return verify_seo_content(task_id, args.client, args.keyword)

    elif task_type == "loop-a":
        if not args.contact_id or not args.tag:
            return make_result(task_id, task_type, "UNVERIFIED", "--contact-id and --tag required for loop-a")
        return verify_loop_a(task_id, args.contact_id, args.tag)

    elif task_type == "landing-page":
        if not args.url:
            return make_result(task_id, task_type, "UNVERIFIED", "--url required for landing-page")
        return verify_landing_page(task_id, args.url)

    elif task_type == "email-sequence":
        if not args.workflow_name:
            return make_result(task_id, task_type, "UNVERIFIED", "--workflow-name required for email-sequence")
        return verify_email_sequence(task_id, args.workflow_name)

    elif task_type == "pdf":
        if not args.workflow_name:
            return make_result(task_id, task_type, "UNVERIFIED", "--workflow-name required for pdf")
        return verify_pdf(task_id, args.workflow_name, args.client or "")

    elif task_type == "consulting":
        if not args.client:
            return make_result(task_id, task_type, "UNVERIFIED", "--client required for consulting")
        return verify_consulting(task_id, args.client)

    elif task_type == "content":
        return verify_content(task_id, args.path)

    elif task_type == "sms-copy":
        if not args.contact_id:
            return make_result(task_id, task_type, "UNVERIFIED", "--contact-id required for sms-copy")
        return verify_sms_copy(task_id, args.contact_id, args.path)

    elif task_type == "code":
        if not args.path:
            return make_result(task_id, task_type, "UNVERIFIED", "--path required for code")
        return verify_code(task_id, args.path, args.launchd_label)

    elif task_type == "daily-summary":
        return verify_daily_summary(task_id)

    else:
        return make_result(task_id, task_type, "UNVERIFIED",
                           f"Unknown task_type: {task_type}")


def from_file(file_path):
    p = Path(os.path.expanduser(file_path))
    if not p.exists():
        result = {
            "task_id": f"unknown-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "task_type": "unknown",
            "status": "UNVERIFIED",
            "evidence": f"Claim file not found: {file_path}",
            "quality_flags": [],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_by": "ryan_verify.py",
            "retry_recommended": True,
        }
        print(json.dumps(result, indent=2))
        write_result(result)
        return result

    with open(p) as f:
        claim = json.load(f)

    task_id = claim.get("task_id", f"unknown-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    task_type = claim.get("task_type", "unknown")
    params = claim.get("params", {})

    # Build a namespace-like object from claim params
    class Args:
        pass

    args = Args()
    args.task_type = task_type
    args.order_id = params.get("order_id")
    args.expected_count = params.get("expected_count")
    args.client = params.get("client")
    args.keyword = params.get("keyword")
    args.contact_id = params.get("contact_id")
    args.tag = params.get("tag")
    args.url = params.get("url")
    args.workflow_name = params.get("workflow_name")
    args.path = params.get("path")
    args.launchd_label = params.get("launchd_label")

    result = dispatch(args)
    # Override task_id with the one from the claim file
    result["task_id"] = task_id
    result["task_type"] = task_type
    return result


def main():
    parser = argparse.ArgumentParser(
        description="ryan_verify.py — Atlas verification authority",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--from-file", metavar="PATH",
                        help="Read task claim from JSON file in verify-inbox/")
    parser.add_argument("--type", dest="task_type",
                        choices=["fiverr", "seo-content", "loop-a", "landing-page",
                                 "email-sequence", "pdf", "consulting", "content",
                                 "sms-copy", "code", "daily-summary"],
                        help="Verification type")
    parser.add_argument("--order-id", help="Fiverr order ID")
    parser.add_argument("--expected-count", type=int, help="Expected file count (fiverr)")
    parser.add_argument("--client", help="Client name (seo-content, consulting, pdf)")
    parser.add_argument("--keyword", help="Target keyword (seo-content)")
    parser.add_argument("--contact-id", help="GHL contact ID (loop-a, sms-copy)")
    parser.add_argument("--tag", help="GHL tag to verify (loop-a)")
    parser.add_argument("--url", help="URL to check (landing-page)")
    parser.add_argument("--workflow-name", help="GHL workflow name (email-sequence, pdf)")
    parser.add_argument("--path", help="File path (content, sms-copy, code)")
    parser.add_argument("--launchd-label", help="launchd label to check (code)")

    args = parser.parse_args()

    if args.from_file:
        result = from_file(args.from_file)
    elif args.task_type:
        result = dispatch(args)
    else:
        parser.print_help()
        sys.exit(0)

    out_path = write_result(result)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
