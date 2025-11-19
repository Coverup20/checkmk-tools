#!/usr/bin/env bash
# cleanup-full.sh - Complete cleanup of CheckMK installation
# Removes all components installed by the installer

set -euo pipefail

echo "=========================================="
echo "CheckMK Complete Cleanup Script"
echo "=========================================="
echo ""
echo "This will remove:"
echo "  - CheckMK Server (site: monitoring)"
echo "  - CheckMK Agent"
echo "  - FRPS Server"
echo "  - All monitoring scripts"
echo "  - Ydea Toolkit"
echo "  - Configuration files"
echo ""
read -p "Continue? (y/n): " confirm
if [[ "$confirm" != "y" ]]; then
  echo "Cleanup cancelled."
  exit 0
fi

echo ""
echo "Starting cleanup..."

# Stop all services
echo "[1/10] Stopping services..."
sudo systemctl stop checkmk-agent-async.socket 2>/dev/null || true
sudo systemctl stop check-mk-agent@.service 2>/dev/null || true
sudo systemctl stop frps.service 2>/dev/null || true
sudo systemctl stop ydea-toolkit.timer 2>/dev/null || true
sudo systemctl stop ydea-toolkit.service 2>/dev/null || true

# Stop CheckMK site
echo "[2/10] Stopping CheckMK site..."
if [ -d /omd/sites/monitoring ]; then
  sudo omd stop monitoring 2>/dev/null || true
fi

# Remove CheckMK site
echo "[3/10] Removing CheckMK site..."
if command -v omd &> /dev/null; then
  sudo omd rm --kill monitoring 2>/dev/null || true
fi

# Uninstall CheckMK Server
echo "[4/10] Uninstalling CheckMK Server..."
if dpkg -l | grep -q check-mk-raw; then
  sudo apt-get purge -y check-mk-raw-* 2>/dev/null || true
fi

# Remove CheckMK Agent
echo "[5/10] Removing CheckMK Agent..."
sudo systemctl disable checkmk-agent-async.socket 2>/dev/null || true
sudo systemctl disable check-mk-agent@.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/checkmk-agent-async.socket
sudo rm -f /etc/systemd/system/check-mk-agent@.service
sudo rm -f /usr/bin/check_mk_agent
sudo rm -rf /etc/check_mk
sudo rm -rf /var/lib/check_mk_agent

# Remove FRPS
echo "[6/10] Removing FRPS..."
sudo systemctl disable frps.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/frps.service
sudo rm -f /usr/local/bin/frps
sudo rm -rf /etc/frp

# Remove monitoring scripts
echo "[7/10] Removing monitoring scripts..."
sudo rm -rf /usr/lib/check_mk_agent/local
sudo rm -rf /usr/lib/check_mk_agent/plugins
sudo rm -f /usr/local/bin/launcher_remote_*

# Remove Ydea Toolkit
echo "[8/10] Removing Ydea Toolkit..."
sudo systemctl disable ydea-toolkit.timer 2>/dev/null || true
sudo systemctl disable ydea-toolkit.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/ydea-toolkit.timer
sudo rm -f /etc/systemd/system/ydea-toolkit.service
sudo rm -rf /opt/ydea-toolkit

# Remove firewall rules (optional - commented out to preserve security)
# echo "[9/10] Removing firewall rules..."
# sudo ufw delete allow 5000/tcp 2>/dev/null || true
# sudo ufw delete allow 6556/tcp 2>/dev/null || true
# sudo ufw delete allow 7000/tcp 2>/dev/null || true
# sudo ufw delete allow 7500/tcp 2>/dev/null || true

echo "[9/10] Keeping firewall rules (manual cleanup if needed)"

# Reload systemd
echo "[10/10] Reloading systemd..."
sudo systemctl daemon-reload

echo ""
echo "=========================================="
echo "Cleanup completed!"
echo "=========================================="
echo ""
echo "System is ready for fresh installation."
echo ""
echo "To reinstall, run:"
echo "  cd ~/checkmk-tools/Install/checkmk-installer"
echo "  sudo bash install.sh"
echo ""
