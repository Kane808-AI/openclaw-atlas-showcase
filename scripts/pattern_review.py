#!/usr/bin/env python3
"""
pattern_review.py -- Weekly synthesis of EXPERIENCE_LOG.jsonl into PATTERNS.md.
Runs via launchd (Sunday 8AM) or manually.
Uses Gemini Flash for pattern extraction.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
WORKSPACE = os.path.expanduser("~/.openclaw/workspace")
EXPERIENCE_LOG = os.path.join(WORKSPACE, "memory", "EXPERIENCE_LOG.jsonl")
PATTERNS_MD = os.path.join(WORKSPACE, "memory", "PATTERNS.md")
STATE_FILE = os.path.join(WORKSPACE, "memory", ".pattern_review_state.json")
NOTIFY_SCRIPT = os.path.expanduser("~/.openclaw/scripts/notify-telegram.sh")
ENV_FILE = os.path.expanduser("~/.openclaw/.env")

# ---------------------------------------------------------------------------
# Auth -- load GOOGLE_API_KEY from .env if not already in environment
# ---------------------------------------------------------------------------
if not os.getenv("GOOGLE_API_KEY") and os.path.isfile(ENV_FILE):
    with open(ENV_FILE) as _f:
        for _line in _f:
            if _line.startswith("GOOGLE_API_KEY="):
                os.environ["GOOGLE_API_KEY"] = _line.strip().split("=", 1)[1]
                break

import google.generativeai as genai  # noqa: E402

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state():
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_review_date": None, "last_line_number": 0}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ---------------------------------------------------------------------------
# Read new entries from the experience log
# ---------------------------------------------------------------------------

def read_new_entries(last_line):
    entries = []
    if not os.path.isfile(EXPERIENCE_LOG):
        return entries, 0

    with open(EXPERIENCE_LOG) as f:
        all_lines = f.readlines()

    total_lines = len(all_lines)
    for i, line in enumerate(all_lines[last_line:], start=last_line):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"WARNING: Skipping malformed line {i + 1}: {line[:80]}", file=sys.stderr)

    return entries, total_lines

# ---------------------------------------------------------------------------
# Group entries for summary
# ---------------------------------------------------------------------------

def build_summary(entries):
    groups = defaultdict(lambda: defaultdict(int))
    for e in entries:
        task_type = e.get("task_type", "other")
        outcome = e.get("outcome", "unknown")
        groups[task_type][outcome] += 1

    lines = []
    for task_type, outcomes in sorted(groups.items()):
        parts = [f"{outcome}={count}" for outcome, count in sorted(outcomes.items())]
        lines.append(f"  {task_type}: {', '.join(parts)}")

    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """You are Atlas's pattern synthesis engine. Analyze these task outcomes and update the patterns file.

CURRENT PATTERNS (maintain continuity -- update, don't replace blindly):
{existing_patterns}

NEW ENTRIES SINCE LAST REVIEW ({count} entries, {date_range}):
{summary}

RAW ENTRIES:
{entries_json}

OUTPUT FORMAT -- return ONLY this Markdown, no code fences, no preamble:

# Atlas Patterns -- Last Updated: {today}

## What Works
- [pattern] + [evidence count] + [last seen YYYY-MM-DD]

## What Fails
- [pattern] + [failure type] + [mitigation]

## Open Questions
- Things tried twice with mixed results, needs more data

## Superseded Patterns
- Old beliefs proven wrong, kept for reference

RULES:
- Merge with existing patterns. Increment evidence counts.
- Move patterns from Open Questions to What Works/Fails once you have 3+ consistent data points.
- Move contradicted patterns to Superseded with explanation.
- Keep each bullet to one line. Be specific and actionable.
- If chris_feedback is "reverted" or "modified", that is stronger signal than outcome alone.
- If a section has no entries, write "- (none)" under it.
- Do NOT wrap your output in code fences."""


def call_gemini(prompt, strict=False):
    model = genai.GenerativeModel("gemini-2.5-flash")
    if strict:
        prompt += "\n\nCRITICAL: Return ONLY the raw Markdown. No code fences. No commentary before or after."

    for attempt in range(2):
        try:
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Gemini attempt {attempt + 1} failed: {e}", file=sys.stderr)
            if attempt == 0:
                time.sleep(5)
    return None


def validate_response(text):
    required = ["## What Works", "## What Fails", "## Open Questions", "## Superseded Patterns"]
    return all(section in text for section in required)


def strip_code_fences(text):
    text = re.sub(r"^```(?:markdown)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    return text.strip()

# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------

def notify(message):
    if os.path.isfile(NOTIFY_SCRIPT):
        try:
            subprocess.run(["/bin/bash", NOTIFY_SCRIPT, message], check=True, timeout=15)
        except Exception as e:
            print(f"Telegram notification failed: {e}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Atlas pattern review -- synthesize EXPERIENCE_LOG into PATTERNS.md")
    parser.add_argument("--check-threshold", action="store_true", help="Only run if 25+ new entries since last review")
    parser.add_argument("--force", action="store_true", help="Force run even with zero entries")
    args = parser.parse_args()

    state = load_state()
    last_line = state.get("last_line_number", 0)

    entries, total_lines = read_new_entries(last_line)
    new_count = len(entries)

    print(f"Found {new_count} new entries (lines {last_line + 1} to {total_lines})")

    if new_count == 0 and not args.force:
        print("No new entries. Exiting.")
        return

    if args.check_threshold and new_count < 25:
        print(f"Only {new_count} new entries (threshold: 25). Skipping.")
        return

    # Read existing PATTERNS.md
    existing_patterns = ""
    if os.path.isfile(PATTERNS_MD):
        with open(PATTERNS_MD) as f:
            existing_patterns = f.read()

    # Build prompt
    summary = build_summary(entries)
    timestamps = [e.get("timestamp", "") for e in entries if e.get("timestamp")]
    if timestamps:
        date_range = f"{timestamps[0][:10]} to {timestamps[-1][:10]}"
    else:
        date_range = "unknown"

    # Cap at 100 most recent entries for the raw dump
    capped_entries = entries[-100:] if len(entries) > 100 else entries
    entries_json = "\n".join(json.dumps(e) for e in capped_entries)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = PROMPT_TEMPLATE.format(
        existing_patterns=existing_patterns,
        count=new_count,
        date_range=date_range,
        summary=summary,
        entries_json=entries_json,
        today=today,
    )

    # Call Gemini
    print("Calling Gemini Flash...")
    result = call_gemini(prompt)

    if result is None:
        notify("Pattern review FAILED -- Gemini API error. Will retry next run.")
        print("ERROR: Gemini returned no response after retries.", file=sys.stderr)
        sys.exit(1)

    result = strip_code_fences(result)

    if not validate_response(result):
        print("Response missing required sections. Retrying with strict prompt...", file=sys.stderr)
        result = call_gemini(prompt, strict=True)
        if result is None:
            notify("Pattern review FAILED -- Gemini API error on retry.")
            sys.exit(1)
        result = strip_code_fences(result)
        if not validate_response(result):
            notify("Pattern review FAILED -- Gemini output malformed after 2 attempts.")
            print("ERROR: Response still missing required sections.", file=sys.stderr)
            sys.exit(1)

    # Write PATTERNS.md
    with open(PATTERNS_MD, "w") as f:
        f.write(result + "\n")

    # Update state
    state["last_review_date"] = datetime.now(timezone.utc).isoformat()
    state["last_line_number"] = total_lines
    save_state(state)

    print(f"PATTERNS.md updated. {new_count} entries processed.")
    notify(f"Weekly pattern review complete. {new_count} entries processed.")


if __name__ == "__main__":
    main()
