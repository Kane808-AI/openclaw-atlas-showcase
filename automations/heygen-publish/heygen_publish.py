#!/Users/chriskaneshiro/.openclaw/venv/google/bin/python3
"""
HeyGen → Edit → Publish Pipeline (Format 3)

Accepts a script, generates a HeyGen avatar video, burns TikTok-style word-by-word
captions via PIL+ffmpeg (no libass), and publishes to YouTube Shorts + Instagram Reels.

Usage:
    python3 heygen_publish.py \
        --script "Hey everyone, check out this kitchen gadget..." \
        --avatar <avatar_id> \
        --voice <voice_id> \
        --title "This $19 Gadget Changed My Kitchen" \
        --description "Amazon link in bio" \
        --tags "kitchen,gadget,amazon" \
        [--dry-run [--test-video /path/to/test.mp4]]
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────

AUTOMATION_DIR = Path.home() / ".openclaw" / "automations" / "heygen-publish"
WORK_DIR = AUTOMATION_DIR / "tmp"
LOG_FILE = AUTOMATION_DIR / "publish_log.jsonl"
ENV_FILE = Path.home() / ".openclaw" / ".env"
HEYGEN_JS = Path.home() / ".openclaw" / "workspace" / "skills" / "heygen" / "heygen.js"
YOUTUBE_PIPELINE = (
    Path.home() / ".openclaw" / "automations" / "youtube-shorts" / "youtube_shorts_pipeline.py"
)
TELEGRAM_TOKEN_FILE = Path.home() / ".openclaw" / "secrets" / "telegram-bot-token"
TELEGRAM_CHAT_ID = "7556461717"

FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
FFPROBE_BIN = "/opt/homebrew/bin/ffprobe"
NODE_BIN = "/opt/homebrew/bin/node"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

# Caption style
CAPTION_WORDS_PER_GROUP = 3
FONT_SIZE = 80
CAPTION_Y_RATIO = 0.72  # bottom third

# ── Env loading ────────────────────────────────────────────────────────────────

def _load_env():
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_env()

# ── Telegram ───────────────────────────────────────────────────────────────────

def _send_telegram(text: str, chat_id: str = TELEGRAM_CHAT_ID):
    try:
        token = TELEGRAM_TOKEN_FILE.read_text().strip()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }).encode()
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:
            resp.read()
        print("[Telegram] Notification sent")
    except Exception as e:
        print(f"[WARN] Telegram notify failed: {e}", file=sys.stderr)

# ── HeyGen API ─────────────────────────────────────────────────────────────────

def heygen_generate(script: str, avatar_id: str, voice_id: str, title: str) -> str:
    """Call heygen.js generate; returns video_id."""
    env = {**os.environ}
    result = subprocess.run(
        [
            NODE_BIN, str(HEYGEN_JS), "generate",
            "--script", script,
            "--avatar", avatar_id,
            "--voice", voice_id,
            "--title", title,
            "--aspect", "9:16",
            "--no-caption",  # We burn our own captions
        ],
        capture_output=True, text=True, timeout=60, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"HeyGen generate failed:\n{result.stderr[:500]}")
    for line in result.stdout.splitlines():
        if "Video queued:" in line:
            return line.split("Video queued:")[-1].strip()
    raise RuntimeError(f"Could not parse video_id from HeyGen output:\n{result.stdout[:400]}")


def heygen_wait_and_download(video_id: str, output_dir: Path) -> Path:
    """Poll HeyGen status until completed; download and return local MP4 path."""
    env = {**os.environ}
    max_wait_secs = 600
    poll_secs = 15
    start = time.time()

    while time.time() - start < max_wait_secs:
        result = subprocess.run(
            [NODE_BIN, str(HEYGEN_JS), "status", video_id],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"HeyGen status failed:\n{result.stderr[:300]}")

        status = "unknown"
        video_url = None
        for line in result.stdout.splitlines():
            if "== Status:" in line:
                status = line.split("== Status:")[-1].replace("==", "").strip()
            if "Video URL:" in line:
                video_url = line.split("Video URL:")[-1].strip()

        elapsed = int(time.time() - start)
        print(f"  HeyGen: {status} ({elapsed}s)")

        if status == "completed":
            if not video_url:
                raise RuntimeError("HeyGen completed but no video URL in response")
            dest = output_dir / f"heygen_{video_id[:8]}.mp4"
            print(f"  Downloading to {dest}...")
            urllib.request.urlretrieve(video_url, str(dest))
            return dest

        if status == "failed":
            raise RuntimeError(f"HeyGen video generation failed: {video_id}")

        time.sleep(poll_secs)

    raise RuntimeError(f"Timed out waiting for HeyGen video {video_id} (10min)")

# ── Video utilities ────────────────────────────────────────────────────────────

def get_duration(video_path: Path) -> float:
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    result.check_returncode()
    return float(json.loads(result.stdout)["format"]["duration"])


def get_dimensions(video_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
         "-show_streams", "-select_streams", "v:0", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    result.check_returncode()
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise RuntimeError("No video stream found")
    return streams[0]["width"], streams[0]["height"]


def ensure_9_16(input_path: Path, output_path: Path) -> Path:
    """Scale-pad to 1080x1920. Returns output_path."""
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
    )
    cmd = [
        FFMPEG_BIN, "-y", "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-preset", "fast",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed:\n{result.stderr[-600:]}")
    return output_path

# ── Transcription ──────────────────────────────────────────────────────────────

def transcribe_with_words(video_path: Path) -> list[dict]:
    """
    Transcribe using faster-whisper with word-level timestamps.
    Returns: [{"word": str, "start": float, "end": float}, ...]
    """
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(video_path), beam_size=5, word_timestamps=True)

    words = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                cleaned = w.word.strip()
                if cleaned:
                    words.append({"word": cleaned, "start": w.start, "end": w.end})
    return words

# ── Caption rendering — PIL + ffmpeg overlay, no libass ───────────────────────

def _group_words_into_captions(words: list[dict]) -> list[dict]:
    """Group word list into CAPTION_WORDS_PER_GROUP-word chunks with timing."""
    groups = []
    for i in range(0, len(words), CAPTION_WORDS_PER_GROUP):
        chunk = words[i : i + CAPTION_WORDS_PER_GROUP]
        if not chunk:
            continue
        groups.append({
            "text": " ".join(w["word"] for w in chunk),
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
        })
    return groups


def _load_caption_font():
    """Load Arial Bold or the best available fallback for TikTok-style captions."""
    from PIL import ImageFont

    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for fp in candidates:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, FONT_SIZE)
            except Exception:
                pass
    return ImageFont.load_default()


def _render_caption_image(text: str, tmp_dir: Path, idx: int) -> Path:
    """
    Render one caption group as a transparent RGBA PNG.
    White bold text, black outline stroke, centered in the bottom third.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_caption_font()

    # Measure — use textbbox to account for font metrics
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (VIDEO_WIDTH - text_w) // 2
    y = int(VIDEO_HEIGHT * CAPTION_Y_RATIO) - text_h // 2

    # Thick black stroke (draw offsets in 8 directions)
    stroke = 4
    for dx in range(-stroke, stroke + 1):
        for dy in range(-stroke, stroke + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))

    # White fill on top
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    out = tmp_dir / f"cap_{idx:04d}.png"
    img.save(str(out), "PNG")
    return out


def burn_captions(input_path: Path, output_path: Path, words: list[dict]) -> Path:
    """
    Burn TikTok-style captions onto video.
    Uses PIL to render each caption group as a transparent PNG, then
    chains ffmpeg overlay filters — one overlay per caption window.
    No libass required.
    """
    if not words:
        shutil.copy2(str(input_path), str(output_path))
        return output_path

    tmp_caps = output_path.parent / "cap_frames"
    tmp_caps.mkdir(exist_ok=True)

    try:
        groups = _group_words_into_captions(words)
        print(f"  Rendering {len(groups)} caption images...")

        cap_entries = []
        for i, grp in enumerate(groups):
            img_path = _render_caption_image(grp["text"], tmp_caps, i)
            cap_entries.append((img_path, grp["start"], grp["end"]))

        # Build ffmpeg command:
        # Input 0 = video; inputs 1..N = caption PNGs
        # Filter: chain overlays, each enabled only during its time window
        inputs = ["-i", str(input_path)]
        for img_path, _, _ in cap_entries:
            inputs += ["-i", str(img_path)]

        prev = "0:v"
        filter_parts = []
        for idx, (_, start, end) in enumerate(cap_entries):
            inp_idx = idx + 1
            out_label = f"ov{idx}"
            filter_parts.append(
                f"[{prev}][{inp_idx}:v]"
                f"overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'"
                f"[{out_label}]"
            )
            prev = out_label

        filter_complex = ";".join(filter_parts)

        cmd = [
            FFMPEG_BIN, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[{prev}]",
            "-map", "0:a?",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-preset", "fast",
            str(output_path),
        ]

        print(f"  Running ffmpeg caption overlay ({len(cap_entries)} overlays)...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg caption burn failed:\n{result.stderr[-800:]}")

        return output_path
    finally:
        shutil.rmtree(tmp_caps, ignore_errors=True)

# ── Import upload functions from existing pipeline (no duplication) ────────────

def _load_pipeline_module():
    """Dynamically import youtube_shorts_pipeline to reuse upload_to_youtube/instagram."""
    spec = importlib.util.spec_from_file_location("yt_pipeline", str(YOUTUBE_PIPELINE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# ── Publish log ────────────────────────────────────────────────────────────────

def _log_run(entry: dict):
    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(
    script: str,
    avatar_id: str,
    voice_id: str,
    title: str,
    description: str,
    tags: list[str],
    dry_run: bool = False,
    test_video: str | None = None,
):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    work_dir = WORK_DIR / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "script_snippet": script[:120],
        "avatar": avatar_id,
        "voice": voice_id,
        "title": title,
        "dry_run": dry_run,
    }

    try:
        # ── Step 1: HeyGen generate + download ────────────────────────────────
        if dry_run and test_video:
            print(f"[Step 1] DRY-RUN: skipping HeyGen — using test video: {test_video}")
            raw_video = Path(test_video)
            if not raw_video.exists():
                raise RuntimeError(f"Test video not found: {test_video}")
        else:
            print("[Step 1] Generating HeyGen avatar video...")
            video_id = heygen_generate(script, avatar_id, voice_id, title)
            print(f"[Step 1] Queued: {video_id}")
            print("[Step 1] Waiting for HeyGen to render (polls every 15s)...")
            raw_video = heygen_wait_and_download(video_id, work_dir)
            print(f"[Step 1] Downloaded: {raw_video}")

        # ── Step 2: Verify/ensure 1080x1920 ──────────────────────────────────
        print("[Step 2] Checking dimensions...")
        w, h = get_dimensions(raw_video)
        if w == VIDEO_WIDTH and h == VIDEO_HEIGHT:
            print(f"[Step 2] Already {w}x{h} — no resize needed")
            normalized = raw_video
        else:
            print(f"[Step 2] Resizing from {w}x{h} to {VIDEO_WIDTH}x{VIDEO_HEIGHT}")
            normalized = work_dir / "normalized.mp4"
            ensure_9_16(raw_video, normalized)
            print(f"[Step 2] Normalized: {normalized}")

        # ── Step 3: Transcribe with word timestamps ───────────────────────────
        print("[Step 3] Transcribing with faster-whisper (word-level timestamps)...")
        try:
            words = transcribe_with_words(normalized)
            print(f"[Step 3] {len(words)} words transcribed")
        except Exception as e:
            print(f"[Step 3] Transcription failed ({e}) — no captions will be burned")
            words = []

        # ── Step 4: Burn TikTok-style captions ───────────────────────────────
        captioned = work_dir / "captioned.mp4"
        if words:
            print(f"[Step 4] Burning captions ({CAPTION_WORDS_PER_GROUP} words/group, PIL+ffmpeg)...")
            burn_captions(normalized, captioned, words)
            print(f"[Step 4] Done: {captioned}")
        else:
            print("[Step 4] No transcript — skipping caption burn")
            captioned = normalized

        # ── Step 5: Publish ───────────────────────────────────────────────────
        copy = {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags,
        }
        yt_url = None
        ig_url = None

        if dry_run:
            print("[Step 5] DRY-RUN: skipping YouTube + Instagram upload")
            yt_url = "https://youtube.com/shorts/DRY_RUN_ID"
            ig_url = "https://www.instagram.com/reel/DRY_RUN_ID/"
            print(f"[Step 5] Would upload: {captioned}")
        else:
            pipeline = _load_pipeline_module()

            print("[Step 5] Uploading to YouTube Shorts...")
            yt = pipeline.upload_to_youtube(captioned, None, copy)
            yt_url = yt["url"]
            print(f"[Step 5] YouTube: {yt_url}")

            print("[Step 5b] Uploading to Instagram Reels...")
            try:
                ig_result = pipeline.upload_to_instagram(captioned, run_id, copy)
                ig_url = ig_result["url"]
                print(f"[Step 5b] Instagram: {ig_url}")
            except Exception as e:
                print(f"[Step 5b] Instagram upload failed (non-fatal): {e}")

        # ── Step 6: Telegram notification ─────────────────────────────────────
        notify_lines = [
            "*HeyGen Pipeline Complete*",
            f"Title: {title}",
            f"Script: _{script[:80]}..._" if len(script) > 80 else f"Script: _{script}_",
            "",
            f"YouTube: {yt_url}",
            f"Instagram: {ig_url or '(not uploaded)'}",
            "",
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M PT')}",
        ]
        notify_text = "\n".join(notify_lines)

        if not dry_run:
            _send_telegram(notify_text)
        else:
            print(f"\n[Step 6] DRY-RUN: Telegram notification (not sent):\n{'─'*50}")
            print(notify_text)
            print("─" * 50)

        # ── Step 7: Log ───────────────────────────────────────────────────────
        log_entry["yt_url"] = yt_url
        log_entry["ig_url"] = ig_url
        log_entry["status"] = "success"
        _log_run(log_entry)
        print(f"\n[Step 7] Logged to {LOG_FILE}")
        print(f"[Done] {yt_url}")

    except Exception as exc:
        import traceback
        print(f"\n[FAILED] {exc}")
        traceback.print_exc()
        log_entry["status"] = "failed"
        log_entry["error"] = str(exc)
        _log_run(log_entry)
        if not dry_run:
            _send_telegram(
                f"*HeyGen Pipeline FAILED*\n"
                f"Title: {title}\n"
                f"Error: {str(exc)[:300]}"
            )
        sys.exit(1)
    finally:
        if not dry_run:
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            print(f"\n[DRY-RUN] Work dir preserved: {work_dir}")

# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=(
            "HeyGen → Edit → Publish: generate avatar video, "
            "burn captions, publish to YouTube Shorts + Instagram Reels"
        )
    )
    parser.add_argument("--script", required=True, help="Script text for the avatar")
    parser.add_argument("--avatar", required=True, help="HeyGen avatar ID")
    parser.add_argument("--voice", required=True, help="HeyGen voice ID")
    parser.add_argument("--title", default="AI Video", help="Video title (max 100 chars)")
    parser.add_argument("--description", default="", help="Video description")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip HeyGen API call and uploads; proves the full chain with a test video",
    )
    parser.add_argument(
        "--test-video", default=None,
        help="Path to test MP4 to use instead of calling HeyGen (requires --dry-run)",
    )

    args = parser.parse_args()

    if args.test_video and not args.dry_run:
        parser.error("--test-video requires --dry-run")

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)

    run_pipeline(
        script=args.script,
        avatar_id=args.avatar,
        voice_id=args.voice,
        title=args.title,
        description=args.description,
        tags=tags,
        dry_run=args.dry_run,
        test_video=args.test_video,
    )


if __name__ == "__main__":
    main()
