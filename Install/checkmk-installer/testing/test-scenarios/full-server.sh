#!/usr/bin/env bash
# full-server.sh - Test full CheckMK server installation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Full Server Installation Test ==="
echo ""

# Load test configuration
export ENV_FILE="${INSTALLER_ROOT}/testing/test-config.env"
source "$ENV_FILE"

# Override for full server
export INSTALL_CHECKMK_SERVER="yes"
export CHECKMK_DEB_URL="https://download.checkmk.com/checkmk/2.4.0p15/check-mk-raw-2.4.0p15_0.jammy_amd64.deb"

# Run installer in unattended mode
cd "$INSTALLER_ROOT"

echo "[1/6] System base..."
bash modules/01-system-base.sh

echo "[2/6] CheckMK server..."
bash modules/02-checkmk-server.sh

echo "[3/6] CheckMK agent..."
bash modules/03-checkmk-agent.sh

echo "[4/6] Scripts deployment..."
bash modules/04-scripts-deploy.sh

echo "[5/6] Ydea toolkit..."
bash modules/05-ydea-toolkit.sh

echo "[6/6] FRPC setup..."
bash modules/06-frpc-setup.sh || echo "FRPC skipped (no server configured)"

echo ""
echo "=== Full Server Installation Complete ==="
echo ""
echo "CheckMK Web UI: http://$(hostname -I | awk '{print $1}'):5000/monitoring/"
echo "Username: cmkadmin"
echo "Password: test123"
