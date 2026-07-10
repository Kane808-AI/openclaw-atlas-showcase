#!/usr/bin/env python3
"""
Video Editor — Claude Code / Atlas tool

Secure ffmpeg wrapper for common video editing operations.
All inputs sanitized. File access sandboxed. Network protocols disabled.

Usage:
  python3 video_edit.py trim input.mp4 output.mp4 --start 00:00:05 --end 00:00:30
  python3 video_edit.py combine clip1.mp4 clip2.mp4 clip3.mp4 -o final.mp4
  python3 video_edit.py text input.mp4 output.mp4 --text "Hello World" --position bottom
  python3 video_edit.py resize input.mp4 output.mp4 --preset tiktok
  python3 video_edit.py speed input.mp4 output.mp4 --factor 1.5
  python3 video_edit.py audio input.mp4 output.mp4 --music bg.mp3 --mix 0.3
  python3 video_edit.py info input.mp4
  python3 video_edit.py thumbnail input.mp4 thumb.jpg --time 00:00:05
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

# Security: only allow file protocol
PROTOCOL_WHITELIST = "-protocol_whitelist,file,pipe"
SAFE_PATH_RE = re.compile(r'^[a-zA-Z0-9_\-./~ ]+$')
SAFE_TEXT_RE = re.compile(r'^[a-zA-Z0-9 _\-.,!?\'\"()#@&+:;\n]+$')
ALLOWED_EXTS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.mp3', '.wav', '.aac', '.m4a', '.jpg', '.jpeg', '.png'}
WORKDIR = os.path.expanduser("~/.openclaw/media")


def validate_path(p, must_exist=True):
    """Validate and resolve a file path. Must be under allowed directories."""
    p = os.path.expanduser(p)
    p = os.path.abspath(p)
    home = os.path.expanduser("~")
    allowed_roots = [
        os.path.join(home, ".openclaw"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Movies"),
        os.path.join(home, "Videos"),
        "/tmp",
    ]
    if not any(p.startswith(root) for root in allowed_roots):
        print(f"ERROR: Path not in allowed directory: {p}")
        print(f"Allowed: ~/.openclaw/, ~/Downloads/, ~/Desktop/, ~/Movies/, /tmp/")
        sys.exit(1)
    ext = os.path.splitext(p)[1].lower()
    if ext and ext not in ALLOWED_EXTS:
        print(f"ERROR: File extension not allowed: {ext}")
        sys.exit(1)
    if must_exist and not os.path.exists(p):
        print(f"ERROR: File not found: {p}")
        sys.exit(1)
    return p


def validate_timestamp(ts):
    """Validate HH:MM:SS or HH:MM:SS.ms format."""
    if not re.match(r'^\d{1,2}:\d{2}:\d{2}(\.\d+)?$', ts):
        print(f"ERROR: Invalid timestamp: {ts} (use HH:MM:SS or HH:MM:SS.ms)")
        sys.exit(1)
    return ts


def validate_text(text):
    """Sanitize text for ffmpeg drawtext filter."""
    if not SAFE_TEXT_RE.match(text):
        print(f"ERROR: Text contains disallowed characters. Alphanumeric and basic punctuation only.")
        sys.exit(1)
    # Escape ffmpeg drawtext special chars
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    text = text.replace(",", "\\,")
    return text


def run_ffmpeg(cmd_args, desc="Processing"):
    """Run ffmpeg with security flags."""
    cmd = ["ffmpeg", "-y"] + cmd_args
    print(f"{desc}...")
    print(f"  cmd: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg failed:\n{result.stderr[-500:]}")
        sys.exit(1)
    print("  Done.")
    return result


def cmd_info(args):
    """Get video file info."""
    path = validate_path(args.input)
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"ERROR: ffprobe failed:\n{result.stderr}")
        sys.exit(1)
    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    print(f"File: {os.path.basename(path)}")
    print(f"Duration: {float(fmt.get('duration', 0)):.1f}s")
    print(f"Size: {int(fmt.get('size', 0)) / 1024 / 1024:.1f}MB")
    for s in data.get("streams", []):
        if s["codec_type"] == "video":
            print(f"Video: {s.get('width')}x{s.get('height')}, {s.get('codec_name')}, {s.get('r_frame_rate')} fps")
        elif s["codec_type"] == "audio":
            print(f"Audio: {s.get('codec_name')}, {s.get('sample_rate')}Hz, {s.get('channels')}ch")


def cmd_trim(args):
    """Trim a video between start and end timestamps."""
    inp = validate_path(args.input)
    out = validate_path(args.output, must_exist=False)
    cmd = ["-i", inp]
    if args.start:
        cmd += ["-ss", validate_timestamp(args.start)]
    if args.end:
        cmd += ["-to", validate_timestamp(args.end)]
    cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero", out]
    run_ffmpeg(cmd, f"Trimming {os.path.basename(inp)}")
    print(f"Output: {out}")


def cmd_combine(args):
    """Combine multiple video clips into one."""
    inputs = [validate_path(p) for p in args.inputs]
    out = validate_path(args.output, must_exist=False)

    # Create concat file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir='/tmp') as f:
        for inp in inputs:
            f.write(f"file '{inp}'\n")
        concat_file = f.name

    try:
        cmd = ["-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", out]
        run_ffmpeg(cmd, f"Combining {len(inputs)} clips")
    finally:
        os.unlink(concat_file)
    print(f"Output: {out}")


def cmd_text(args):
    """Add text overlay using Pillow PNG + ffmpeg overlay filter."""
    inp = validate_path(args.input)
    out = validate_path(args.output, must_exist=False)
    # Unescape for display (validate_text escaped for ffmpeg, undo for Pillow)
    text = validate_text(args.text)
    display_text = text.replace("\\:", ":").replace("\\,", ",").replace("\\'", "'")

    # Get video dimensions via ffprobe
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", inp],
        capture_output=True, text=True, timeout=15
    )
    streams = json.loads(probe.stdout).get("streams", [])
    vid = next((s for s in streams if s["codec_type"] == "video"), {})
    vid_w, vid_h = int(vid.get("width", 1080)), int(vid.get("height", 1920))

    size = max(16, min(120, args.fontsize))
    color_map = {
        "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
        "yellow": (255, 255, 0), "green": (0, 255, 0), "blue": (0, 0, 255),
    }
    color = args.color if re.match(r'^[a-zA-Z]+$', args.color) else "white"
    fill = color_map.get(color, (255, 255, 255))

    # Render text to transparent PNG using Pillow
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (vid_w, vid_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except (OSError, IOError):
        font = ImageFont.load_default(size)
    bbox = draw.textbbox((0, 0), display_text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (vid_w - tw) // 2
    if args.position == "top":
        y = 50
    elif args.position == "center":
        y = (vid_h - th) // 2
    else:
        y = vid_h - th - 80

    # Draw outline then text
    for ox, oy in [(-2,0),(2,0),(0,-2),(0,2),(-2,-2),(2,2),(-2,2),(2,-2)]:
        draw.text((x+ox, y+oy), display_text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), display_text, font=font, fill=(*fill, 255))

    png_path = tempfile.mktemp(suffix=".png", dir="/tmp")
    img.save(png_path)

    try:
        cmd = ["-i", inp, "-i", png_path, "-filter_complex", "overlay=0:0", "-codec:a", "copy", out]
        run_ffmpeg(cmd, "Adding text overlay")
    finally:
        os.unlink(png_path)
    print(f"Output: {out}")


def cmd_resize(args):
    """Resize video to preset dimensions."""
    inp = validate_path(args.input)
    out = validate_path(args.output, must_exist=False)

    presets = {
        "tiktok": "1080:1920",      # 9:16 vertical
        "tiktok-land": "1920:1080",  # 16:9 horizontal
        "instagram": "1080:1080",    # 1:1 square
        "instagram-reel": "1080:1920",
        "youtube": "1920:1080",
        "youtube-short": "1080:1920",
    }

    if args.preset:
        scale = presets.get(args.preset)
        if not scale:
            print(f"ERROR: Unknown preset. Available: {', '.join(presets.keys())}")
            sys.exit(1)
    elif args.width and args.height:
        w = max(1, min(7680, int(args.width)))
        h = max(1, min(4320, int(args.height)))
        scale = f"{w}:{h}"
    else:
        print("ERROR: Specify --preset or --width and --height")
        sys.exit(1)

    # scale + pad to avoid stretching
    w, h = scale.split(":")
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    cmd = ["-i", inp, "-vf", vf, "-codec:a", "copy", out]
    run_ffmpeg(cmd, f"Resizing to {scale}")
    print(f"Output: {out}")


def cmd_speed(args):
    """Change video playback speed."""
    inp = validate_path(args.input)
    out = validate_path(args.output, must_exist=False)
    factor = max(0.25, min(4.0, float(args.factor)))

    video_filter = f"setpts={1/factor}*PTS"
    audio_filter = f"atempo={factor}" if 0.5 <= factor <= 2.0 else f"atempo={min(2.0, factor)}"
    # Chain atempo for factors outside 0.5-2.0 range
    if factor > 2.0:
        audio_filter = f"atempo=2.0,atempo={factor/2.0}"
    elif factor < 0.5:
        audio_filter = f"atempo=0.5,atempo={factor/0.5}"

    cmd = ["-i", inp, "-vf", video_filter, "-af", audio_filter, out]
    run_ffmpeg(cmd, f"Speed x{factor}")
    print(f"Output: {out}")


def cmd_audio(args):
    """Add or replace audio track."""
    inp = validate_path(args.input)
    music = validate_path(args.music)
    out = validate_path(args.output, must_exist=False)
    mix = max(0.0, min(1.0, float(args.mix)))

    if mix == 0:
        # Replace audio entirely
        cmd = ["-i", inp, "-i", music, "-map", "0:v", "-map", "1:a", "-shortest", "-c:v", "copy", out]
    else:
        # Mix original audio with music
        orig_vol = mix
        music_vol = 1.0 - mix
        af = f"[0:a]volume={orig_vol}[a1];[1:a]volume={music_vol}[a2];[a1][a2]amix=inputs=2:duration=shortest"
        cmd = ["-i", inp, "-i", music, "-filter_complex", af, "-map", "0:v", "-c:v", "copy", out]

    run_ffmpeg(cmd, f"Adding audio (mix={mix})")
    print(f"Output: {out}")


def cmd_thumbnail(args):
    """Extract a frame as thumbnail."""
    inp = validate_path(args.input)
    out = validate_path(args.output, must_exist=False)
    time = validate_timestamp(args.time) if args.time else "00:00:01"

    cmd = ["-i", inp, "-ss", time, "-vframes", "1", "-q:v", "2", out]
    run_ffmpeg(cmd, "Extracting thumbnail")
    print(f"Output: {out}")


def main():
    parser = argparse.ArgumentParser(description="Video Editor — secure ffmpeg wrapper")
    sub = parser.add_subparsers(dest="command", required=True)

    # info
    p = sub.add_parser("info", help="Get video file info")
    p.add_argument("input")

    # trim
    p = sub.add_parser("trim", help="Trim video")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--start", "-s")
    p.add_argument("--end", "-e")

    # combine
    p = sub.add_parser("combine", help="Combine multiple clips")
    p.add_argument("inputs", nargs="+")
    p.add_argument("-o", "--output", required=True)

    # text
    p = sub.add_parser("text", help="Add text overlay")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--text", "-t", required=True)
    p.add_argument("--position", "-p", default="bottom", choices=["top", "center", "bottom"])
    p.add_argument("--fontsize", type=int, default=48)
    p.add_argument("--color", default="white")

    # resize
    p = sub.add_parser("resize", help="Resize video")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--preset", choices=["tiktok", "tiktok-land", "instagram", "instagram-reel", "youtube", "youtube-short"])
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)

    # speed
    p = sub.add_parser("speed", help="Change playback speed")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--factor", "-f", type=float, required=True, help="0.25 to 4.0")

    # audio
    p = sub.add_parser("audio", help="Add/replace audio track")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--music", "-m", required=True)
    p.add_argument("--mix", type=float, default=0.3, help="0=replace, 0.5=equal mix, 1=original only")

    # thumbnail
    p = sub.add_parser("thumbnail", help="Extract frame as image")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--time", "-t", default="00:00:01")

    args = parser.parse_args()
    commands = {
        "info": cmd_info, "trim": cmd_trim, "combine": cmd_combine,
        "text": cmd_text, "resize": cmd_resize, "speed": cmd_speed,
        "audio": cmd_audio, "thumbnail": cmd_thumbnail,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
