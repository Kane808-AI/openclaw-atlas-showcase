"""
Overlay compositor for YouTube Shorts — conditional overlay mode.

Applies a persistent top-banner hook text and optional PIP compositing
(Chris as picture-in-picture over a full-frame proof asset).

This is a CONDITIONAL mode — it only runs when a per-video overlay config
file exists at: <automation_dir>/overlay/<video_id>.json

Trigger conditions (from project spec / Koa guidance):
  - Tool demos, workflow walkthroughs, website teardowns, resource clips
  - "Save this" and before/after proof clips
  - Only when the source clip contains screen proof OR a proof_asset is provided
  - NOT the default for every Short

Usage:
  Atlas creates overlay/<video_id>.json → pipeline detects it → runs apply_overlay()

Config file schema (all fields optional except banner_text):
  {
    "enabled": true,
    "banner_text": "I built this in 20 minutes",   // 5-8 words, required
    "proof_asset": "/path/to/screen-recording.mp4", // optional background asset
    "pip_position": "bottom-right",                 // where Chris appears
    "pip_scale": 0.35,                              // relative to frame width/height
    "banner_font_size": 52,
    "banner_bg_opacity": 0.80,
    "banner_padding": 22,
    "banner_y_offset": 44
  }
"""

import json
import shutil
import subprocess
from pathlib import Path

FFMPEG_BIN = "/opt/homebrew/bin/ffmpeg"
FFPROBE_BIN = "/opt/homebrew/bin/ffprobe"
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920

OVERLAY_CONFIG_DEFAULTS = {
    "enabled": True,
    "banner_text": "",
    "proof_asset": None,
    "pip_position": "bottom-right",
    "pip_scale": 0.35,
    "banner_font_size": 52,
    "banner_bg_opacity": 0.80,
    "banner_padding": 22,
    "banner_y_offset": 44,
}

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
]

_PIP_BOTTOM_SAFE = 380   # px — YouTube Shorts bottom UI safe zone (captions + controls)
_PIP_SIDE_MARGIN  = 40   # px — side safe margin
_PIP_TOP_SAFE     = 180  # px — skip banner area when PIP is at top


def _find_font() -> str:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return ""


def _pip_xy(position: str, scale: float) -> tuple[str, str]:
    """Return (x_expr, y_expr) for ffmpeg overlay filter at given position."""
    pip_w = f"(iw*{scale})"
    pip_h = f"(ih*{scale})"
    m = _PIP_SIDE_MARGIN
    b = _PIP_BOTTOM_SAFE
    t = _PIP_TOP_SAFE
    coords = {
        "bottom-right": (f"W-{pip_w}-{m}", f"H-{pip_h}-{b}"),
        "bottom-left":  (f"{m}",            f"H-{pip_h}-{b}"),
        "top-right":    (f"W-{pip_w}-{m}", f"{t}"),
        "top-left":     (f"{m}",            f"{t}"),
    }
    return coords.get(position, coords["bottom-right"])


def _escape_drawtext(text: str) -> str:
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def _build_banner_filter(cfg: dict) -> str:
    font_path = _find_font()
    font_arg = f":fontfile={font_path}" if font_path else ""
    escaped = _escape_drawtext(cfg["banner_text"].strip())
    fs = int(cfg["banner_font_size"])
    opacity = float(cfg["banner_bg_opacity"])
    pad = int(cfg["banner_padding"])
    y_off = int(cfg["banner_y_offset"])
    return (
        f"drawtext=text='{escaped}'"
        f"{font_arg}"
        f":fontsize={fs}"
        f":fontcolor=white"
        f":x=(W-text_w)/2"
        f":y={y_off + pad}"
        f":box=1"
        f":boxcolor=black@{opacity:.2f}"
        f":boxborderw={pad}"
    )


def _get_duration(path: Path) -> float:
    r = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    r.check_returncode()
    return float(json.loads(r.stdout)["format"]["duration"])


def _is_image(path: Path) -> bool:
    probe = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=15,
    )
    return (
        "image2" in probe.stdout.lower() or
        path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    )


def apply_overlay(input_path: Path, output_path: Path, config: dict) -> Path:
    """
    Apply overlay treatment to input_path and write result to output_path.

    Mode A — banner only (no proof_asset):
      Adds persistent top-banner hook text to the normalized video.

    Mode B — PIP + banner (proof_asset provided):
      Proof asset fills the 1080x1920 background; input video (Chris) is
      resized to pip_scale and anchored at pip_position; banner goes on top.

    Returns output_path on success. Raises RuntimeError on ffmpeg failure.
    """
    cfg = {**OVERLAY_CONFIG_DEFAULTS, **config}

    if not cfg.get("enabled", True):
        shutil.copy2(str(input_path), str(output_path))
        return output_path

    banner_text = cfg["banner_text"].strip()
    if not banner_text:
        raise ValueError("overlay_compositor: banner_text is required")

    banner_filter = _build_banner_filter(cfg)
    proof_asset = cfg.get("proof_asset")

    if proof_asset:
        proof_path = Path(proof_asset)
        if not proof_path.exists():
            raise FileNotFoundError(f"overlay_compositor: proof_asset not found: {proof_path}")

        scale = float(cfg["pip_scale"])
        pos = str(cfg["pip_position"])
        ox, oy = _pip_xy(pos, scale)
        duration = _get_duration(input_path)

        bg_scale_filter = (
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},setsar=1"
        )
        pip_scale_filter = f"scale=iw*{scale}:ih*{scale}"
        filter_complex = (
            f"[0:v]{bg_scale_filter}[bg];"
            f"[1:v]{pip_scale_filter}[pip];"
            f"[bg][pip]overlay={ox}:{oy}[composited];"
            f"[composited]{banner_filter}[out]"
        )

        if _is_image(proof_path):
            cmd = [
                FFMPEG_BIN, "-y",
                "-loop", "1", "-t", str(duration), "-i", str(proof_path),
                "-i", str(input_path),
                "-filter_complex", filter_complex,
                "-map", "[out]", "-map", "1:a?",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", "-preset", "fast",
                "-shortest",
                str(output_path),
            ]
        else:
            # Video proof asset — stream-loop so it covers full clip duration
            cmd = [
                FFMPEG_BIN, "-y",
                "-stream_loop", "-1", "-i", str(proof_path),
                "-i", str(input_path),
                "-filter_complex", filter_complex,
                "-map", "[out]", "-map", "1:a?",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", "-preset", "fast",
                "-t", str(duration),
                str(output_path),
            ]
    else:
        # Mode A: banner only on existing normalized video
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(input_path),
            "-vf", banner_filter,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-movflags", "+faststart", "-preset", "fast",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(
            f"overlay_compositor ffmpeg failed:\n{result.stderr[-800:]}"
        )
    return output_path


def load_overlay_config(automation_dir: Path, video_id: str) -> dict | None:
    """
    Load overlay config for video_id from <automation_dir>/overlay/<video_id>.json.
    Returns None if no config file exists or if enabled=false.
    """
    config_path = automation_dir / "overlay" / f"{video_id}.json"
    if not config_path.exists():
        return None
    with open(config_path) as f:
        cfg = json.load(f)
    if not cfg.get("enabled", True):
        print(f"[Overlay] Config exists for {video_id} but enabled=false — skipping")
        return None
    return cfg


def validate_overlay_config(config: dict) -> list[str]:
    """Returns list of validation error strings. Empty list = valid."""
    errors = []

    banner = config.get("banner_text", "").strip()
    if not banner:
        errors.append("banner_text is required")
    elif len(banner.split()) > 10:
        errors.append(f"banner_text is {len(banner.split())} words — target 5-8 words max")

    proof = config.get("proof_asset")
    if proof and not Path(proof).exists():
        errors.append(f"proof_asset not found: {proof}")

    scale = config.get("pip_scale", 0.35)
    if not (0.15 <= float(scale) <= 0.6):
        errors.append(f"pip_scale {scale} out of range [0.15, 0.6]")

    valid_positions = {"bottom-right", "bottom-left", "top-right", "top-left"}
    pos = config.get("pip_position", "bottom-right")
    if pos not in valid_positions:
        errors.append(f"pip_position '{pos}' invalid — must be one of {sorted(valid_positions)}")

    return errors
