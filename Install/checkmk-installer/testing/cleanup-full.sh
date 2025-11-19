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
echo "[1/12] Stopping services..."
sudo systemctl stop checkmk-agent-async.socket 2>/dev/null || true
sudo systemctl stop check-mk-agent@.service 2>/dev/null || true
sudo systemctl stop frps.service 2>/dev/null || true
sudo systemctl stop ydea-toolkit.timer 2>/dev/null || true
sudo systemctl stop ydea-toolkit.service 2>/dev/null || true
sudo systemctl stop ydea-ticket-monitor.timer 2>/dev/null || true
sudo systemctl stop ydea-ticket-monitor.service 2>/dev/null || true

# Stop CheckMK site
echo "[2/12] Stopping CheckMK site..."
if [ -d /omd/sites/monitoring ]; then
  sudo omd stop monitoring 2>/dev/null || true
fi

# Remove CheckMK site (force kill if needed)
echo "[3/12] Removing CheckMK site..."
if command -v omd &> /dev/null; then
  timeout 30 sudo omd rm --kill monitoring 2>/dev/null || true
  # Force kill any remaining processes
  sudo pkill -9 -f "monitoring" 2>/dev/null || true
fi

# Unmount any locked directories
echo "[4/12] Unmounting locked directories..."
sudo umount /omd/sites/monitoring/tmp 2>/dev/null || true
sudo umount /opt/omd/sites/monitoring/tmp 2>/dev/null || true

# Uninstall CheckMK Server
echo "[5/12] Uninstalling CheckMK Server..."
if dpkg -l | grep -q check-mk-raw; then
  sudo apt-get purge -y check-mk-raw-* 2>/dev/null || true
fi

# Remove CheckMK Agent
echo "[6/12] Removing CheckMK Agent..."
sudo systemctl disable checkmk-agent-async.socket 2>/dev/null || true
sudo systemctl disable check-mk-agent@.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/checkmk-agent-async.socket
sudo rm -f /etc/systemd/system/check-mk-agent@.service
sudo rm -f /usr/bin/check_mk_agent
sudo rm -rf /etc/check_mk
sudo rm -rf /var/lib/check_mk_agent

# Remove FRPS
echo "[7/12] Removing FRPS..."
sudo systemctl disable frps.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/frps.service
sudo rm -f /usr/local/bin/frps
sudo rm -rf /etc/frp

# Remove monitoring scripts
echo "[8/12] Removing monitoring scripts..."
sudo rm -rf /usr/lib/check_mk_agent/local
sudo rm -rf /usr/lib/check_mk_agent/plugins
sudo rm -f /usr/local/bin/launcher_remote_*

# Remove Ydea Toolkit
echo "[9/12] Removing Ydea Toolkit..."
sudo systemctl disable ydea-toolkit.timer 2>/dev/null || true
sudo systemctl disable ydea-toolkit.service 2>/dev/null || true
sudo systemctl disable ydea-ticket-monitor.timer 2>/dev/null || true
sudo systemctl disable ydea-ticket-monitor.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/ydea-toolkit.timer
sudo rm -f /etc/systemd/system/ydea-toolkit.service
sudo rm -f /etc/systemd/system/ydea-ticket-monitor.timer
sudo rm -f /etc/systemd/system/ydea-ticket-monitor.service
sudo rm -rf /opt/ydea-toolkit

# Remove OMD directories
echo "[10/12] Removing OMD directories..."
sudo rm -rf /omd
sudo rm -rf /opt/omd

# Remove firewall rules (optional - commented out to preserve security)
# echo "[11/12] Removing firewall rules..."
# sudo ufw delete allow 5000/tcp 2>/dev/null || true
# sudo ufw delete allow 6556/tcp 2>/dev/null || true
# sudo ufw delete allow 7000/tcp 2>/dev/null || true
# sudo ufw delete allow 7500/tcp 2>/dev/null || true

echo "[11/12] Keeping firewall rules (manual cleanup if needed)"

# Reload systemd and reset failed units
echo "[12/12] Reloading systemd..."
sudo systemctl daemon-reload
sudo systemctl reset-failed

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
