#!/usr/bin/env bash
#
# export-from-openclaw.sh — Sanitizing one-way export from the private
# ~/.openclaw working repo into this public showcase repo.
#
# This is the ONLY sanctioned way to refresh the public repo. It copies a
# strict allowlist of portfolio files, redacts personal identifiers, and
# runs gitleaks as a hard gate. If gitleaks finds anything, the export
# aborts and nothing is staged for push.
#
# Usage:   tools/export-from-openclaw.sh
# Env:     SRC   source working repo   (default: ~/.openclaw)
#          DEST  this showcase repo    (default: repo root of this script)
#
# It never copies: .env*, auth-state/auth-profiles, sessions, browser data,
# node_modules, sqlite, secrets/, keys, backups, codex-home caches.

set -euo pipefail

SRC="${SRC:-$HOME/.openclaw}"
DEST="${DEST:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

if [[ ! -d "$SRC" ]]; then echo "SRC not found: $SRC" >&2; exit 1; fi
if [[ "$SRC" -ef "$DEST" ]]; then echo "SRC and DEST must differ" >&2; exit 1; fi

echo "Source: $SRC"
echo "Dest:   $DEST"

# ----------------------------------------------------------------------
# 1. Wipe previously-exported content (never touch .git / tools / README)
# ----------------------------------------------------------------------
for d in docs agents scripts automations skills mcp; do
  rm -rf "${DEST:?}/$d"
done

# ----------------------------------------------------------------------
# 2. Allowlist copy. rsync with explicit include/exclude — deny by default.
# ----------------------------------------------------------------------
EXCLUDES=(
  --exclude='*.env' --exclude='.env*' --exclude='*env*.json'
  --exclude='auth-state*' --exclude='auth-profiles*'
  --exclude='*.sqlite*' --exclude='*.pem' --exclude='*.key' --exclude='*.p12'
  --exclude='*credential*' --exclude='*secret*' --exclude='*token*'
  --exclude='*.bak' --exclude='*.bak.*' --exclude='*.broken*' --exclude='*.deleted*'
  --exclude='node_modules/' --exclude='codex-home/' --exclude='sessions/'
  --exclude='harness-auth/' --exclude='__pycache__/' --exclude='.DS_Store'
)

copy() {  # copy <relative-glob-parent> <rsync-filter...>
  local sub="$1"; shift
  [[ -e "$SRC/$sub" ]] || { echo "  skip (absent): $sub"; return 0; }
  mkdir -p "$DEST/$(dirname "$sub")"
  rsync -a "${EXCLUDES[@]}" "$@" "$SRC/$sub" "$DEST/$(dirname "$sub")/"
}

echo "==> copying master orchestration doc"
mkdir -p "$DEST/docs"
rsync -a "$SRC/AGENTS.md" "$DEST/docs/AGENTS.md"

echo "==> copying the 15 agent personas (AGENTS/SOUL/TOOLS only)"
mkdir -p "$DEST/agents"
while IFS= read -r agentdir; do
  name="$(basename "$(dirname "$agentdir")")"
  mkdir -p "$DEST/agents/$name"
  for f in AGENTS.md SOUL.md TOOLS.md; do
    [[ -f "$agentdir/$f" ]] && rsync -a "$agentdir/$f" "$DEST/agents/$name/$f"
  done
done < <(find "$SRC/agents" -maxdepth 2 -type d -name agent 2>/dev/null)

echo "==> copying automation scripts (env-driven, no secrets)"
mkdir -p "$DEST/scripts"
rsync -a "${EXCLUDES[@]}" \
  --include='*/' --include='*.py' --include='*.sh' --include='*.js' --exclude='*' \
  "$SRC/scripts/" "$DEST/scripts/"

echo "==> copying automations (docs/config only)"
copy "automations" --include='*/' --include='*.md' --include='*.py' --include='*.sh' --include='*.json' --include='*.yaml' --include='*.yml' --exclude='*'
# NOTE: skills/ is intentionally NOT exported — it is third-party vendored
# skill bundles (~7k files), not original work, and adds noise + risk.

echo "==> copying vault-mcp server source (top-level only, no node_modules)"
mkdir -p "$DEST/mcp/vault-mcp"
find "$SRC/vault-mcp" -maxdepth 1 -type f \( -name '*.js' -o -name '*.mjs' -o -name '*.md' -o -name 'package.json' \) \
  ! -name '*secret*' ! -name '*token*' -exec rsync -a {} "$DEST/mcp/vault-mcp/" \;

# ----------------------------------------------------------------------
# 3. Redaction pass over every copied TEXT file.
# ----------------------------------------------------------------------
echo "==> redacting personal identifiers"
find "$DEST" -type f \( -name '*.md' -o -name '*.py' -o -name '*.sh' -o -name '*.js' -o -name '*.mjs' -o -name '*.json' \) \
  -not -path '*/.git/*' -not -path '*/tools/*' -print0 |
while IFS= read -r -d '' f; do
  LC_ALL=C sed -i '' \
    -e 's/ckane703@gmail\.com/you@example.com/g' \
    -e 's/[0-9]\{3\}[-.][0-9]\{3\}[-.][0-9]\{4\}/[redacted-phone]/g' \
    -e 's#https://discord\.com/api/webhooks/[0-9A-Za-z_/-]*#[redacted-webhook]#g' \
    -e 's#https://hooks\.slack\.com/[0-9A-Za-z_/-]*#[redacted-webhook]#g' \
    -e 's/100\.\([0-9]\{1,3\}\.\)\{2\}[0-9]\{1,3\}/100.x.x.x/g' \
    -e 's/[a-z0-9-]\{3,\}\.ts\.net/tailnet.example.ts.net/g' \
    "$f"
  # Neutralize any hardcoded credential assignment: NAME = "literal" where
  # NAME looks sensitive. Value is replaced with a placeholder so the script
  # still demonstrates the pattern without leaking. Permanent rule, not a patch.
  perl -i -pe 's/((?:SECRET|TOKEN|API_?KEY|api_key|PASSWORD|CLIENT_SECRET|BEARER|PRIVATE_?KEY|ACCESS_?TOKEN)\w*\s*[:=]\s*)(["\x27])(?!https?:\/\/)[^"\x27]{8,}\2/${1}${2}REDACTED_SET_VIA_ENV${2}/gi' "$f"
done

# ----------------------------------------------------------------------
# 4. HARD GATE: gitleaks. Any finding aborts the export.
# ----------------------------------------------------------------------
echo "==> secret-scan gate (gitleaks)"
if command -v gitleaks >/dev/null 2>&1; then
  # Report goes to /tmp so it is never itself scanned or committed.
  # A committed .gitleaks.toml in DEST allowlists reviewed false positives.
  GLREPORT="/tmp/showcase-gitleaks.json"
  CFG=(); [[ -f "$DEST/.gitleaks.toml" ]] && CFG=(--config "$DEST/.gitleaks.toml")
  if ! gitleaks detect --no-git --source "$DEST" "${CFG[@]}" \
        --report-path "$GLREPORT" 2>/dev/null; then
    echo ""
    echo "!!! gitleaks found potential secrets — export ABORTED, nothing pushed." >&2
    echo "!!! review $GLREPORT" >&2
    exit 2
  fi
  echo "    clean."
else
  echo "!!! gitleaks not installed — refusing to certify clean. Install it first." >&2
  exit 3
fi

echo ""
echo "Export complete and secret-scan clean."
echo "Review 'git status' in $DEST, then commit and push manually."
