#!/usr/bin/env python3
"""
log_experience.py -- Append one entry to EXPERIENCE_LOG.jsonl.
Called by Atlas/sub-agents after completing Tier 2+ tasks.

Usage:
  python3 log_experience.py --task_type lead_scrape --agent atlas \
    --summary "Scraped 50 leads from Avvo" --outcome success \
    --notes "Pagination worked with 2s delay"

  Optional flags:
    --failure_reason "reason string"
    --chris_feedback approved|reverted|modified|no_response (default: no_response)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

LOG_FILE = os.path.expanduser("~/.openclaw/workspace/memory/EXPERIENCE_LOG.jsonl")

VALID_TASK_TYPES = ["lead_scrape", "content_draft", "wave_reconcile", "outreach", "other"]
VALID_AGENTS = ["atlas", "nova", "leo", "echo", "muse", "kai", "koa", "ryan", "alex", "aura", "scout"]
VALID_OUTCOMES = ["success", "partial", "failure"]
VALID_FEEDBACK = ["approved", "reverted", "modified", "no_response"]


def main():
    parser = argparse.ArgumentParser(description="Log a task outcome to EXPERIENCE_LOG.jsonl")
    parser.add_argument("--task_type", required=True, choices=VALID_TASK_TYPES)
    parser.add_argument("--agent", required=True, choices=VALID_AGENTS)
    parser.add_argument("--summary", required=True, help="One sentence describing what was attempted")
    parser.add_argument("--outcome", required=True, choices=VALID_OUTCOMES)
    parser.add_argument("--failure_reason", default=None, help="Brief reason if outcome is partial or failure")
    parser.add_argument("--chris_feedback", default="no_response", choices=VALID_FEEDBACK)
    parser.add_argument("--notes", default=None, help="Anything for future reference")
    args = parser.parse_args()

    if not args.summary.strip():
        print("ERROR: --summary cannot be empty", file=sys.stderr)
        sys.exit(1)

    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "task_type": args.task_type,
        "agent": args.agent,
        "summary": args.summary.strip(),
        "outcome": args.outcome,
        "failure_reason": args.failure_reason,
        "chris_feedback": args.chris_feedback,
        "notes": args.notes,
    }

    line = json.dumps(entry, ensure_ascii=False)

    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

    print(f"Logged: {args.outcome} | {args.task_type} | {args.agent}")


if __name__ == "__main__":
    main()
