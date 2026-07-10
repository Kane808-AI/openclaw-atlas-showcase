#!/usr/bin/env python3
"""
inbox_capture.py — Log an idea/capture from Chris to notes/inbox/.

Usage:
    python3 inbox_capture.py --source telegram --from chris --message "..."

Writes ~/.openclaw/workspace/notes/inbox/YYYY-MM-DD-HHMM-<slug>.md with
frontmatter (source, from, created, status: unread) and the raw message
as the body. No processing.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

INBOX_DIR = Path.home() / ".openclaw" / "workspace" / "notes" / "inbox"
SOURCES = {"telegram", "discord"}
FROMS = {"chris", "atlas"}


def slugify(text: str, max_len: int = 40) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    if not text:
        return "capture"
    return text[:max_len].rstrip("-")


def write_capture(source: str, sender: str, message: str) -> Path:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d-%H%M")
    slug = slugify(message)
    path = INBOX_DIR / f"{stamp}-{slug}.md"

    counter = 2
    while path.exists():
        path = INBOX_DIR / f"{stamp}-{slug}-{counter}.md"
        counter += 1

    frontmatter = (
        "---\n"
        f"source: {source}\n"
        f"from: {sender}\n"
        f"created: {now.isoformat(timespec='seconds')}\n"
        "status: unread\n"
        "---\n\n"
    )
    path.write_text(frontmatter + message.rstrip() + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Log a capture to notes/inbox/.")
    parser.add_argument("--source", required=True, choices=sorted(SOURCES))
    parser.add_argument("--from", dest="sender", required=True, choices=sorted(FROMS))
    parser.add_argument("--message", required=True, help="Message body")
    args = parser.parse_args()

    if not args.message.strip():
        print("error: --message is empty", file=sys.stderr)
        return 2

    path = write_capture(args.source, args.sender, args.message)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
