#!/usr/bin/env bash
# claude-code-delegate.sh — Direct Claude Code delegation for Atlas
# Called via exec tool: exec("bash ~/.openclaw/scripts/claude-code-delegate.sh --prompt '...'")
# Supports sync (default) and async modes. Returns JSON on stdout.

set -euo pipefail

# Explicit PATH — nvm node first (required for claude CLI)
export PATH="$HOME/.nvm/versions/node/v22.22.0/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export NO_COLOR=1
# Clear any stale API key so Claude Code uses OAuth token instead
unset ANTHROPIC_API_KEY

CLAUDE_BIN="${HOME}/.local/bin/claude"
RESULTS_DIR="${HOME}/.openclaw/workspace/cowork-tasks/cc-results"
DEFAULT_CWD="${HOME}/.openclaw"
DEFAULT_MODEL="sonnet"
DEFAULT_TIMEOUT=300

# Parse arguments
PROMPT=""
CWD="$DEFAULT_CWD"
MODEL="$DEFAULT_MODEL"
TIMEOUT="$DEFAULT_TIMEOUT"
ASYNC=false
STATUS_ID=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prompt) PROMPT="$2"; shift 2 ;;
        --cwd) CWD="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --timeout) TIMEOUT="$2"; shift 2 ;;
        --async) ASYNC=true; shift ;;
        --status) STATUS_ID="$2"; shift 2 ;;
        *) echo "{\"status\":\"error\",\"error\":\"Unknown argument: $1\"}"; exit 1 ;;
    esac
done

# --- Status check mode ---
if [[ -n "$STATUS_ID" ]]; then
    meta_file="${RESULTS_DIR}/${STATUS_ID}.meta.json"
    result_file="${RESULTS_DIR}/${STATUS_ID}.txt"

    if [[ ! -f "$meta_file" ]]; then
        echo "{\"status\":\"error\",\"error\":\"Task not found: ${STATUS_ID}\"}"
        exit 1
    fi

    pid=$(python3 -c "import json; print(json.load(open('${meta_file}')).get('pid',''))")

    if kill -0 "$pid" 2>/dev/null; then
        partial=""
        if [[ -f "$result_file" ]]; then
            partial=$(tail -c 2000 "$result_file" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" | sed 's/^"//;s/"$//')
        fi
        echo "{\"status\":\"running\",\"task_id\":\"${STATUS_ID}\",\"pid\":${pid},\"partial_output\":\"${partial}\"}"
    else
        output=""
        if [[ -f "$result_file" ]]; then
            output=$(python3 -c "
import json, sys
with open('${result_file}') as f:
    content = f.read().strip()
# Truncate to 50K to avoid overwhelming Atlas
print(json.dumps(content[:50000]))
")
        fi
        echo "{\"status\":\"complete\",\"task_id\":\"${STATUS_ID}\",\"output\":${output:-'\"\"'}}"
    fi
    exit 0
fi

# --- Require prompt ---
if [[ -z "$PROMPT" ]]; then
    echo "{\"status\":\"error\",\"error\":\"--prompt is required\"}"
    exit 1
fi

# --- Async mode ---
if [[ "$ASYNC" == true ]]; then
    mkdir -p "$RESULTS_DIR"
    task_id=$(python3 -c "import uuid; print(uuid.uuid4().hex[:12])")
    result_file="${RESULTS_DIR}/${task_id}.txt"
    meta_file="${RESULTS_DIR}/${task_id}.meta.json"

    # Launch Claude Code in background
    "$CLAUDE_BIN" -p \
        --model "$MODEL" \
        --no-session-persistence \
        --permission-mode bypassPermissions \
        "$PROMPT" \
        < /dev/null \
        > "$result_file" 2>&1 &
    bg_pid=$!

    # Write metadata
    python3 -c "
import json
from datetime import datetime, timezone
meta = {
    'task_id': '${task_id}',
    'pid': ${bg_pid},
    'status': 'running',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'prompt_preview': '''${PROMPT}'''[:200],
    'cwd': '${CWD}',
    'model': '${MODEL}',
    'result_file': '${result_file}'
}
with open('${meta_file}', 'w') as f:
    json.dump(meta, f, indent=2)
"

    echo "{\"status\":\"launched\",\"task_id\":\"${task_id}\",\"pid\":${bg_pid}}"
    exit 0
fi

# --- Sync mode (default) ---
start_time=$(date +%s)

# Run Claude Code with timeout (macOS-native: background + wait + kill)
tmpfile=$(mktemp /tmp/cc-delegate.XXXXXX)
trap "rm -f '$tmpfile'" EXIT

set +e
"$CLAUDE_BIN" -p \
    --model "$MODEL" \
    --no-session-persistence \
    --permission-mode bypassPermissions \
    --max-budget-usd 2.00 \
    "$PROMPT" \
    < /dev/null > "$tmpfile" 2>&1 &
bg_pid=$!

elapsed=0
while kill -0 "$bg_pid" 2>/dev/null && [[ $elapsed -lt $TIMEOUT ]]; do
    sleep 1
    elapsed=$((elapsed + 1))
done

if kill -0 "$bg_pid" 2>/dev/null; then
    kill "$bg_pid" 2>/dev/null
    wait "$bg_pid" 2>/dev/null
    exit_code=124
else
    wait "$bg_pid"
    exit_code=$?
fi

output=$(cat "$tmpfile")
set -e

end_time=$(date +%s)
duration=$((end_time - start_time))

# Build JSON response — pipe output via stdin to avoid shell quoting issues
python3 -c "
import json, sys
output = sys.stdin.read().strip()
exit_code = ${exit_code}
duration = ${duration}
timeout_secs = ${TIMEOUT}
if exit_code == 124:
    print(json.dumps({
        'status': 'error',
        'error': f'Timeout after {timeout_secs} seconds',
        'partial_output': output[:10000],
        'exit_code': 124,
        'duration_seconds': duration
    }))
elif exit_code == 0:
    print(json.dumps({
        'status': 'complete',
        'output': output[:50000],
        'exit_code': 0,
        'duration_seconds': duration
    }))
else:
    print(json.dumps({
        'status': 'error',
        'output': output[:50000],
        'exit_code': exit_code,
        'duration_seconds': duration
    }))
" < "$tmpfile"
