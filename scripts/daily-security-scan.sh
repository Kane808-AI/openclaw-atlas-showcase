#!/bin/bash
# daily-security-scan.sh — Daily security scan for OpenClaw/Atlas infrastructure
#
# Checks:
#   A. Secrets exposure (plist key count, git-tracked secrets, recent commit leaks)
#   B. Network exposure (listening ports, public-facing services)
#   C. Infrastructure drift (node path, gateway health, launchd service status)
#   D. File permissions (credentials/, agents/*/auth-profiles.json, .env)
#
# Alerting (Telegram): only on new findings, CRITICAL/HIGH severity, or Sunday all-clear
# Baseline: ~/.openclaw/scripts/security-baseline.json (created on first run)
# Log: ~/.openclaw/logs/security-scan/YYYY-MM-DD.log

set -o pipefail

# ─── Paths ────────────────────────────────────────────────────────────────────
HOME_DIR="/Users/chriskaneshiro"
OPENCLAW_DIR="$HOME_DIR/.openclaw"
WORKSPACE_DIR="$OPENCLAW_DIR/workspace"
PLIST_PATH="$HOME_DIR/Library/LaunchAgents/ai.openclaw.gateway.plist"
CREDENTIALS_DIR="$OPENCLAW_DIR/credentials"
AGENTS_DIR="$OPENCLAW_DIR/agents"
LOG_DIR="$OPENCLAW_DIR/logs/security-scan"
BASELINE_FILE="$OPENCLAW_DIR/scripts/security-baseline.json"

# Use the venv python3 if available, fall back to system
PY3="$OPENCLAW_DIR/venv/google/bin/python3"
if [ ! -x "$PY3" ]; then
    PY3="$(command -v python3 2>/dev/null || echo '/usr/bin/python3')"
fi

TODAY="$(date +%Y-%m-%d)"
TIMESTAMP="$(date +%Y-%m-%dT%H:%M:%S)"
LOG_FILE="$LOG_DIR/$TODAY.log"
DOW="$(date +%u)"  # 1=Mon, 7=Sun
IS_SUNDAY=false
[ "$DOW" -eq 7 ] && IS_SUNDAY=true

TELEGRAM_CHAT_ID="7556461717"

# ─── Setup ────────────────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date +%H:%M:%S)] $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Security scan started: $TIMESTAMP"
log "=========================================="

# ─── Telegram ─────────────────────────────────────────────────────────────────
# Token read at runtime from plist — never hardcoded in this script
TELEGRAM_BOT_TOKEN="REDACTED_SET_VIA_ENV"$PLIST_PATH" 2>/dev/null || true)"

send_telegram() {
    local msg="$1"
    if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
        log "WARNING: Could not read TELEGRAM_BOT_TOKEN from plist — skipping Telegram"
        return 0
    fi
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${msg}" \
        -d "parse_mode=Markdown" > /dev/null 2>&1 || log "WARNING: Telegram send failed"
}

# ─── Findings tracking ────────────────────────────────────────────────────────
FINDINGS=()
MAX_SEVERITY=""

# finding SEVERITY "description"
finding() {
    local severity="$1"
    local desc="$2"
    FINDINGS+=("[$severity] $desc")
    log "[SECURITY] $severity — $desc"
    case "$severity" in
        CRITICAL) MAX_SEVERITY="CRITICAL" ;;
        HIGH)     [ "$MAX_SEVERITY" != "CRITICAL" ] && MAX_SEVERITY="HIGH" ;;
        MEDIUM)   [ "$MAX_SEVERITY" != "CRITICAL" ] && [ "$MAX_SEVERITY" != "HIGH" ] && MAX_SEVERITY="MEDIUM" ;;
        LOW)      [ -z "$MAX_SEVERITY" ] && MAX_SEVERITY="LOW" ;;
    esac
}

# ─── Baseline helpers ─────────────────────────────────────────────────────────
BASELINE_EXISTS=false
[ -f "$BASELINE_FILE" ] && BASELINE_EXISTS=true

# Read a string or number field from the baseline JSON
baseline_get() {
    local key="$1" default="$2"
    "$PY3" - "$BASELINE_FILE" "$key" "$default" 2>/dev/null <<'PYEOF'
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    val = d.get(sys.argv[2])
    if val is None:
        print(sys.argv[3])
    elif isinstance(val, list):
        print(json.dumps(val))
    else:
        print(val)
except Exception:
    print(sys.argv[3])
PYEOF
}

# ─── A. SECRETS EXPOSURE ──────────────────────────────────────────────────────
log "--- A. Secrets Exposure ---"

# A1. Count env var entries in gateway plist whose name contains KEY, TOKEN, SECRET, or API
#     These are credentials stored in plaintext in the plist.
PLIST_KEY_COUNT="$(grep -oE '<key>[A-Z0-9_]*(KEY|TOKEN|SECRET|API)[A-Z0-9_]*</key>' "$PLIST_PATH" 2>/dev/null \
    | sort -u | wc -l | tr -d '[:space:]')" || PLIST_KEY_COUNT="0"
log "Plist credential entries: $PLIST_KEY_COUNT"

if [ "$BASELINE_EXISTS" = true ]; then
    EXPECTED_KEY_COUNT="$(baseline_get 'expected_plist_key_count' '0')"
    if [ "$PLIST_KEY_COUNT" != "$EXPECTED_KEY_COUNT" ]; then
        finding "MEDIUM" "Plist credential key count changed: expected $EXPECTED_KEY_COUNT, found $PLIST_KEY_COUNT — review $PLIST_PATH"
    else
        log "Plist key count OK: $PLIST_KEY_COUNT"
    fi
fi

# A2. Check for sensitive file patterns tracked in git
log "Checking git-tracked secret files..."
TRACKED_SECRETS="REDACTED_SET_VIA_ENV"$WORKSPACE_DIR" ls-files 2>/dev/null \
    | grep -E '(\.env$|auth-profiles\.json|recovery-token\.txt|credentials\.json|\.key$|\.pem$|personal-token\.json|service-account\.json)' \
    || true)"
if [ -n "$TRACKED_SECRETS" ]; then
    while IFS= read -r tracked_file; do
        [ -z "$tracked_file" ] && continue
        finding "CRITICAL" "Secret file tracked in git: $tracked_file — fix: git rm --cached '$tracked_file'"
    done <<< "$TRACKED_SECRETS"
else
    log "No secret files tracked in git"
fi

# A3. Scan commits added in the last 24h for potential key leaks
log "Scanning recent commits for key leaks..."
RECENT_LEAK="$(git -C "$WORKSPACE_DIR" log --since="24 hours ago" --diff-filter=A -p 2>/dev/null \
    | grep -iE '(api_key|api-key|apikey|secret|password)' \
    | grep -vE '^(---|\+\+\+|@@|diff |index |#|//|\*)' \
    | head -5 || true)"
if [ -n "$RECENT_LEAK" ]; then
    finding "HIGH" "Potential key leak in recent git commits — review: git -C $WORKSPACE_DIR log --since='24 hours ago' --diff-filter=A -p"
else
    log "No key leaks detected in recent commits"
fi

# ─── B. NETWORK EXPOSURE ──────────────────────────────────────────────────────
log "--- B. Network Exposure ---"

# Gather listening ports — try lsof first, fall back to netstat
LISTEN_OUTPUT="$(lsof -i -P -n 2>/dev/null | grep LISTEN || true)"
if [ -z "$LISTEN_OUTPUT" ]; then
    # lsof may return nothing due to macOS permissions; try netstat
    LISTEN_OUTPUT="$(netstat -an 2>/dev/null | grep -E '(\.LISTEN|LISTEN)' || true)"
fi

PUBLIC_PORTS=()   # ports bound to all interfaces (0.0.0.0 or *)
ALL_PORTS=()      # all listening ports

if [ -n "$LISTEN_OUTPUT" ]; then
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # Detect public-facing bindings: *:<port> or 0.0.0.0:<port>
        if echo "$line" | grep -qE '(\*|0\.0\.0\.0):[0-9]+ \(LISTEN\)'; then
            port="$(echo "$line" | grep -oE '(\*|0\.0\.0\.0):([0-9]+)' | grep -oE '[0-9]+$')"
            proc="$(echo "$line" | awk '{print $1}')"
            [ -n "$port" ] && PUBLIC_PORTS+=("$port/$proc")
        fi
        # Collect all listening ports
        port="$(echo "$line" | grep -oE ':[0-9]+ \(LISTEN\)' | grep -oE '[0-9]+' | head -1)"
        [ -n "$port" ] && ALL_PORTS+=("$port")
    done <<< "$LISTEN_OUTPUT"
    log "Listening ports found: ${#ALL_PORTS[@]}"
    log "Public-facing ports: ${PUBLIC_PORTS[*]:-none}"
else
    log "WARNING: Could not enumerate listening ports (lsof/netstat returned nothing)"
fi

if [ "$BASELINE_EXISTS" = true ] && [ -n "$LISTEN_OUTPUT" ]; then
    # Flag new public-facing ports not in the baseline allowlist
    ALLOWED_PUBLIC="$(baseline_get 'allowed_public_ports' '[]')"
    ALLOWED_PROCS="$(baseline_get 'allowed_public_processes' '[]')"
    for pp in "${PUBLIC_PORTS[@]+"${PUBLIC_PORTS[@]}"}"; do
        port="${pp%%/*}"
        proc="${pp##*/}"
        if ! echo "$ALLOWED_PUBLIC" | grep -q "\"$port\"" \
           && ! echo "$ALLOWED_PROCS" | grep -q "\"$proc\""; then
            finding "CRITICAL" "Port $port bound to all interfaces ($proc) — not in allowed_public_ports baseline"
        fi
    done

    # Check expected local ports are present
    for expected_port in 18789 18794 5678 13337; do
        if ! printf '%s\n' "${ALL_PORTS[@]+"${ALL_PORTS[@]}"}" | grep -q "^${expected_port}$"; then
            finding "MEDIUM" "Expected port $expected_port not listening — associated service may be down"
        fi
    done
fi

# ─── C. INFRASTRUCTURE DRIFT ──────────────────────────────────────────────────
log "--- C. Infrastructure Drift ---"

# C1. Verify node binary referenced in gateway plist still exists
NODE_PATH="$(plutil -extract ProgramArguments.0 raw "$PLIST_PATH" 2>/dev/null || true)"
if [ -n "$NODE_PATH" ]; then
    if [ ! -x "$NODE_PATH" ]; then
        finding "LOW" "Node binary in gateway plist no longer exists: $NODE_PATH — gateway may fail after nvm change"
    else
        log "Node binary OK: $NODE_PATH"
    fi
else
    log "WARNING: Could not read ProgramArguments from gateway plist"
fi

# C2. Gateway health check
log "Checking gateway health (http://127.0.0.1:18789/health)..."
# curl writes "%{http_code}" to stdout even on connection failure (outputs "000").
# Using "; true" prevents the "|| echo '000'" doubling bug where both curl's "000"
# and the fallback echo "000" get concatenated into "000000".
GATEWAY_STATUS="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 'http://127.0.0.1:18789/health' 2>/dev/null; true)"
[ -z "$GATEWAY_STATUS" ] && GATEWAY_STATUS="000"
if [ "$GATEWAY_STATUS" = "200" ]; then
    log "Gateway health: OK (HTTP 200)"
else
    finding "HIGH" "Gateway health check failed: HTTP $GATEWAY_STATUS on /health endpoint"
fi

# C3. Check critical launchd services are running (PID column, not exit code)
#     Exit code -15 can be stale from a prior SIGTERM even when service is running —
#     the PID column is the authoritative indicator of whether a service is live.
log "Checking launchd services..."
CRITICAL_SERVICES=(
    "ai.openclaw.gateway"
    "ai.openclaw.workspace-sync"
    "ai.openclaw.vault-mcp"
    "ai.openclaw.ryan-verify-server"
    "com.openclaw.n8n"
    "ai.openclaw.mcp-server"
)
for svc in "${CRITICAL_SERVICES[@]}"; do
    svc_line="$(launchctl list 2>/dev/null | grep -F "$svc" || true)"
    if [ -z "$svc_line" ]; then
        finding "HIGH" "Service not registered with launchd: $svc"
    else
        pid_col="$(echo "$svc_line" | awk '{print $1}')"
        if [ "$pid_col" = "-" ]; then
            finding "HIGH" "Service registered but not running (PID -): $svc"
        else
            log "Service $svc: running (PID $pid_col)"
        fi
    fi
done

# ─── D. FILE PERMISSIONS ──────────────────────────────────────────────────────
log "--- D. File Permissions ---"

# Helper: check a path's octal permissions and flag if not expected
check_perms() {
    local path="$1" expected="$2" label="$3"
    local actual
    actual="$(stat -f '%OLp' "$path" 2>/dev/null || true)"
    if [ -z "$actual" ]; then
        log "WARNING: Could not stat $path"
        return
    fi
    if [ "$actual" != "$expected" ]; then
        finding "MEDIUM" "$label has permissions $actual — should be $expected (fix: chmod $expected '$path')"
    else
        log "Permissions OK ($actual): $path"
    fi
}

# Credentials directory itself should be 700
if [ -d "$CREDENTIALS_DIR" ]; then
    check_perms "$CREDENTIALS_DIR" "700" "credentials/"
    # All files inside should be 600
    while IFS= read -r -d '' cfile; do
        check_perms "$cfile" "600" "credentials/$(basename "$cfile")"
    done < <(find "$CREDENTIALS_DIR" -type f -print0 2>/dev/null)
fi

# All auth-profiles.json files under agents/ should be 600
while IFS= read -r -d '' afile; do
    check_perms "$afile" "600" "agents/.../auth-profiles.json"
done < <(find "$AGENTS_DIR" -name "auth-profiles.json" -print0 2>/dev/null)

# .env should be 600
ENV_FILE="$OPENCLAW_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    check_perms "$ENV_FILE" "600" ".env"
fi

# ─── E. RESULTS & ALERTING ────────────────────────────────────────────────────
log "--- E. Results ---"
FINDINGS_COUNT="${#FINDINGS[@]}"
log "Total findings: $FINDINGS_COUNT"
log "Max severity: ${MAX_SEVERITY:-none}"

# Serialize findings to a sorted JSON array for comparison with baseline
CURRENT_FINDINGS_JSON="$("$PY3" - "${FINDINGS[@]+"${FINDINGS[@]}"}" 2>/dev/null <<'PYEOF'
import json, sys
lines = [a for a in sys.argv[1:] if a]
print(json.dumps(sorted(lines)))
PYEOF
)"
CURRENT_FINDINGS_JSON="${CURRENT_FINDINGS_JSON:-[]}"

# Determine if we should send a Telegram alert
SHOULD_ALERT=false
ALERT_MSG=""

if [ "$BASELINE_EXISTS" = false ]; then
    # First run: always send baseline establishment message
    SHOULD_ALERT=true
    ALERT_MSG="*🔐 Security Scanner: Baseline Established — $TODAY*

Initial scan complete. Review the initial state before the scanner will flag deviations.

Plist credential entries: $PLIST_KEY_COUNT"
    if [ "$FINDINGS_COUNT" -gt 0 ]; then
        ALERT_MSG+="

*Initial findings ($FINDINGS_COUNT):*"
        for f in "${FINDINGS[@]}"; do
            ALERT_MSG+="
• $f"
        done
    else
        ALERT_MSG+="

No issues found on initial scan. ✅"
    fi
    ALERT_MSG+="

Scanner runs daily at 7:55 AM PT. Alert on new findings or CRITICAL/HIGH severity only."

elif [ "$FINDINGS_COUNT" -gt 0 ]; then
    # Subsequent run with findings — only alert if findings changed or severity is high
    LAST_FINDINGS="$(baseline_get 'last_findings' '[]')"
    if [ "$CURRENT_FINDINGS_JSON" != "$LAST_FINDINGS" ] \
        || [ "$MAX_SEVERITY" = "CRITICAL" ] \
        || [ "$MAX_SEVERITY" = "HIGH" ]; then
        SHOULD_ALERT=true
        ALERT_MSG="*🔐 Security Scan Findings — $TODAY*
Max severity: *${MAX_SEVERITY}*"
        for f in "${FINDINGS[@]}"; do
            ALERT_MSG+="
• $f"
        done
    fi

elif [ "$IS_SUNDAY" = true ]; then
    # Weekly all-clear — confirms scanner is running even with no issues
    SHOULD_ALERT=true
    ALERT_MSG="🔐 Weekly security all-clear — $TODAY. No issues detected."
fi

if [ "$SHOULD_ALERT" = true ]; then
    send_telegram "$ALERT_MSG"
    log "Telegram alert sent"
else
    log "No alert sent (clean scan, no state change)"
fi

# ─── F. UPDATE BASELINE ───────────────────────────────────────────────────────
log "--- F. Updating baseline ---"

# Capture current public ports for baseline storage
PUBLIC_PORTS_JSON="$("$PY3" - "${PUBLIC_PORTS[@]+"${PUBLIC_PORTS[@]}"}" 2>/dev/null <<'PYEOF'
import json, sys
# Strip process name suffix (e.g. "5678/node" → "5678")
ports = sorted(set(a.split('/')[0] for a in sys.argv[1:] if a))
print(json.dumps(ports))
PYEOF
)"
PUBLIC_PORTS_JSON="${PUBLIC_PORTS_JSON:-[]}"

if [ "$BASELINE_EXISTS" = false ]; then
    # Create baseline from current state
    "$PY3" - "$BASELINE_FILE" "$TODAY" "$PLIST_KEY_COUNT" "$PUBLIC_PORTS_JSON" "$CURRENT_FINDINGS_JSON" 2>/dev/null <<'PYEOF'
import json, sys
baseline = {
    "expected_plist_key_count": int(sys.argv[3]),
    "allowed_public_ports": json.loads(sys.argv[4]),
    "expected_local_ports": [18789, 18794, 5678, 13337],
    "expected_services": [
        "ai.openclaw.gateway",
        "ai.openclaw.workspace-sync",
        "ai.openclaw.vault-mcp",
        "ai.openclaw.ryan-verify-server",
        "com.openclaw.n8n",
        "ai.openclaw.mcp-server"
    ],
    "last_clean_scan": None,
    "scan_history_days": 30,
    "last_findings": json.loads(sys.argv[5]),
    "first_run_date": sys.argv[2]
}
with open(sys.argv[1], 'w') as f:
    json.dump(baseline, f, indent=2)
print("Baseline written")
PYEOF
    log "Baseline file created: $BASELINE_FILE"
else
    # Update last_findings and last_clean_scan if clean
    "$PY3" - "$BASELINE_FILE" "$CURRENT_FINDINGS_JSON" "$TODAY" "$FINDINGS_COUNT" 2>/dev/null <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    baseline = json.load(f)
baseline["last_findings"] = json.loads(sys.argv[2])
if int(sys.argv[4]) == 0:
    baseline["last_clean_scan"] = sys.argv[3]
with open(sys.argv[1], 'w') as f:
    json.dump(baseline, f, indent=2)
PYEOF
    log "Baseline updated"
fi

log "=========================================="
log "Scan complete: $(date +%H:%M:%S) | Findings: $FINDINGS_COUNT | Severity: ${MAX_SEVERITY:-none}"
log "=========================================="
