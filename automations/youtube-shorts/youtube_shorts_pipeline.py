#!/Users/chriskaneshiro/.openclaw/venv/google/bin/python3
"""
YouTube Shorts + Instagram Reels Pipeline — @papakane808 TikTok → YouTube + Instagram

Polls @papakane808 every 2 hours (via cron), downloads new videos,
normalizes for Shorts/Reels (1080x1920, ≤180s YT / ≤90s IG), transcribes, generates copy
via Gemini, uploads to YouTube Data API v3, and publishes to Instagram Reels
via Graph API (staged through GCS).

Steps:
  1  Poll TikTok profile for recent video IDs
  2  Skip already-processed IDs
  3  Verify video still exists (grace period check for very new videos)
  4  Download watermark-free via yt-dlp
  5  Normalize: 1080x1920, ≤180s (YT) / ≤90s (IG), H.264, yuv420p, AAC, faststart
  6  Transcribe with faster-whisper → SRT saved locally (for copy generation)
  7  Extract 3 thumbnail candidates
  8  Generate copy: title, description, tags (Gemini + Muse templates)
  9  Upload clean normalized MP4 to YouTube (auto-captions handle subtitles)
  9b Upload same normalized MP4 (or 90s-trimmed copy) to Instagram Reels (staged via GCS)
 10  Log YouTube + Instagram IDs/URLs
 11  Telegram success/failure alerts
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add scripts dir for google_auth + other shared utils
sys.path.insert(0, str(Path.home() / ".openclaw" / "scripts"))

# ── Config ────────────────────────────────────────────────────────────────────

AUTOMATION_DIR = Path.home() / ".openclaw" / "automations" / "youtube-shorts"
PROCESSED_IDS_FILE = AUTOMATION_DIR / ".processed_ids"
FAILED_IDS_FILE    = AUTOMATION_DIR / ".failed_ids"
TRACKING_LOG_FILE = AUTOMATION_DIR / "tracking_log.jsonl"
COPY_TEMPLATES_FILE = AUTOMATION_DIR / "youtube_copy_templates.json"
WORK_DIR = Path.home() / ".openclaw" / "workspace" / "tmp" / "youtube-shorts"
LOCK_FILE = AUTOMATION_DIR / ".pipeline.lock"
ATTEMPTS_FILE = AUTOMATION_DIR / ".attempts.json"
PLAYLIST_FILE = AUTOMATION_DIR / ".playlist_id"
MAX_ATTEMPTS = 3  # Stop retrying a video after this many failures
POLL_WINDOW = 200  # Videos to fetch from profile (covers ~6 months at 1/day)
YOUTUBE_QUOTA_PER_UPLOAD = 1650  # videos.insert (1600) + thumbnails.set (50)
YOUTUBE_DAILY_QUOTA = 10000
NOTIFY_SCRIPT = str(Path.home() / ".openclaw" / "scripts" / "notify-telegram.sh")
ENV_FILE = Path.home() / ".openclaw" / ".env"

TIKTOK_PROFILE = "https://www.tiktok.com/@papakane808"
YTDLP_BIN = "/opt/homebrew/bin/yt-dlp"
FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
FFPROBE_BIN = "/opt/homebrew/bin/ffprobe"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
MAX_DURATION_SECS = 175   # YouTube Shorts cap is 180s; trim to 175s for safety margin so re-mux rounding can't push it over and demote to a regular video
IG_MAX_DURATION_SECS = 90  # Instagram Reels Graph API limit
NEW_VIDEO_GRACE_SECS = 30 * 60  # 30 minutes
MAX_VIDEO_AGE_DAYS = 3  # Skip TikTok videos older than this (don't backfill old content)

# ── Instagram / GCS config ─────────────────────────────────────────────────────

IG_API_BASE = "https://graph.facebook.com/v21.0"
IG_GCS_BUCKET = "openclaw-instagram-staging"
IG_GCS_PROJECT = "openclaw-brand75-488404"
IG_SA_FILE = Path.home() / ".openclaw" / "credentials" / "google" / "brand75-service-account.json"
IG_CONTAINER_TIMEOUT_SECS = 600   # 10 min max wait for Instagram to process container (bumped from 300 — intermittent timeout failures)
IG_CONTAINER_POLL_SECS = 10
IG_CAPTION_MAX = 2200

# ── Load .env ─────────────────────────────────────────────────────────────────

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

# ── Telegram ──────────────────────────────────────────────────────────────────

def _notify(message: str):
    try:
        subprocess.run([NOTIFY_SCRIPT, message], timeout=15, check=False)
    except Exception as e:
        print(f"[WARN] Telegram notify failed: {e}", file=sys.stderr)


def notify_success(tiktok_id: str, title: str, yt_url: str):
    _notify(
        f"\u2705 *YouTube Shorts Upload*\n"
        f"TikTok: `{tiktok_id}`\n"
        f"Title: {title}\n"
        f"URL: {yt_url}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M PT')}"
    )


def notify_failure(tiktok_id: str, step: str, error: str):
    _notify(
        f"\u274c *YouTube Shorts FAILED*\n"
        f"TikTok: `{tiktok_id}`\n"
        f"Step: {step}\n"
        f"Error: {str(error)[:400]}"
    )


def notify_ig_success(tiktok_id: str, reel_url: str):
    _notify(
        f"\u2705 *Instagram Reels Upload*\n"
        f"TikTok: `{tiktok_id}`\n"
        f"URL: {reel_url}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M PT')}"
    )


def notify_ig_failure(tiktok_id: str, step: str, error: str):
    _notify(
        f"\u274c *Instagram Reels FAILED*\n"
        f"TikTok: `{tiktok_id}`\n"
        f"Step: {step}\n"
        f"Error: {str(error)[:400]}"
    )

# ── Processed IDs ─────────────────────────────────────────────────────────────

def load_processed_ids() -> set:
    if not PROCESSED_IDS_FILE.exists():
        return set()
    return {line.strip() for line in PROCESSED_IDS_FILE.read_text().splitlines() if line.strip()}


def mark_processed(video_id: str):
    with open(PROCESSED_IDS_FILE, "a") as f:
        f.write(video_id + "\n")
    _unmark_failed(video_id)


def load_failed_ids() -> set:
    if not FAILED_IDS_FILE.exists():
        return set()
    return {line.strip() for line in FAILED_IDS_FILE.read_text().splitlines() if line.strip()}


def mark_failed(video_id: str):
    failed = load_failed_ids()
    if video_id not in failed:
        with open(FAILED_IDS_FILE, "a") as f:
            f.write(video_id + "\n")


def load_successful_youtube_ids() -> set:
    """Return set of TikTok IDs that have a confirmed successful YouTube upload
    in the tracking log. This is the AUTHORITATIVE dedup source — prevents
    retry-until-duplicate bugs that .processed_ids alone can't catch."""
    if not TRACKING_LOG_FILE.exists():
        return set()
    successful = set()
    with open(TRACKING_LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("yt_video_id"):
                    successful.add(entry["tiktok_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return successful


def _unmark_failed(video_id: str):
    if not FAILED_IDS_FILE.exists():
        return
    failed = load_failed_ids()
    if video_id in failed:
        failed.discard(video_id)
        FAILED_IDS_FILE.write_text("".join(f"{v}\n" for v in sorted(failed)))

# ── Concurrency lock ──────────────────────────────────────────────────────────

def acquire_lock() -> bool:
    """Return True if this process acquired the lock, False if another run is active."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if that PID is still alive
            os.kill(pid, 0)
            return False  # Process is alive — another run is in progress
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # Stale lock — previous run crashed; take it
    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass

# ── Attempt tracker ───────────────────────────────────────────────────────────

def _load_attempts() -> dict:
    if not ATTEMPTS_FILE.exists():
        return {}
    try:
        return json.loads(ATTEMPTS_FILE.read_text())
    except Exception:
        return {}


def _save_attempts(data: dict):
    ATTEMPTS_FILE.write_text(json.dumps(data, indent=2))


def record_attempt(video_id: str) -> int:
    """Increment attempt count for video_id. Returns new count."""
    data = _load_attempts()
    data[video_id] = data.get(video_id, 0) + 1
    _save_attempts(data)
    return data[video_id]


def get_attempts(video_id: str) -> int:
    return _load_attempts().get(video_id, 0)

class QuotaExceededError(Exception):
    """Raised when the YouTube API daily quota is exhausted."""

# ── Step 1: Poll TikTok profile ───────────────────────────────────────────────

def poll_tiktok_profile() -> list[dict]:
    """Return up to POLL_WINDOW recent videos as [{id, upload_date, title}]."""
    print(f"[Step 1] Polling @papakane808 TikTok profile (last {POLL_WINDOW} videos)...")
    result = subprocess.run(
        [
            YTDLP_BIN,
            "--flat-playlist",
            "--print", "%(id)s\t%(upload_date)s\t%(title)s",
            "--no-download",
            "--playlist-items", f"1-{POLL_WINDOW}",
            "--cookies-from-browser", "chrome",
            TIKTOK_PROFILE,
        ],
        capture_output=True,
        text=True,
        timeout=240,  # larger window needs more time
    )
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp profile poll failed: {result.stderr[:400]}")

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 2)
        if parts and parts[0].strip():
            videos.append({
                "id": parts[0].strip(),
                "upload_date": parts[1].strip() if len(parts) > 1 else "",
                "title": parts[2].strip() if len(parts) > 2 else "",
            })

    print(f"[Step 1] Found {len(videos)} videos on profile")
    return videos

# ── Step 3: Verify video exists ───────────────────────────────────────────────

def verify_video(video_id: str, upload_date: str) -> bool:
    """
    Return False (skip) if the video appears to have been deleted within
    the 30-minute grace window. Videos older than 30min pass without re-check.
    """
    url = f"https://www.tiktok.com/@papakane808/video/{video_id}"

    # upload_date from yt-dlp is YYYYMMDD; if video was uploaded today it
    # could be < 30min old — re-verify it still exists.
    if upload_date and len(upload_date) == 8:
        try:
            uploaded_dt = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            age_secs = (datetime.now(timezone.utc) - uploaded_dt).total_seconds()
            if age_secs < NEW_VIDEO_GRACE_SECS:
                print(f"[Step 3] Video {video_id} is recent ({age_secs / 60:.0f}min) — re-verifying...")
                check = subprocess.run(
                    [YTDLP_BIN, "--skip-download", "--print", "%(id)s",
                     "--cookies-from-browser", "chrome", url],
                    capture_output=True, text=True, timeout=30,
                )
                if check.returncode != 0 or video_id not in check.stdout:
                    print(f"[Step 3] SKIP {video_id}: video gone within grace period")
                    return False
        except ValueError:
            pass

    return True

# ── Step 4: Download ──────────────────────────────────────────────────────────

def _probe_streams(video_path: Path) -> list[dict]:
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-show_streams", "-of", "json", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    result.check_returncode()
    return json.loads(result.stdout).get("streams", [])


def has_audio_stream(video_path: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in _probe_streams(video_path))


def require_audio_stream(video_path: Path, label: str = "video") -> None:
    if not has_audio_stream(video_path):
        raise RuntimeError(f"{label} has no audio stream: {video_path}")


def _download_with_format(url: str, output_tmpl: str, format_selector: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            YTDLP_BIN,
            "--format", format_selector,
            "--merge-output-format", "mp4",
            "--output", output_tmpl,
            "--no-playlist",
            "--cookies-from-browser", "chrome",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )


def download_video(video_id: str, work_dir: Path) -> Path:
    url = f"https://www.tiktok.com/@papakane808/video/{video_id}"
    output_tmpl = str(work_dir / "%(id)s.%(ext)s")

    # Prefer progressive H.264 formats that explicitly include audio. Some TikTok posts
    # report higher-res HEVC variants as if they include audio, but yt-dlp can still save
    # a video-only file from those selectors, which led to soundless Instagram uploads.
    selectors = [
        "best[format_id*=h264][acodec!=none][vcodec!=none]/best[acodec!=none][vcodec!=none]/download",
        "download",
        "best",
    ]

    last_error = ""
    for i, selector in enumerate(selectors, 1):
        for stale in work_dir.glob(f"{video_id}.*"):
            stale.unlink(missing_ok=True)

        result = _download_with_format(url, output_tmpl, selector)
        if result.returncode != 0:
            last_error = result.stderr[:400]
            continue

        candidates = list(work_dir.glob(f"{video_id}.*"))
        if not candidates:
            last_error = f"Downloaded file not found in {work_dir}"
            continue

        candidate = candidates[0]
        if has_audio_stream(candidate):
            if i > 1:
                print(f"[Step 4] Audio-safe fallback selector worked for {video_id}: {selector}")
            return candidate

        last_error = f"Downloaded file has no audio stream using selector: {selector}"
        print(f"[Step 4] WARNING {last_error} — retrying fallback")

    raise RuntimeError(f"Download failed: {last_error}")

# ── Step 5: FFmpeg normalize ──────────────────────────────────────────────────

def get_duration(video_path: Path) -> float:
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
        capture_output=True, text=True, timeout=30,
    )
    result.check_returncode()
    return float(json.loads(result.stdout)["format"]["duration"])


def normalize_video(input_path: Path, output_path: Path) -> Path:
    """
    Scale-pad to 1080x1920 (no crop), trim to 180s max, H.264/yuv420p/AAC/faststart.
    Handles any source aspect ratio by padding with black bars.
    Instagram-specific 90s trim is created separately in process_video().
    """
    duration = get_duration(input_path)
    trim_args = ["-t", str(MAX_DURATION_SECS)] if duration > MAX_DURATION_SECS else []

    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
    )

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(input_path),
        *trim_args,
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-preset", "fast",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed: {result.stderr[-600:]}")
    return output_path

def _trim_for_instagram(input_path: Path, output_path: Path) -> Path:
    """Stream-copy input_path trimmed to IG_MAX_DURATION_SECS. Fast — no re-encode."""
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", str(input_path),
        "-t", str(IG_MAX_DURATION_SECS),
        "-c", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg IG trim failed: {result.stderr[-600:]}")
    return output_path


# ── Step 6: Transcription + captions ─────────────────────────────────────────

def _srt_timestamp(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    s = int(seconds)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe(video_path: Path) -> tuple[str, Path]:
    """Transcribe with faster-whisper base model. Returns (full_text, srt_path).

    Returns empty strings if the video has no audio track or decoding fails.
    The caller is responsible for skipping caption burn on empty output.
    """
    from faster_whisper import WhisperModel

    srt_path = video_path.with_suffix(".srt")
    srt_lines = []
    text_parts = []

    try:
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(video_path), beam_size=5)
        for i, seg in enumerate(segments, 1):
            text_parts.append(seg.text.strip())
            srt_lines.append(
                f"{i}\n{_srt_timestamp(seg.start)} --> {_srt_timestamp(seg.end)}\n{seg.text.strip()}\n"
            )
    except Exception as e:
        print(f"[Step 6] Whisper failed ({e}) — no audio track or decode error, proceeding without captions")

    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    return " ".join(text_parts), srt_path


# ── Step 7: Thumbnails ────────────────────────────────────────────────────────

def extract_thumbnails(video_path: Path, output_dir: Path, count: int = 3) -> list[Path]:
    duration = get_duration(video_path)
    thumbs = []
    for i in range(count):
        t = duration * (i + 1) / (count + 1)
        out = output_dir / f"thumbnail_{i + 1}.jpg"
        result = subprocess.run(
            [FFMPEG_BIN, "-y", "-ss", f"{t:.2f}", "-i", str(video_path),
             "-frames:v", "1", "-q:v", "2", str(out)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            thumbs.append(out)
    return thumbs

# ── Step 8: Copy generation ───────────────────────────────────────────────────

_DEFAULT_PROMPT = (
    "You are Muse, copywriter for @papakane808 — a personal AI/automation builder "
    "posting YouTube Shorts about Claude, OpenClaw, and AI tools.\n\n"
    "Given this transcript, return ONLY a valid JSON object with:\n"
    '- "title": SEO keyword-rich YouTube Shorts title (max 100 chars, '
    'hook-driven, mention relevant tools like Claude / OpenClaw / AI automation)\n'
    '- "description": 2-3 sentences ending exactly with: '
    '"Follow @papakane808 for daily AI building content. Drop a comment with your biggest AI question."\n'
    '- "tags": array of 10-15 lowercase keyword strings (no #, no spaces)\n\n'
    "Voice: direct, builder-style, no corporate speak. Active voice.\n"
    "Return ONLY the JSON object, no markdown fences, no explanation."
)


def generate_copy(transcript: str, video_id: str) -> dict:
    templates = {}
    if COPY_TEMPLATES_FILE.exists():
        with open(COPY_TEMPLATES_FILE) as f:
            templates = json.load(f)

    prompt = templates.get("llm_prompt", _DEFAULT_PROMPT)
    default_tags = templates.get("default_tags", [
        "openclaw", "aiautomation", "claudeai", "claudecode",
        "aiagent", "youtubeShorts", "AItools", "automation", "aibuilder",
    ])
    cta = templates.get("abos_cta",
        "Follow @papakane808 for daily AI building content. "
        "Drop a comment with your biggest AI question.")

    try:
        from google import genai as _genai
        client = _genai.Client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=f"{prompt}\n\nTranscript:\n{transcript[:3000]}",
        )
        raw = response.text.strip()
        # Strip markdown code fences if the model wrapped in them
        clean = re.sub(r"```(?:json)?\n?(.*?)\n?```", r"\1", raw, flags=re.DOTALL).strip()
        return json.loads(clean)
    except Exception as e:
        print(f"[Step 8] LLM copy failed ({e}), using fallback template")

    snippet = transcript[:200].strip() if transcript else f"AI automation — {video_id}"
    return {
        "title": (templates.get("default_title_prefix", "How I built this with AI")
                  + f": {transcript[:55].strip()}...")[:100],
        "description": f"{snippet}\n\n{cta}",
        "tags": default_tags,
    }

# ── Step 9: YouTube upload ────────────────────────────────────────────────────

_YT_TOKEN_FILE = Path.home() / ".openclaw" / "credentials" / "google" / "youtube-token.json"
_YT_CLIENT_FILE = Path.home() / ".openclaw" / "credentials" / "google" / "personal-gmail-oauth-client.json"


def _get_youtube_creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError

    if not _YT_TOKEN_FILE.exists():
        raise RuntimeError(
            f"YouTube OAuth token missing: {_YT_TOKEN_FILE}\n"
            "Run once: /opt/homebrew/bin/python3 ~/.openclaw/scripts/youtube_auth_setup.py"
        )

    with open(_YT_TOKEN_FILE) as f:
        tok = json.load(f)
    with open(_YT_CLIENT_FILE) as f:
        cli = json.load(f)["installed"]

    creds = Credentials(
        token=tok.get("token"),
        refresh_token=tok.get("refresh_token"),
        token_uri=tok.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=cli["client_id"],
        client_secret=cli["client_secret"],
        scopes=tok.get("scopes", ["https://www.googleapis.com/auth/youtube.upload"]),
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise RuntimeError(
                f"YouTube token refresh failed: {e}\n"
                "Re-run: /opt/homebrew/bin/python3 ~/.openclaw/scripts/youtube_auth_setup.py"
            )
        tok["token"] = creds.token
        if creds.expiry:
            tok["expiry"] = creds.expiry.isoformat() + "Z"
        with open(_YT_TOKEN_FILE, "w") as f:
            json.dump(tok, f, indent=2)

    return creds


def upload_to_youtube(video_path: Path, thumbnail_path: Path | None, copy: dict) -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError

    creds = _get_youtube_creds()
    youtube = build("youtube", "v3", credentials=creds)

    title = copy.get("title", "AI automation short")[:100]
    description = copy.get("description", "")
    if "#shorts" not in description.lower():
        description = f"{description}\n\n#Shorts".lstrip()
    description = description[:5000]
    tags = copy.get("tags", [])
    if not any(t.lower() == "shorts" for t in tags):
        tags = list(tags) + ["Shorts"]

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "28",  # Science & Technology
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True, chunksize=5 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print("[Step 9] Uploading to YouTube...")
    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"[Step 9]   {int(status.progress() * 100)}%")
    except HttpError as e:
        if e.resp.status == 403 and b"quotaExceeded" in e.content:
            raise QuotaExceededError("YouTube API daily quota exhausted")
        raise

    yt_id = response["id"]
    yt_url = f"https://youtube.com/shorts/{yt_id}"

    if thumbnail_path and thumbnail_path.exists():
        try:
            thumb_media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
            youtube.thumbnails().set(videoId=yt_id, media_body=thumb_media).execute()
            print("[Step 9] Thumbnail set")
        except Exception as e:
            print(f"[Step 9] Thumbnail upload skipped: {e}")

    return {"video_id": yt_id, "url": yt_url, "title": title, "youtube": youtube}


def add_to_playlist(youtube, yt_video_id: str):
    """Add a video to the OpenClaw playlist. No-op if .playlist_id file is missing."""
    if not PLAYLIST_FILE.exists():
        return
    playlist_id = PLAYLIST_FILE.read_text().strip()
    if not playlist_id:
        return
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={"snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": yt_video_id},
            }}
        ).execute()
        print(f"[Step 9] Added to OpenClaw playlist")
    except Exception as e:
        print(f"[Step 9] Playlist add skipped (non-fatal): {e}")

# ── Step 9b: Instagram Reels upload ──────────────────────────────────────────

def _ig_post(path: str, params: dict) -> dict:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN not set in .env")
    params["access_token"] = token
    url = f"{IG_API_BASE}{path}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = body
        raise RuntimeError(f"Instagram API {e.code}: {msg}")


def _ig_get(path: str, params: dict) -> dict:
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN not set in .env")
    params["access_token"] = token
    url = f"{IG_API_BASE}{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(body).get("error", {}).get("message", body)
        except Exception:
            msg = body
        raise RuntimeError(f"Instagram API {e.code}: {msg}")


def _stage_to_gcs(video_path: Path, video_id: str) -> str:
    """Upload normalized MP4 to GCS staging bucket. Returns v4 signed URL (2h TTL).

    Requires one-time GCS setup. If bucket/permissions are missing, run:
      ~/.openclaw/automations/youtube-shorts/setup_instagram_gcs.sh
    (after: gcloud auth login --account support@brand75.com)
    """
    import datetime as dt
    from google.cloud import storage
    from google.oauth2 import service_account

    credentials = service_account.Credentials.from_service_account_file(
        str(IG_SA_FILE),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    client = storage.Client(project=IG_GCS_PROJECT, credentials=credentials)

    bucket = client.bucket(IG_GCS_BUCKET)

    blob_name = f"instagram/{video_id}.mp4"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(video_path), content_type="video/mp4", timeout=600)
    print(f"[Step 9b/GCS] Staged {blob_name}")

    signed_url = blob.generate_signed_url(
        version="v4",
        expiration=dt.timedelta(hours=2),
        method="GET",
        credentials=credentials,
    )
    return signed_url


def _delete_from_gcs(video_id: str):
    """Remove staged video from GCS. Non-fatal — just warns on error."""
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            str(IG_SA_FILE),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = storage.Client(project=IG_GCS_PROJECT, credentials=credentials)
        client.bucket(IG_GCS_BUCKET).blob(f"instagram/{video_id}.mp4").delete()
        print(f"[Step 9b/GCS] Deleted staged video for {video_id}")
    except Exception as e:
        print(f"[Step 9b/GCS] Cleanup warning: {e}")


def upload_to_instagram(video_path: Path, video_id: str, copy: dict) -> dict:
    """
    Stage video to GCS, create Reels container, wait for processing, publish.
    GCS object is deleted regardless of publish outcome.
    Returns {"reel_id": ..., "url": ...}.
    """
    ig_user_id = os.environ.get("INSTAGRAM_USER_ID", "17841400066810201")

    description = copy.get("description", "")
    tags = copy.get("tags", [])
    hashtag_line = " ".join(f"#{t}" for t in tags)
    caption = f"{description}\n\n{hashtag_line}".strip() if hashtag_line else description
    caption = caption[:IG_CAPTION_MAX]

    print("[Step 9b] Staging video to GCS...")
    video_url = _stage_to_gcs(video_path, video_id)

    try:
        print("[Step 9b] Creating Reels container...")
        resp = _ig_post(f"/{ig_user_id}/media", {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
        })
        container_id = resp.get("id")
        if not container_id:
            raise RuntimeError(f"No container ID in response: {resp}")

        print(f"[Step 9b] Waiting for container {container_id} to finish processing...")
        deadline = time.time() + IG_CONTAINER_TIMEOUT_SECS
        while True:
            if time.time() > deadline:
                raise RuntimeError(
                    f"Container {container_id} timed out after {IG_CONTAINER_TIMEOUT_SECS}s"
                )
            status_resp = _ig_get(f"/{container_id}", {"fields": "status_code,status"})
            status_code = status_resp.get("status_code", "")
            print(f"[Step 9b]   status: {status_code}")
            if status_code == "FINISHED":
                break
            if status_code == "ERROR":
                raise RuntimeError(
                    f"Container processing error: {status_resp.get('status', 'unknown')}"
                )
            time.sleep(IG_CONTAINER_POLL_SECS)

        print("[Step 9b] Publishing Reel...")
        pub_resp = _ig_post(f"/{ig_user_id}/media_publish", {"creation_id": container_id})
        reel_id = pub_resp.get("id")
        if not reel_id:
            raise RuntimeError(f"No reel ID in publish response: {pub_resp}")

        reel_url = f"https://www.instagram.com/reel/{reel_id}/"
        print(f"[Step 9b] Published: {reel_url}")
        return {"reel_id": reel_id, "url": reel_url}

    finally:
        _delete_from_gcs(video_id)

# ── Step 10: Tracking log ─────────────────────────────────────────────────────

def log_upload(tiktok_id: str, yt_video_id: str, yt_url: str, title: str,
               ig_reel_id: str | None = None, ig_url: str | None = None,
               ig_error: str | None = None, overlay_applied: bool = False):
    entry = {
        "tiktok_id": tiktok_id,
        "yt_video_id": yt_video_id,
        "yt_url": yt_url,
        "title": title,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    if overlay_applied:
        entry["overlay_applied"] = True
    if ig_reel_id:
        entry["ig_reel_id"] = ig_reel_id
        entry["ig_url"] = ig_url
    if ig_error:
        entry["ig_error"] = ig_error
    with open(TRACKING_LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

# ── Per-video orchestration ───────────────────────────────────────────────────

def process_video(video_info: dict):
    video_id = video_info["id"]
    upload_date = video_info.get("upload_date", "")
    vid_work = WORK_DIR / video_id
    vid_work.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"Processing {video_id}")
    print(f"{'='*60}")

    current_step = "init"
    try:
        # Step 3: verify
        current_step = "Step 3 (verify)"
        if not verify_video(video_id, upload_date):
            mark_processed(video_id)
            return

        # Step 4: download
        current_step = "Step 4 (download)"
        print(f"[{current_step}] Downloading...")
        raw = download_video(video_id, vid_work)
        print(f"[Step 4] {raw.name}")

        # Step 5: normalize
        current_step = "Step 5 (normalize)"
        print(f"[{current_step}] Normalizing to 1080x1920...")
        clean = vid_work / f"{video_id}_clean.mp4"
        normalize_video(raw, clean)
        require_audio_stream(clean, "Normalized output")

        # Step 5b: overlay compositor (conditional — only runs if overlay/<video_id>.json exists)
        overlay_applied = False
        current_step = "Step 5b (overlay compositor)"
        try:
            from overlay_compositor import load_overlay_config, validate_overlay_config, apply_overlay
            overlay_cfg = load_overlay_config(AUTOMATION_DIR, video_id)
            if overlay_cfg:
                errs = validate_overlay_config(overlay_cfg)
                if errs:
                    print(f"[Step 5b] Overlay config invalid — skipping overlay: {errs}")
                else:
                    print(f"[Step 5b] Applying overlay: '{overlay_cfg.get('banner_text')}'")
                    overlay_out = vid_work / f"{video_id}_overlay.mp4"
                    apply_overlay(clean, overlay_out, overlay_cfg)
                    clean = overlay_out
                    require_audio_stream(clean, "Overlay output")
                    overlay_applied = True
                    print(f"[Step 5b] Overlay applied successfully")
        except ImportError:
            pass  # overlay_compositor not available — safe to skip

        # Step 6: transcribe + burn captions
        current_step = "Step 6 (transcribe)"
        print(f"[{current_step}] Transcribing...")
        transcript, srt_path = transcribe(clean)
        print(f"[Step 6] {len(transcript)} chars transcribed")

        # SRT saved locally for reference; YouTube auto-captions handle subtitles

        # Final duration guard before upload
        dur = get_duration(clean)
        if dur > MAX_DURATION_SECS + 2:
            raise RuntimeError(f"Output is {dur:.1f}s > {MAX_DURATION_SECS}s limit")

        # Step 7: thumbnails
        current_step = "Step 7 (thumbnails)"
        thumbs = extract_thumbnails(clean, vid_work, count=3)
        print(f"[Step 7] {len(thumbs)} thumbnails extracted")

        # Step 8: copy
        current_step = "Step 8 (copy)"
        print(f"[{current_step}] Generating copy...")
        copy = generate_copy(transcript, video_id)
        print(f"[Step 8] Title: {copy.get('title', '(none)')}")

        # Step 9: upload clean normalized video (YouTube handles auto-captions)
        current_step = "Step 9 (YouTube upload)"
        require_audio_stream(clean, "YouTube upload candidate")
        yt = upload_to_youtube(clean, thumbs[0] if thumbs else None, copy)
        add_to_playlist(yt.pop("youtube"), yt["video_id"])

        # Step 9b: Instagram Reels — non-fatal; YouTube success is the gate
        ig_result = None
        ig_temp = None
        ig_error_msg = None
        current_step = "Step 9b (Instagram upload)"
        try:
            if dur > IG_MAX_DURATION_SECS:
                ig_temp = vid_work / f"{video_id}_ig.mp4"
                print(f"[Step 9b] Video is {dur:.1f}s — trimming to {IG_MAX_DURATION_SECS}s for Instagram...")
                _trim_for_instagram(clean, ig_temp)
                require_audio_stream(ig_temp, "Instagram trimmed output")
                ig_video = ig_temp
            else:
                ig_video = clean
            require_audio_stream(ig_video, "Instagram upload candidate")
            ig_result = upload_to_instagram(ig_video, video_id, copy)
            notify_ig_success(video_id, ig_result["url"])
        except Exception as ig_exc:
            ig_error_msg = str(ig_exc)[:500]
            print(f"[Step 9b] Instagram upload failed (non-fatal): {ig_exc}")
            notify_ig_failure(video_id, "Step 9b (Instagram upload)", str(ig_exc))
        finally:
            if ig_temp and ig_temp.exists():
                ig_temp.unlink(missing_ok=True)

        # Step 10: log
        log_upload(
            video_id, yt["video_id"], yt["url"], yt["title"],
            ig_reel_id=ig_result["reel_id"] if ig_result else None,
            ig_url=ig_result["url"] if ig_result else None,
            ig_error=ig_error_msg,
            overlay_applied=overlay_applied,
        )
        mark_processed(video_id)

        # Cleanup — remove temp video files; tracking log + processed IDs are permanent
        shutil.rmtree(vid_work, ignore_errors=True)

        # Step 11: success alert
        notify_success(video_id, yt["title"], yt["url"])
        print(f"\n\u2705 {yt['url']}")

    except QuotaExceededError:
        raise  # Propagate up — _run() handles this cleanly
    except Exception as exc:
        import traceback
        print(f"\n\u274c Failed [{current_step}]: {exc}")
        traceback.print_exc()

        attempts = record_attempt(video_id)
        if attempts >= MAX_ATTEMPTS:
            print(f"[Retry] {video_id} hit {MAX_ATTEMPTS} failures — marking as permanently failed")
            mark_failed(video_id)
            notify_failure(
                video_id, current_step,
                f"Giving up after {MAX_ATTEMPTS} attempts. Last error: {str(exc)}"
            )
        else:
            notify_failure(video_id, current_step, f"Attempt {attempts}/{MAX_ATTEMPTS}: {str(exc)}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n[YouTube Shorts Pipeline] {datetime.now().strftime('%Y-%m-%d %H:%M')} PT")

    AUTOMATION_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    if not acquire_lock():
        print("[Main] Another pipeline run is already in progress — exiting.")
        sys.exit(0)

    try:
        _run()
    finally:
        release_lock()


def _run():
    # Step 1
    try:
        videos = poll_tiktok_profile()
    except Exception as e:
        notify_failure("poll", "Step 1 (TikTok poll)", str(e))
        sys.exit(1)

    if not videos:
        print("[Main] No videos returned from profile poll.")
        sys.exit(0)

    # Step 2: filter
    processed = load_processed_ids()
    successful_yt = load_successful_youtube_ids()
    failed = load_failed_ids()
    polled_ids = {v["id"] for v in videos}

    # Exclude confirmed successes. Use the tracking log as the authoritative source:
    # if a video has ANY successful YouTube upload in the log, skip it even if
    # .processed_ids doesn't have it (prevents retry-until-duplicate bug).
    # Filter out videos that are too old (don't backfill old TikTok content)
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=MAX_VIDEO_AGE_DAYS)).strftime("%Y%m%d")
    new_videos = []
    for v in videos:
        if v["id"] in processed or v["id"] in successful_yt:
            continue
        upload_date = v.get("upload_date", "")
        if not upload_date or len(upload_date) != 8:
            print(f"[Step 2] SKIP {v['id']}: no valid upload_date — treating as too old")
            continue
        if upload_date < cutoff_date:
            print(f"[Step 2] SKIP {v['id']}: upload_date {upload_date} older than {MAX_VIDEO_AGE_DAYS} days (cutoff {cutoff_date})")
            continue
        new_videos.append(v)

    # Log any videos that are in processed but NOT in the tracking log (stale state)
    stale_processed = processed - successful_yt
    if stale_processed:
        print(f"[Step 2] {len(stale_processed)} ID(s) in .processed_ids but no tracking log entry — treating as unverified")

    if failed:
        retrying = failed & polled_ids
        outside_window = failed - polled_ids
        if retrying:
            print(f"[Step 2] {len(retrying)} failed ID(s) in poll window — will retry: {sorted(retrying)}")
        if outside_window:
            print(f"[Step 2] WARNING: {len(outside_window)} failed ID(s) outside poll window (manual retry required): {sorted(outside_window)}")

    print(f"[Step 2] {len(new_videos)} to process / {len(videos)} polled / {len(processed)} in processed_ids / {len(successful_yt)} confirmed on YouTube")

    if not new_videos:
        print("[Main] All caught up — nothing new to process.")
        sys.exit(0)

    # Daily quota cap: max 5 uploads per run to stay well within 10K daily limit
    # (each upload costs ~1650 quota, so 5 = 8250, leaving headroom)
    MAX_UPLOADS_PER_RUN = 5
    uploaded = 0
    for v in new_videos:
        if uploaded >= MAX_UPLOADS_PER_RUN:
            remaining = len(new_videos) - uploaded
            print(f"\n[Quota] Hit max {MAX_UPLOADS_PER_RUN} uploads per run cap. {remaining} video(s) remain for next run.")
            break
        try:
            process_video(v)
            uploaded += 1
        except QuotaExceededError:
            remaining = len(new_videos) - uploaded
            print(f"\n[Quota] Daily YouTube quota exhausted after {uploaded} upload(s). {remaining} video(s) remain.")
            _notify(
                f"\u23f8 *YouTube Shorts — Quota Reached*\n"
                f"Uploaded {uploaded} video(s) today. {remaining} still in backlog.\n"
                f"Pipeline resumes automatically next run."
            )
            return

    print(f"\n[Main] Done. {uploaded} video(s) uploaded.")


if __name__ == "__main__":
    main()
