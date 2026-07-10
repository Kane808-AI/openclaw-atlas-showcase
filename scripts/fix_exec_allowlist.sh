#!/usr/bin/env bash
# fix_exec_allowlist.sh — showcase-safe config audit helper.
#
# The private system once used this kind of script to inspect OpenClaw config,
# but the public showcase must not encourage unrestricted shell execution. This
# file is intentionally read-only: it prints the current config and recommends a
# narrow allowlist instead of mutating anything.

set -euo pipefail

echo "=== OpenClaw Exec Allowlist Audit ==="
echo ""

echo "Current exec config:"
openclaw config get tools.exec 2>&1 || echo "  (no tools.exec config found)"

echo ""
echo "Recommended pattern for production:"
echo '  openclaw config set tools.exec.allow ["git","rg","python3 -m pytest"]'
echo ""
echo "Avoid broad rules such as [\"**\"] in shared or public examples."
