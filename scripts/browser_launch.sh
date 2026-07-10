#!/usr/bin/env bash
# browser_launch.sh — the only sanctioned way for agents to open a browser.
#
# Launches Brave Browser with Atlas's dedicated profile. Refuses any other
# browser, binary, or profile. Optional first arg = URL to open.
#
# Why: agents kept opening system Chrome or unsigned Brave instances and
# losing their logged-in sessions. The rule lives in AGENTS.md but was
# unenforceable at runtime — this wrapper enforces it.

set -euo pipefail

readonly ATLAS_PROFILE="$HOME/.openclaw/data/browser/profiles/atlas"
readonly BRAVE_APP="/Applications/Brave Browser.app"
readonly BRAVE_BIN="$BRAVE_APP/Contents/MacOS/Brave Browser"

die() {
  echo "[browser_launch] REFUSED: $*" >&2
  echo "[browser_launch] Atlas only opens Brave with the atlas profile. No exceptions." >&2
  exit 1
}

# --- Reject misuse ---------------------------------------------------------

# Accept either no args, or exactly one URL.
if [ "$#" -gt 1 ]; then
  die "too many args. Usage: browser_launch.sh [URL]"
fi

URL="${1:-}"

# If a URL was passed, sanity check it: must be http(s) or file: scheme.
# Reject `--user-data-dir=` overrides, `--profile-directory`, or anything
# that tries to redirect to a different profile or browser binary.
if [ -n "$URL" ]; then
  case "$URL" in
    -*)
      die "URL cannot start with a dash ('$URL'). Pass a real URL or nothing."
      ;;
    http://*|https://*|file://*|about:*)
      : ;;
    *)
      die "URL must be http://, https://, file://, or about: ('$URL')"
      ;;
  esac
fi

# --- Validate target browser + profile ------------------------------------

if [ ! -d "$BRAVE_APP" ]; then
  die "Brave Browser not installed at $BRAVE_APP"
fi
if [ ! -x "$BRAVE_BIN" ]; then
  die "Brave binary missing or not executable: $BRAVE_BIN"
fi
if [ ! -d "$ATLAS_PROFILE" ]; then
  die "Atlas profile dir missing: $ATLAS_PROFILE"
fi
if [ ! -d "$ATLAS_PROFILE/Default" ]; then
  die "Atlas profile looks corrupt — no Default/ subdir at $ATLAS_PROFILE"
fi

# --- Launch ----------------------------------------------------------------

echo "[browser_launch] Brave + atlas profile: $ATLAS_PROFILE${URL:+  →  $URL}"

# Use `open -na` so we get a fresh process tied to this profile. Without
# -n, macOS reuses any existing Brave window (which may be on the wrong
# profile). --args passes everything after to Brave itself.
if [ -n "$URL" ]; then
  exec /usr/bin/open -na "$BRAVE_APP" --args \
    "--user-data-dir=$ATLAS_PROFILE" \
    "--profile-directory=Default" \
    "$URL"
else
  exec /usr/bin/open -na "$BRAVE_APP" --args \
    "--user-data-dir=$ATLAS_PROFILE" \
    "--profile-directory=Default"
fi
