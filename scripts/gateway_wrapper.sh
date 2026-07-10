#!/bin/bash
# gateway_wrapper.sh — Launches the OpenClaw gateway via nvm's current default node.
# Used by the ai.openclaw.gateway LaunchAgent to avoid hardcoding a versioned nvm path.

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

exec openclaw gateway --port "${OPENCLAW_GATEWAY_PORT:-18789}"
