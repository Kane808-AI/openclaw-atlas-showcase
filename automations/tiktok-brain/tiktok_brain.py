#!/usr/bin/env python3
"""
TikTok Brain - Video-to-Knowledge Pipeline

Accepts a local video file (.mp4, .mov, .m4v) or a URL.
For URLs: transcribes via ElevenLabs POST /v1/speech-to-text with source_url + xi-api-key,
falls back to yt-dlp + faster-whisper on failure.
For local files: transcribes via faster-whisper.

Usage:
    python3 tiktok_brain.py <video file or URL>
"""

import os, sys, json, tempfile, subprocess, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
import re as _re

# Shared auth module
sys.path.insert(0, os.path.expanduser("~/.openclaw/scripts"))
from google_auth import get_brand75_credentials

from google import genai
from googleapiclient.discovery import build

# Obsidian logging
OBSIDIAN_TIKTOK_BRAIN_PATH = os.path.expanduser("~/.openclaw/workspace/notes/ideas/tiktok-brain")
OBSIDIAN_IDEAS_BACKLOG_PATH = os.path.expanduser("~/.openclaw/workspace/notes/ideas/backlog")
OBSIDIAN_INDEX_PATH = os.path.join(OBSIDIAN_TIKTOK_BRAIN_PATH, "INDEX.md")

# --- Configuration ---

# Load GOOGLE_API_KEY from env, falling back to .env file
_ENV_FILE = os.path.expanduser("~/.openclaw/.env")
if not os.getenv("GOOGLE_API_KEY") and os.path.isfile(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            if _line.startswith("GOOGLE_API_KEY="):
                os.environ["GOOGLE_API_KEY"] = _line.strip().split("=", 1)[1]
                break

# Initialize google.genai client (reads GOOGLE_API_KEY from env automatically)
_client = genai.Client()

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}

# LLM - Gemini 2.5 Flash
GEMINI_MODEL = "gemini-2.5-flash"


# ──────────────────────────────────────────────
#  LLM (Gemini 2.5 Flash)
# ──────────────────────────────────────────────

def llm_call(prompt, transcript):
    """Single-turn chat completion via Google Gemini API."""
    try:
        response = _client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{prompt}\n\nTranscript:\n{transcript}",
        )
        return response.text.strip()
    except Exception as e:
        print(f"  LLM call failed: {e}")
        return None


def generate_review(transcript):
    """High-level review: key ideas, actionable takeaways, recommendations."""
    prompt = (
        "You are reviewing a TikTok video transcript for a builder who runs "
        "an AI automation company, a marketing agency, and personal projects. "
        "Write a high-level review with these sections:\n\n"
        "## Key Ideas\n"
        "Bullet the 3-5 most important ideas or insights from this video.\n\n"
        "## Actionable Takeaways\n"
        "For each key idea, explain how it could be applied — to a business, "
        "a personal brand, a side project, content strategy, or any other endeavor. "
        "Be specific and practical.\n\n"
        "## Recommendations\n"
        "What should the viewer do next based on this content? "
        "Include tools, strategies, or experiments worth trying.\n\n"
        "Keep it concise but useful. No fluff."
    )
    return llm_call(prompt, transcript)


def generate_summary(transcript):
    """2-3 sentence LLM summary. Falls back to first-3-sentences if LLM fails."""
    prompt = (
        "Summarize this transcript in 2-3 sentences for a content creator's "
        "reference log."
    )
    result = llm_call(prompt, transcript)
    if result:
        return result
    # Fallback
    sentences = transcript.split(".")
    return ". ".join([s.strip() for s in sentences[:3] if s.strip()]) + "."


def generate_tags(transcript):
    """2-3 comma-separated topic tags via LLM. Returns empty string on failure."""
    prompt = (
        "Generate 2-3 short tags for this transcript. Tags should describe the "
        "main topic. Choose from or create tags like: AI, OpenClaw, Claude, "
        "Automation, Marketing, TikTok, Business, Security, Tools, Productivity. "
        "Return only the tags as comma-separated values, nothing else."
    )
    result = llm_call(prompt, transcript)
    if result:
        # Strip trailing punctuation and whitespace
        return result.rstrip(".,;").strip()
    return ""


# ──────────────────────────────────────────────
#  Transcription & Download
# ──────────────────────────────────────────────

def transcribe(audio_path):
    from faster_whisper import WhisperModel

    print(f"Transcribing: {audio_path}")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio_path, beam_size=5)
    text = " ".join([s.text for s in segments]).strip()
    print(f"Transcript length: {len(text)} chars")
    return text


def transcribe_url_elevenlabs(url):
    """POST to ElevenLabs official /v1/speech-to-text with source_url + xi-api-key.
    Uses multipart/form-data. Works for TikTok URLs (server-side fetcher not blocked).
    Response shape: {"text": "...", "language_code": "...", "words": [...], ...}
    Returns transcript text, or None on failure so the caller falls back.
    """
    api_key = os.getenv("ELEVENLABS_API_KEY") or _load_env_key("ELEVENLABS_API_KEY")
    if not api_key:
        print("  [ElevenLabs] ELEVENLABS_API_KEY not set — skipping")
        return None

    boundary = "----ElevenLabsBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="model_id"\r\n\r\nscribe_v2\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="source_url"\r\n\r\n{url}\r\n'
        f"--{boundary}--\r\n"
    ).encode()

    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/speech-to-text",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "xi-api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        text = data.get("text", "").strip()
        if not text:
            print(f"  [ElevenLabs] Empty text in response — top-level keys: {list(data.keys())}")
            return None
        print(f"  [ElevenLabs] /v1/speech-to-text succeeded — {len(text)} chars")
        return text
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        print(f"  [ElevenLabs] HTTP {e.code}: {err_body}")
        return None
    except Exception as e:
        print(f"  [ElevenLabs] Request failed: {e}")
        return None


def _load_env_key(key_name):
    """Load a single key from ~/.openclaw/.env, returning None if missing."""
    if os.path.isfile(_ENV_FILE):
        with open(_ENV_FILE) as f:
            for line in f:
                if line.startswith(f"{key_name}="):
                    return line.strip().split("=", 1)[1]
    return None


def download_audio(url, output_path):
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", "chrome",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--output", output_path,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        raise Exception(f"yt-dlp failed: {result.stderr}")


# ──────────────────────────────────────────────
#  Obsidian Logging
# ──────────────────────────────────────────────

def log_review_to_obsidian(date_str, source_name, transcript, review, summary, tags):
    """Write the full review and transcript to a Markdown file in tiktok-brain/."""
    os.makedirs(OBSIDIAN_TIKTOK_BRAIN_PATH, exist_ok=True)

    # Build a slug from first few words of the transcript
    slug = _re.sub(r'[^a-zA-Z0-9_\-.]', '', transcript[:50].replace(' ', '-'))
    filename = f"{date_str}-{slug}.md"
    file_path = Path(OBSIDIAN_TIKTOK_BRAIN_PATH) / filename

    frontmatter = f"""---
date: "{date_str}"
source: "{source_name}"
tags: "{tags}"
summary: "{summary[:200] if summary else ''}"
---
"""
    body = f"# TikTok Brain - {date_str}\n\n"
    body += f"**Source:** {source_name}\n\n"
    if review:
        body += f"{review}\n\n---\n\n"
    body += f"## Transcript\n\n{transcript}\n"

    content = frontmatter + body
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Logged review to Obsidian: {file_path}")
    except Exception as e:
        print(f"  Warning: Failed to write review to Obsidian {file_path}: {e}")

    return file_path


def log_ideas_to_obsidian(ideas, date_str, source_name, tags, tiktok_brain_file_path):
    """Write extracted ideas to individual Markdown files in Obsidian Ideas Backlog."""
    os.makedirs(OBSIDIAN_IDEAS_BACKLOG_PATH, exist_ok=True)
    for idea_data in ideas:
        idea_content = idea_data["idea"]
        category = idea_data["category"]
        # Create a safe filename from the idea content
        filename = _re.sub(r'[^a-zA-Z0-9_\-.]', '', idea_content[:50].replace(' ', '-'))
        file_path = os.path.join(OBSIDIAN_IDEAS_BACKLOG_PATH, f"{date_str}-{filename}.md")

        # YAML frontmatter
        frontmatter = f"""---
date: "{date_str}"
category: "{category}"
tags: "{tags}"
source: "{source_name}"
tiktok_brain_source: "{tiktok_brain_file_path.name}"
---
"""
        content = f"{frontmatter}# Idea\n\n{idea_content}\n"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"  Logged idea to Obsidian: {file_path}")
        except Exception as e:
            print(f"  Warning: Failed to write idea to Obsidian {file_path}: {e}")


def append_to_index(date_str, note_filename, tags, summary):
    """Append a row to the INDEX.md master table."""
    note_link = "[[" + Path(note_filename).stem + "]]"
    short_summary = summary[:117] + "..." if len(summary) > 120 else summary
    row = f"| {date_str} | {note_link} | {tags} | {short_summary} | New |"
    try:
        if not os.path.exists(OBSIDIAN_INDEX_PATH):
            header = "# TikTok Brain Index\n\n| Date | Note | Tags | Summary | Status |\n|------|------|------|---------|--------|\n"
            with open(OBSIDIAN_INDEX_PATH, "w", encoding="utf-8") as f:
                f.write(header)
        with open(OBSIDIAN_INDEX_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        # Insert before the <!-- entries comment or at end
        if "<!-- " in content:
            # Update the entry count
            lines = content.rstrip().split("\n")
            # Find and update comment line
            for i, line in enumerate(lines):
                if line.startswith("<!-- "):
                    count = int(_re.search(r"(\d+)", line).group(1)) + 1
                    lines[i] = f"<!-- {count} entries -->"
                    lines.insert(i, row)
                    break
            content = "\n".join(lines) + "\n"
        else:
            content = content.rstrip() + "\n" + row + "\n"
        with open(OBSIDIAN_INDEX_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  Appended to INDEX.md")
    except Exception as e:
        print(f"  Warning: Failed to append to INDEX.md: {e}")


# ──────────────────────────────────────────────
#  Google Doc Logging
# ──────────────────────────────────────────────

def create_google_doc(date_str, source_name, transcript, review, summary, tags):
    """Create a Google Doc with the transcript and high-level review."""
    creds = get_brand75_credentials()
    docs_service = build("docs", "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    slug = " ".join(transcript.split()[:8])
    title = f"TikTok Brain - {date_str} - {slug}"

    # Create the doc via Drive API (sets title)
    metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
    doc = drive_service.files().create(body=metadata, fields="id").execute()
    doc_id = doc["id"]

    # Build doc content
    content = f"Source: {source_name}\nDate: {date_str}\nTags: {tags}\n\n"
    content += f"Summary: {summary}\n\n"
    if review:
        content += f"{review}\n\n"
        content += "─" * 40 + "\n\n"
    content += f"Transcript:\n\n{transcript}\n"

    # Write content into the doc
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
    ).execute()

    doc_link = f"https://docs.google.com/document/d/{doc_id}/edit"
    print(f"  Created Google Doc: {doc_link}")
    return doc_link


# ──────────────────────────────────────────────
#  Ideas Extraction
# ──────────────────────────────────────────────

def extract_ideas(transcript):
    ideas = []
    sentences = [
        s.strip() for s in _re.split(r"[.!?]", transcript) if len(s.strip()) > 20
    ]
    keywords = {
        "AI": ["ai", "gpt", "claude", "model", "automation", "agent", "bot", "openclaw"],
        "Sales": ["sales", "revenue", "client", "customer", "pipeline", "crm", "lead"],
        "Marketing": [
            "marketing", "tiktok", "instagram", "social", "content", "brand", "seo",
        ],
        "Operations": [
            "workflow", "process", "system", "tool", "automate", "api", "apify",
        ],
    }
    signals = [
        "use", "try", "build", "create", "you can", "tool",
        "way to", "helps", "allows", "access",
    ]
    seen = set()
    for sentence in sentences:
        lower = sentence.lower()
        category = "Other"
        for cat, words in keywords.items():
            if any(w in lower for w in words):
                category = cat
                break
        if any(sig in lower for sig in signals) and sentence not in seen:
            seen.add(sentence)
            ideas.append({"idea": sentence, "category": category})
    return ideas[:5]


# ──────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: tiktok_brain.py <video file or URL>"}))
        sys.exit(1)

    input_arg = sys.argv[1]
    is_url = input_arg.startswith("http://") or input_arg.startswith("https://")
    is_local = not is_url

    print(f"Input: {input_arg}")
    print(f"Mode: {'local file' if is_local else 'URL (ElevenLabs first, yt-dlp fallback)'}")

    # ── File filter (local files only) ──
    if is_local:
        if not os.path.isfile(input_arg):
            print(json.dumps({
                "error": f"File not found: {input_arg}",
            }))
            sys.exit(1)
        ext = Path(input_arg).suffix.lower()
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            print(json.dumps({
                "status": "skipped",
                "reason": (
                    f"Extension '{ext}' is not a supported video format. "
                    f"Accepted: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}"
                ),
            }))
            sys.exit(0)
        audio_file = input_arg
        source_name = os.path.basename(input_arg)
    else:
        source_name = input_arg

    # ── Transcribe ──
    if is_url:
        print("[ElevenLabs] Attempting URL transcription...")
        transcript = transcribe_url_elevenlabs(input_arg)
        if transcript:
            print(f"[ElevenLabs] Path: /v1/speech-to-text (official) — {len(transcript)} chars")
        else:
            print("[ElevenLabs] URL transcription failed — falling back to yt-dlp + faster-whisper")
            tmpdir = tempfile.mkdtemp()
            audio_file = os.path.join(tmpdir, "audio.mp3")
            print("Downloading audio...")
            download_audio(input_arg, audio_file)
            transcript = transcribe(audio_file)
    else:
        print("[whisper] Path: local file — faster-whisper")
        transcript = transcribe(audio_file)
    if not transcript:
        print(json.dumps({"error": "Empty transcript"}))
        sys.exit(1)

    date_str = datetime.now().strftime("%Y-%m-%d")

    # ── LLM: review + summary + tags ──
    print("Generating high-level review...")
    review = generate_review(transcript)
    print("Generating LLM summary...")
    summary = generate_summary(transcript)
    print("Generating LLM tags...")
    tags = generate_tags(transcript)
    print(f"  Tags: {tags}")

    # ── Log review + transcript to Obsidian ──
    print("Logging review to Obsidian...")
    tiktok_brain_file_path = log_review_to_obsidian(
        date_str, source_name, transcript, review, summary, tags,
    )

    # ── Append to INDEX.md ──
    print("Updating INDEX.md...")
    append_to_index(date_str, tiktok_brain_file_path.name, tags, summary)

    # ── Create Google Doc (transcript + review) ──
    doc_link = None
    print("Creating Google Doc...")
    try:
        doc_link = create_google_doc(
            date_str, source_name, transcript, review, summary, tags,
        )
    except Exception as e:
        print(f"  Warning: Google Doc creation failed: {e}")

    # ── Ideas Backlog ──
    print("Extracting ideas...")
    ideas = extract_ideas(transcript)
    if ideas:
        print(f"  Found {len(ideas)} ideas - logging...")
        try:
            log_ideas_to_obsidian(ideas, date_str, source_name, tags, tiktok_brain_file_path)
        except Exception as e:
            print(f"  Warning: Ideas logging failed: {e}")
    else:
        print("  No ideas extracted from this transcript.")

    # ── Done ──
    result = {
        "status": "success",
        "review_file": str(tiktok_brain_file_path),
        "doc_link": doc_link,
        "summary": summary,
        "tags": tags,
        "ideas_logged": len(ideas) if ideas else 0,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
