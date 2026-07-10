#!/usr/bin/env python3
"""
TikTok Brain Digest — Sends a batched review summary to Telegram 2-3x/week.

Scans recent TikTok Brain Obsidian entries since the last digest,
pulls summaries/tags/ideas, and sends a formatted digest to Chris via Telegram.

Usage:
    python3 digest.py              # Send digest of unreviewed entries
    python3 digest.py --dry-run    # Preview without sending
"""

import os
import sys
import json
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

TIKTOK_BRAIN_DIR = Path.home() / ".openclaw/workspace/notes/ideas/tiktok-brain"
LAST_DIGEST_FILE = Path.home() / ".openclaw/automations/tiktok-brain/.last_digest"
ENV_FILE = Path.home() / ".openclaw/.env"
CHAT_ID = "7556461717"

# Max entries per digest message (Telegram has a 4096 char limit)
MAX_PER_MESSAGE = 5


def get_last_digest_date():
    """Read the timestamp of the last digest sent."""
    if LAST_DIGEST_FILE.exists():
        ts = LAST_DIGEST_FILE.read_text().strip()
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            pass
    return None


def save_last_digest_date():
    """Save current timestamp as last digest."""
    LAST_DIGEST_FILE.write_text(datetime.now().isoformat())


def parse_frontmatter(filepath):
    """Extract YAML frontmatter fields from an Obsidian note."""
    text = filepath.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip().strip('"')

    return meta


def get_unreviewed_entries(since_date=None):
    """Find TikTok Brain entries created since last digest."""
    entries = []
    for f in sorted(TIKTOK_BRAIN_DIR.glob("*.md")):
        if f.name == "INDEX.md":
            continue

        meta = parse_frontmatter(f)
        if not meta or "date" not in meta:
            continue

        try:
            entry_date = datetime.strptime(meta["date"], "%Y-%m-%d")
        except ValueError:
            continue

        if since_date and entry_date <= since_date:
            continue

        entries.append({
            "file": f.name,
            "date": meta.get("date", ""),
            "summary": meta.get("summary", ""),
            "tags": meta.get("tags", ""),
        })

    return entries


def format_digest(entries):
    """Format entries into Telegram-friendly messages."""
    if not entries:
        return []

    messages = []
    header = (
        f"TikTok Brain Digest — {datetime.now().strftime('%b %d, %Y')}\n"
        f"{len(entries)} new video(s) processed since last review.\n"
        f"Google Docs with full transcripts + reviews are in Drive.\n\n"
    )

    current_msg = header
    count = 0

    for entry in entries:
        block = f"({entry['tags']})\n{entry['summary']}\n\n"

        # Check Telegram message length limit
        if len(current_msg) + len(block) > 3800 or count >= MAX_PER_MESSAGE:
            messages.append(current_msg.rstrip())
            current_msg = f"(continued)\n\n"
            count = 0

        current_msg += block
        count += 1

    if current_msg.strip():
        current_msg += "Reply here to discuss any of these or flag one for the plan."
        messages.append(current_msg.rstrip())

    return messages


def _load_bot_token():
    """Read TELEGRAM_BOT_TOKEN from .env without sourcing the whole file."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.getenv("TELEGRAM_BOT_TOKEN")


def send_telegram(message):
    """Send a message via Telegram Bot API."""
    token = _load_bot_token()
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not found in .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message,
    }).encode()

    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                print(f"ERROR: Telegram API returned: {result}")
                return False
        return True
    except Exception as e:
        print(f"ERROR: Telegram send failed: {e}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv

    last_date = get_last_digest_date()
    entries = get_unreviewed_entries(since_date=last_date)

    if not entries:
        print("No new TikTok Brain entries since last digest.")
        return

    print(f"Found {len(entries)} new entries since {last_date or 'beginning'}")

    messages = format_digest(entries)

    for i, msg in enumerate(messages):
        if dry_run:
            print(f"\n--- Message {i+1} ---")
            print(msg)
        else:
            print(f"Sending message {i+1}/{len(messages)}...")
            if not send_telegram(msg):
                print("Stopping due to send failure.")
                return

    if not dry_run:
        save_last_digest_date()
        print("Digest sent. Last digest timestamp updated.")


if __name__ == "__main__":
    main()
