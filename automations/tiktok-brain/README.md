# TikTok Brain Automation

## Trigger
Any TikTok URL sent to Atlas via Telegram.

## Pipeline
1. **Download** — yt-dlp with Chrome cookies (`--cookies-from-browser chrome`)
2. **Transcribe** — faster-whisper (base model, CPU, int8)
3. **Google Doc** — Create doc titled: `TikTok - [YYYY-MM-DD] - [first 8 words of transcript]`
   - Contents: Original URL, full transcript
4. **Google Sheet** — Append row to "TikTok Brain" sheet
   - Columns: Date | URL | Summary (3 sentences) | Tags | Doc Link | Status
   - Status default: "New"
5. **Telegram Reply** — Send summary + doc link back to Chris

## Dependencies
- yt-dlp (with Chrome cookies access)
- faster-whisper (base model)
- Google Docs API (Brand75 credentials)
- Google Sheets API (Brand75 credentials)
- Sheet ID: [PENDING]

## Files
- `tiktok_brain.py` — Main automation script
- `README.md` — This file

## Status
- [x] Spec saved
- [x] Download + transcribe pipeline
- [ ] Google Docs integration (awaiting credentials confirmation)
- [ ] Google Sheets integration (awaiting Sheet ID)
- [ ] End-to-end test
