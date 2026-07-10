#!/Users/chriskaneshiro/.openclaw/venv/google/bin/python3
"""
Instagram recovery script — re-posts to Instagram for TikTok IDs that uploaded to
YouTube but missed Instagram. Appends backfill-style entries to tracking_log.jsonl.

Usage:
  python3 recover_instagram.py                    # auto-detect from last 7 days
  python3 recover_instagram.py 7634299554367687949 7624620601268899086
  python3 recover_instagram.py --dry-run          # show what would be recovered

Will NOT re-post if tracking_log already contains an ig_reel_id for that tiktok_id.
Will NOT remove or re-process .processed_ids (YouTube is untouched).
"""

import json
import sys
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

AUTOMATION_DIR = Path.home() / ".openclaw" / "automations" / "youtube-shorts"
TRACKING_LOG_FILE = AUTOMATION_DIR / "tracking_log.jsonl"
WORK_DIR = Path.home() / ".openclaw" / "workspace" / "tmp" / "youtube-shorts-recovery"

sys.path.insert(0, str(Path.home() / ".openclaw" / "scripts"))
sys.path.insert(0, str(AUTOMATION_DIR))

from youtube_shorts_pipeline import (
    _load_env,
    download_video,
    normalize_video,
    _trim_for_instagram,
    get_duration,
    upload_to_instagram,
    notify_ig_success,
    notify_ig_failure,
    IG_MAX_DURATION_SECS,
)

_load_env()


def load_tracking() -> dict:
    """Returns dict: tiktok_id -> {yt: entry_or_None, ig: entry_or_None}"""
    by_id = {}
    if not TRACKING_LOG_FILE.exists():
        return by_id
    with open(TRACKING_LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            tid = e["tiktok_id"]
            if tid not in by_id:
                by_id[tid] = {"yt": None, "ig": None, "title": ""}
            if "yt_video_id" in e:
                by_id[tid]["yt"] = e
                by_id[tid]["title"] = e.get("title", "")
            if "ig_reel_id" in e:
                by_id[tid]["ig"] = e
    return by_id


def find_recent_yt_only(days: int = 7) -> list[dict]:
    """Return tracking entries that have YouTube but no Instagram, uploaded within `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    by_id = load_tracking()
    result = []
    for tid, rec in by_id.items():
        if rec["yt"] and not rec["ig"]:
            uploaded_str = rec["yt"].get("uploaded_at", "")
            try:
                uploaded = datetime.fromisoformat(uploaded_str)
                if uploaded >= cutoff:
                    result.append(rec["yt"])
            except ValueError:
                pass
    return sorted(result, key=lambda x: x["uploaded_at"])


def append_ig_backfill(tiktok_id: str, ig_reel_id: str, ig_url: str, ig_error: str | None = None):
    entry: dict = {
        "tiktok_id": tiktok_id,
        "backfill": True,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    if ig_reel_id:
        entry["ig_reel_id"] = ig_reel_id
        entry["ig_url"] = ig_url
    if ig_error:
        entry["ig_error"] = ig_error
    with open(TRACKING_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[Log] Appended backfill entry for {tiktok_id}")


def recover_one(yt_entry: dict, dry_run: bool = False) -> bool:
    tiktok_id = yt_entry["tiktok_id"]
    title = yt_entry.get("title", "(no title)")
    yt_url = yt_entry.get("yt_url", "")

    print(f"\n{'='*60}")
    print(f"Recovering Instagram for TikTok {tiktok_id}")
    print(f"  Title: {title}")
    print(f"  YouTube: {yt_url}")
    print(f"{'='*60}")

    if dry_run:
        print("[DRY RUN] Would download, normalize, and post to Instagram.")
        return True

    vid_work = WORK_DIR / tiktok_id
    vid_work.mkdir(parents=True, exist_ok=True)

    copy = {
        "title": title,
        "description": (
            f"{title}\n\n"
            "Follow @papakane808 for daily AI building content. "
            "Drop a comment with your biggest AI question."
        ),
        "tags": ["openclaw", "aiautomation", "claudeai", "claudecode",
                 "aiagent", "youtubeShorts", "AItools", "automation", "aibuilder"],
    }

    ig_temp = None
    try:
        print("[Step 1] Downloading from TikTok...")
        raw = download_video(tiktok_id, vid_work)
        print(f"[Step 1] Downloaded: {raw.name}")

        print("[Step 2] Normalizing to 1080x1920...")
        clean = vid_work / f"{tiktok_id}_clean.mp4"
        normalize_video(raw, clean)

        dur = get_duration(clean)
        print(f"[Step 2] Duration: {dur:.1f}s")

        if dur > IG_MAX_DURATION_SECS:
            ig_temp = vid_work / f"{tiktok_id}_ig.mp4"
            print(f"[Step 3] Trimming to {IG_MAX_DURATION_SECS}s for Instagram...")
            _trim_for_instagram(clean, ig_temp)
            ig_video = ig_temp
        else:
            ig_video = clean

        print("[Step 4] Uploading to Instagram Reels...")
        ig_result = upload_to_instagram(ig_video, tiktok_id, copy)
        notify_ig_success(tiktok_id, ig_result["url"])

        append_ig_backfill(tiktok_id, ig_result["reel_id"], ig_result["url"])
        print(f"\n✅ Recovered: {ig_result['url']}")
        return True

    except Exception as e:
        print(f"\n❌ Recovery failed for {tiktok_id}: {e}")
        notify_ig_failure(tiktok_id, "recover_instagram.py", str(e))
        append_ig_backfill(tiktok_id, "", "", ig_error=str(e)[:500])
        return False

    finally:
        if ig_temp and ig_temp.exists():
            ig_temp.unlink(missing_ok=True)
        shutil.rmtree(vid_work, ignore_errors=True)


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in sys.argv

    by_id = load_tracking()

    if args:
        targets = []
        for tid in args:
            if tid not in by_id or not by_id[tid]["yt"]:
                print(f"[SKIP] {tid} — no YouTube entry found in tracking log")
                continue
            if by_id[tid]["ig"]:
                print(f"[SKIP] {tid} — Instagram already posted: {by_id[tid]['ig'].get('ig_url')}")
                continue
            targets.append(by_id[tid]["yt"])
    else:
        targets = find_recent_yt_only(days=7)
        if not targets:
            print("No recent YouTube-only entries found (last 7 days). Nothing to recover.")
            return

    if not targets:
        print("Nothing to recover.")
        return

    print(f"\nRecovering {len(targets)} Instagram post(s){'  [DRY RUN]' if dry_run else ''}:")
    for t in targets:
        print(f"  {t['tiktok_id']}  {t.get('uploaded_at','')[:10]}  {t.get('title','')[:60]}")

    success = 0
    fail = 0
    for yt_entry in targets:
        if recover_one(yt_entry, dry_run=dry_run):
            success += 1
        else:
            fail += 1

    print(f"\n[Done] {success} recovered, {fail} failed.")


if __name__ == "__main__":
    main()
