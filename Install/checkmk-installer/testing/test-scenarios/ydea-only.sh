#!/usr/bin/env bash
# ydea-only.sh - Test Ydea toolkit installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "=== Ydea Toolkit Installation Test ==="
echo ""

# Load test configuration
export ENV_FILE="${INSTALLER_ROOT}/testing/test-config.env"
source "$ENV_FILE"

# Run installer in unattended mode
cd "$INSTALLER_ROOT"

echo "[1/2] System base..."
bash modules/01-system-base.sh

echo "[2/2] Ydea toolkit..."
bash modules/05-ydea-toolkit.sh

echo ""
echo "=== Ydea Toolkit Installation Complete ==="
echo ""
echo "Ydea toolkit: /opt/ydea-toolkit/"
echo "Command: ydea-toolkit"
echo ""
echo "Test commands:"
echo "  ydea-toolkit status"
echo "  ydea-toolkit tickets list"
echo "  ydea-toolkit update-tracking"
