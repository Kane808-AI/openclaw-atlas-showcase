#!/Users/chriskaneshiro/.openclaw/venv/google/bin/python3
"""
Instagram Reels Backfill — TikTok @papakane808 → Instagram (Feb 20 2026 onward)

Polls TikTok, filters to videos on or after BACKFILL_START_DATE, skips any
already uploaded to Instagram, and publishes each as a Reel via Graph API.
YouTube is NOT touched. This is a one-shot backfill script.

Run manually:
  ~/.openclaw/venv/google/bin/python3 \
    ~/.openclaw/automations/youtube-shorts/instagram_reels_backfill.py
"""

import importlib.util
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Bootstrap: load the main pipeline module ─────────────────────────────────

_PIPELINE = Path.home() / ".openclaw" / "automations" / "youtube-shorts" / "youtube_shorts_pipeline.py"
_spec = importlib.util.spec_from_file_location("pipeline", _PIPELINE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Pull everything we need from the pipeline
poll_tiktok_profile   = _mod.poll_tiktok_profile
download_video        = _mod.download_video
normalize_video       = _mod.normalize_video
transcribe            = _mod.transcribe
generate_copy         = _mod.generate_copy
get_duration          = _mod.get_duration
upload_to_instagram   = _mod.upload_to_instagram
_notify               = _mod._notify
WORK_DIR              = _mod.WORK_DIR
TRACKING_LOG_FILE     = _mod.TRACKING_LOG_FILE
MAX_DURATION_SECS     = _mod.MAX_DURATION_SECS

# ── Backfill config ───────────────────────────────────────────────────────────

AUTOMATION_DIR    = Path.home() / ".openclaw" / "automations" / "youtube-shorts"
IG_UPLOADED_FILE  = AUTOMATION_DIR / ".ig_uploaded_ids"  # TikTok IDs confirmed on Instagram
BACKFILL_START    = "20260220"   # YYYYMMDD — include this date and after
POLL_WINDOW       = 400          # Deep enough to cover Feb 20 to present

# ── Instagram uploaded ID tracking ───────────────────────────────────────────

def load_ig_uploaded() -> set:
    ids = set()
    # Seed from tracking log — any entry with ig_reel_id is already done
    if TRACKING_LOG_FILE.exists():
        for line in TRACKING_LOG_FILE.read_text().splitlines():
            try:
                entry = json.loads(line)
                if entry.get("ig_reel_id"):
                    ids.add(entry["tiktok_id"])
            except Exception:
                pass
    # Also load the backfill-specific file
    if IG_UPLOADED_FILE.exists():
        for line in IG_UPLOADED_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                ids.add(line)
    return ids


def mark_ig_uploaded(tiktok_id: str):
    with open(IG_UPLOADED_FILE, "a") as f:
        f.write(tiktok_id + "\n")


def log_ig_upload(tiktok_id: str, reel_id: str, reel_url: str):
    """Append an Instagram-only entry to tracking_log.jsonl."""
    entry = {
        "tiktok_id": tiktok_id,
        "ig_reel_id": reel_id,
        "ig_url": reel_url,
        "backfill": True,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(TRACKING_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

# ── Date filter ───────────────────────────────────────────────────────────────

def is_on_or_after(upload_date: str, cutoff: str) -> bool:
    """upload_date and cutoff are YYYYMMDD strings. Returns True if date >= cutoff."""
    if not upload_date or len(upload_date) != 8:
        return False  # No date info — skip to be safe
    return upload_date >= cutoff

# ── Per-video backfill ────────────────────────────────────────────────────────

def backfill_video(video_info: dict, ig_uploaded: set) -> bool:
    """Download, normalize, transcribe, and upload one video to Instagram.
    Returns True on success, False on failure."""
    video_id = video_info["id"]
    upload_date = video_info.get("upload_date", "")
    vid_work = WORK_DIR / f"ig_backfill_{video_id}"
    vid_work.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Backfill {video_id}  (TikTok date: {upload_date})")
    print(f"{'='*60}")

    try:
        print("[BF1] Downloading...")
        raw = download_video(video_id, vid_work)

        print("[BF2] Normalizing...")
        clean = vid_work / f"{video_id}_clean.mp4"
        normalize_video(raw, clean)

        dur = get_duration(clean)
        if dur > MAX_DURATION_SECS + 2:
            raise RuntimeError(f"Video {dur:.1f}s > {MAX_DURATION_SECS}s limit")

        print("[BF3] Transcribing...")
        transcript, _ = transcribe(clean)

        print("[BF4] Generating copy...")
        copy = generate_copy(transcript, video_id)

        print("[BF5] Uploading to Instagram...")
        ig = upload_to_instagram(clean, video_id, copy)

        log_ig_upload(video_id, ig["reel_id"], ig["url"])
        mark_ig_uploaded(video_id)
        ig_uploaded.add(video_id)

        _notify(
            f"\u2705 *Instagram Backfill*\n"
            f"TikTok: `{video_id}`\n"
            f"URL: {ig['url']}\n"
            f"Date: {upload_date}"
        )
        print(f"\u2705 {ig['url']}")
        return True

    except Exception as exc:
        import traceback
        print(f"\n\u274c Backfill failed for {video_id}: {exc}")
        traceback.print_exc()
        _notify(
            f"\u274c *Instagram Backfill FAILED*\n"
            f"TikTok: `{video_id}`\n"
            f"Error: {str(exc)[:400]}"
        )
        return False

    finally:
        shutil.rmtree(vid_work, ignore_errors=True)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n[Instagram Backfill] {datetime.now().strftime('%Y-%m-%d %H:%M')} PT")
    print(f"Start date: {BACKFILL_START}  |  Poll window: {POLL_WINDOW} videos")

    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # Poll TikTok
    # Temporarily override POLL_WINDOW on the module
    original_window = _mod.POLL_WINDOW
    _mod.POLL_WINDOW = POLL_WINDOW
    try:
        videos = poll_tiktok_profile()
    finally:
        _mod.POLL_WINDOW = original_window

    if not videos:
        print("[Main] No videos returned from poll.")
        sys.exit(0)

    # Filter to Feb 20 onward
    in_window = [v for v in videos if is_on_or_after(v.get("upload_date", ""), BACKFILL_START)]
    print(f"[Main] {len(in_window)} videos on/after {BACKFILL_START} (of {len(videos)} total)")

    if not in_window:
        print("[Main] Nothing in window.")
        sys.exit(0)

    # Skip already on Instagram
    ig_uploaded = load_ig_uploaded()
    to_upload = [v for v in in_window if v["id"] not in ig_uploaded]
    already_done = len(in_window) - len(to_upload)
    print(f"[Main] {already_done} already on Instagram, {len(to_upload)} to upload")

    if not to_upload:
        print("[Main] All caught up.")
        sys.exit(0)

    _notify(
        f"\u25b6\ufe0f *Instagram Backfill Started*\n"
        f"{len(to_upload)} videos to upload (since {BACKFILL_START})"
    )

    # Process oldest-first so Instagram feed is in chronological order
    to_upload_sorted = sorted(to_upload, key=lambda v: v.get("upload_date", ""))
    succeeded = 0
    failed = 0

    for v in to_upload_sorted:
        ok = backfill_video(v, ig_uploaded)
        if ok:
            succeeded += 1
        else:
            failed += 1
        # Brief pause between uploads to avoid rate limits
        time.sleep(5)

    print(f"\n[Main] Done. {succeeded} uploaded, {failed} failed.")
    _notify(
        f"\u2705 *Instagram Backfill Complete*\n"
        f"Uploaded: {succeeded}  |  Failed: {failed}"
    )


if __name__ == "__main__":
    main()
