#!/usr/bin/env bash
# fix_exec_allowlist.sh — Correct config paths + gateway restart
# Run once: bash ~/.openclaw/scripts/fix_exec_allowlist.sh

set -uo pipefail
export PATH="$HOME/.nvm/versions/node/v22.22.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

echo "=== OpenClaw Config Fix Script ==="
echo ""

echo "1. Testing exec allowlist paths..."
# Try global tools.exec.allow (correct JSON path)
openclaw config set tools.exec.allow '["**"]' 2>&1 && echo "  ✅ tools.exec.allow set to [\"**\"]" || echo "  ⚠️ tools.exec.allow path failed"

echo ""
echo "2. Testing agentToAgent paths..."
# Try the path OpenClaw's own error message says to use
openclaw config set tools.agentToAgent.enabled true 2>&1 && echo "  ✅ tools.agentToAgent.enabled = true" || echo "  ⚠️ agentToAgent path failed"

echo ""
echo "3. Current exec config:"
openclaw config get tools.exec 2>&1 || echo "  (no output)"

echo ""
echo "4. Current agentToAgent config:"
openclaw config get tools.agentToAgent 2>&1 || echo "  (no output — may need full gateway read)"

echo ""
echo "5. Clearing any stuck copywriter session label..."
SESSION_FILE="$HOME/.openclaw/agents/copywriter/sessions/sessions.json"
if [ -f "$SESSION_FILE" ]; then
    python3 - <<'PYEOF'
import json, os

session_file = os.path.expanduser("~/.openclaw/agents/copywriter/sessions/sessions.json")
with open(session_file) as f:
    data = json.load(f)

removed = 0
if isinstance(data, list):
    cleaned = [s for s in data if 'muse-amazon-research' not in str(s.get('label',''))]
    removed = len(data) - len(cleaned)
    with open(session_file, 'w') as f:
        json.dump(cleaned, f, indent=2)
elif isinstance(data, dict):
    sessions = data.get('sessions', [])
    cleaned = [s for s in sessions if 'muse-amazon-research' not in str(s.get('label',''))]
    removed = len(sessions) - len(cleaned)
    data['sessions'] = cleaned
    with open(session_file, 'w') as f:
        json.dump(data, f, indent=2)

print(f"  Removed {removed} stuck session(s)")
PYEOF
else
    echo "  No sessions file found — skipping"
fi

echo ""
echo "6. Restarting gateway..."
openclaw gateway restart && echo "  ✅ Gateway restarted" || echo "  ⚠️ Gateway restart failed"

echo ""
echo "=== Done. Review output above for any ⚠️ warnings ==="
