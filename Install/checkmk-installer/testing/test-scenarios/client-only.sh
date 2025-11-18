#!/usr/bin/env bash
# client-only.sh - Test CheckMK agent-only installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "=== Client-Only Installation Test ==="
echo ""

# Load test configuration
export ENV_FILE="${INSTALLER_ROOT}/testing/test-config.env"
source "$ENV_FILE"

# Override for client-only
export INSTALL_CHECKMK_SERVER="no"
export CHECKMK_SERVER="10.0.2.2"  # Host machine

# Run installer in unattended mode
cd "$INSTALLER_ROOT"

echo "[1/3] System base..."
bash modules/01-system-base.sh

echo "[2/3] CheckMK agent..."
bash modules/03-checkmk-agent.sh

echo "[3/3] Scripts deployment..."
bash modules/04-scripts-deploy.sh

echo ""
echo "=== Client-Only Installation Complete ==="
echo ""
echo "CheckMK Agent listening on port 6556"
echo "Test with: telnet localhost 6556"
