#!/usr/bin/env python3
"""Transcribe a TikTok URL via ElevenLabs's undocumented /v1/speech-to-text/url endpoint.

No auth required — same endpoint the elevenlabs.io/tiktok-transcript-generator
page calls. Returns the transcript string on success; raises on any other outcome.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text/url"
MODEL_ID = "scribe_v2"
DEFAULT_TIMEOUT = 300


class ElevenLabsTranscribeError(Exception):
    """Raised when the endpoint returns anything other than a valid transcript."""


def transcribe_url(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    payload = json.dumps({"url": url, "model_id": MODEL_ID}).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise ElevenLabsTranscribeError(f"HTTP {e.code}: {err_body}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ElevenLabsTranscribeError(f"Network error: {e}") from None
    except json.JSONDecodeError as e:
        raise ElevenLabsTranscribeError(f"Non-JSON response: {e}") from None

    text = (data.get("chunk") or {}).get("text")
    if not text:
        raise ElevenLabsTranscribeError(f"Empty transcript in response: {data}")
    return text


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: elevenlabs_transcribe.py <tiktok_url>", file=sys.stderr)
        return 1
    try:
        print(transcribe_url(sys.argv[1]))
        return 0
    except ElevenLabsTranscribeError as e:
        print(f"ElevenLabs transcribe failed: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
