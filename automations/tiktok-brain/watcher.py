#!/usr/bin/env python3
"""
TikTok Brain Watch Folder
Watches ~/.openclaw/workspace/inbox for new video files and auto-processes them.
On startup, scans for any videos already present so restarts never lose the backlog.
"""
import sys, os, time, subprocess, urllib.request, urllib.parse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCH_FOLDER = os.path.expanduser("~/.openclaw/workspace/inbox")
SCRIPT = os.path.expanduser("~/.openclaw/automations/tiktok-brain/tiktok_brain.py")
TELEGRAM_TOKEN_FILE = os.path.expanduser("~/.openclaw/secrets/telegram-bot-token")
TELEGRAM_CHAT_ID = "7556461717"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}


def notify_telegram(message):
    try:
        with open(TELEGRAM_TOKEN_FILE) as f:
            token = f.read().strip()
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode()
        urllib.request.urlopen(url, data=data, timeout=10).read()
    except Exception as e:
        print(f"Telegram notify failed: {e}", flush=True)


class VideoHandler(FileSystemEventHandler):
    def __init__(self):
        self.processed = set()

    def process_video(self, path):
        if path in self.processed:
            return
        self.processed.add(path)
        print(f"Processing: {path}", flush=True)
        time.sleep(3)  # Wait for file to finish copying

        result = subprocess.run(
            [sys.executable, SCRIPT, path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"ERROR: tiktok_brain.py failed for {path}", flush=True)
            print(result.stderr[-2000:], flush=True)
            self.processed.discard(path)  # allow retry on next restart
            return

        if result.stdout:
            print(result.stdout, flush=True)

        notify_telegram(f"🧠 TikTok Brain: processed {os.path.basename(path)}")

        processed_folder = os.path.join(WATCH_FOLDER, "processed")
        os.makedirs(processed_folder, exist_ok=True)
        destination = os.path.join(processed_folder, os.path.basename(path))
        try:
            if os.path.exists(path):
                os.rename(path, destination)
                print(f"Moved to processed/: {os.path.basename(path)}", flush=True)
            else:
                print(f"Warning: file already moved or deleted: {path}", flush=True)
        except FileNotFoundError:
            print(f"Warning: file vanished before move: {path}", flush=True)

    def on_created(self, event):
        if event.is_directory:
            return
        if os.path.splitext(event.src_path)[1].lower() in VIDEO_EXTENSIONS:
            self.process_video(event.src_path)


if __name__ == "__main__":
    print(f"Watching {WATCH_FOLDER} for new videos...", flush=True)
    handler = VideoHandler()
    observer = Observer()
    observer.schedule(handler, WATCH_FOLDER, recursive=False)
    observer.start()

    # Startup scan — process any videos already in inbox before this session started
    print("Scanning inbox for existing videos...", flush=True)
    for fname in sorted(os.listdir(WATCH_FOLDER)):
        full = os.path.join(WATCH_FOLDER, fname)
        if os.path.isfile(full) and os.path.splitext(fname)[1].lower() in VIDEO_EXTENSIONS:
            handler.process_video(full)
    print("Startup scan complete.", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
