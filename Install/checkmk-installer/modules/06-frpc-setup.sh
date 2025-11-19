#!/usr/bin/env bash
# 06-frpc-setup.sh - FRPC Client installation and configuration
# Installs and configures FRP client for reverse proxy

set -euo pipefail

MODULE_NAME="FRPC Client Setup"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_ROOT="$(dirname "$SCRIPT_DIR")"

# Source utilities
source "${INSTALLER_ROOT}/utils/colors.sh"
source "${INSTALLER_ROOT}/utils/logger.sh"
source "${INSTALLER_ROOT}/utils/validate.sh"
source "${INSTALLER_ROOT}/utils/menu.sh"

# Load configuration
if [[ -f "${INSTALLER_ROOT}/.env" ]]; then
  set -a
  source "${INSTALLER_ROOT}/.env"
  set +a
fi

# Module start
log_module_start "$MODULE_NAME"

# Installation paths
FRPC_INSTALL_DIR="/usr/local/bin"
FRPC_CONFIG_DIR="/etc/frp"
FRPC_LOG_DIR="/var/log"

#############################################
# Detect system architecture
#############################################
detect_architecture() {
  local arch=$(uname -m)
  
  case "$arch" in
    x86_64)
      echo "amd64"
      ;;
    aarch64|arm64)
      echo "arm64"
      ;;
    armv7l)
      echo "arm"
      ;;
    *)
      log_error "Unsupported architecture: $arch"
      return 1
      ;;
  esac
}

#############################################
# Download FRPC
#############################################
download_frpc() {
  log_info "Downloading FRPC..."
  
  local version="${FRPC_VERSION:-0.52.3}"
  local arch=$(detect_architecture)
  local download_url="https://github.com/fatedier/frp/releases/download/v${version}/frp_${version}_linux_${arch}.tar.gz"
  local dest="/tmp/frpc.tar.gz"
  
  log_debug "Download URL: $download_url"
  
  # Try local copy first
  local local_frpc="${INSTALLER_ROOT}/scripts/Install/Agent-FRPC/frpc"
  if [[ -f "$local_frpc" ]]; then
    log_info "Using local FRPC binary"
    cp "$local_frpc" "$FRPC_INSTALL_DIR/frpc"
    chmod +x "$FRPC_INSTALL_DIR/frpc"
    log_success "FRPC binary installed from local copy"
    return 0
  fi
  
  # Download from GitHub
  if ! log_command "wget -O '$dest' '$download_url'"; then
    log_error "Failed to download FRPC"
    return 1
  fi
  
  # Extract
  log_command "tar -xzf '$dest' -C /tmp/"
  
  # Find and copy binary
  local frpc_bin=$(find /tmp -name "frpc" -type f | grep -v ".tar.gz" | head -1)
  if [[ -n "$frpc_bin" ]]; then
    cp "$frpc_bin" "$FRPC_INSTALL_DIR/frpc"
    chmod +x "$FRPC_INSTALL_DIR/frpc"
    log_success "FRPC binary installed"
  else
    log_error "FRPC binary not found in archive"
    return 1
  fi
  
  # Cleanup
  rm -rf /tmp/frp_* "$dest"
}

#############################################
# Configure FRPC
#############################################
configure_frpc() {
  log_info "Configuring FRPC..."
  
  # Check required configuration
  if [[ -z "${FRPC_SERVER_ADDR:-}" ]]; then
    log_error "FRPC_SERVER_ADDR not configured"
    return 1
  fi
  
  # Create config directory
  mkdir -p "$FRPC_CONFIG_DIR"
  
  local config_file="$FRPC_CONFIG_DIR/frpc.ini"
  local hostname=$(hostname)
  
  # Use template if available
  local template="${INSTALLER_ROOT}/templates/frpc.ini.template"
  
  if [[ -f "$template" ]]; then
    log_debug "Using configuration template"
    cp "$template" "$config_file"
    
    # Replace placeholders
    sed -i "s|{{FRPC_SERVER_ADDR}}|${FRPC_SERVER_ADDR}|g" "$config_file"
    sed -i "s|{{FRPC_SERVER_PORT}}|${FRPC_SERVER_PORT:-7000}|g" "$config_file"
    sed -i "s|{{FRPC_TOKEN}}|${FRPC_TOKEN:-}|g" "$config_file"
    sed -i "s|{{HOSTNAME}}|${hostname}|g" "$config_file"
    sed -i "s|{{FRPC_REMOTE_PORT}}|${FRPC_REMOTE_PORT:-}|g" "$config_file"
    sed -i "s|{{FRPC_SSH_REMOTE_PORT}}|${FRPC_SSH_REMOTE_PORT:-}|g" "$config_file"
    sed -i "s|{{FRPC_ADMIN_USER}}|${FRPC_ADMIN_USER:-admin}|g" "$config_file"
    sed -i "s|{{FRPC_ADMIN_PWD}}|${FRPC_ADMIN_PWD:-admin}|g" "$config_file"
    sed -i "s|{{FRPC_DOMAIN}}|${FRPC_DOMAIN:-example.com}|g" "$config_file"
  else
    # Create basic configuration
    log_warning "Template not found, creating basic configuration"
    
    cat > "$config_file" <<EOF
[common]
server_addr = ${FRPC_SERVER_ADDR}
server_port = ${FRPC_SERVER_PORT:-7000}
token = ${FRPC_TOKEN:-}
log_file = ${FRPC_LOG_DIR}/frpc.log
log_level = info
log_max_days = 7

# Admin interface
admin_addr = 127.0.0.1
admin_port = 7400
admin_user = ${FRPC_ADMIN_USER:-admin}
admin_pwd = ${FRPC_ADMIN_PWD:-admin}

# CheckMK Agent Proxy
[checkmk-${hostname}]
type = tcp
local_ip = 127.0.0.1
local_port = 6556
remote_port = ${FRPC_REMOTE_PORT:-}
use_encryption = true
use_compression = true
EOF
  fi
  
  chmod 600 "$config_file"
  
  log_success "FRPC configured: $config_file"
}

#############################################
# Create systemd service
#############################################
create_systemd_service() {
  log_info "Creating systemd service..."
  
  local service_file="/etc/systemd/system/frpc.service"
  local template="${INSTALLER_ROOT}/templates/systemd/frpc.service"
  
  if [[ -f "$template" ]]; then
    cp "$template" "$service_file"
  else
    cat > "$service_file" <<EOF
[Unit]
Description=FRPC Client Service
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=$FRPC_INSTALL_DIR/frpc -c $FRPC_CONFIG_DIR/frpc.ini
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${FRPC_LOG_DIR}

[Install]
WantedBy=multi-user.target
EOF
  fi
  
  # Reload and enable service
  log_command "systemctl daemon-reload"
  log_command "systemctl enable frpc.service"
  
  log_success "Systemd service created"
}

#############################################
# Test FRPC connection
#############################################
test_frpc_connection() {
  log_info "Testing FRPC connection..."
  
  # Start service temporarily
  systemctl start frpc.service
  
  # Wait a moment
  sleep 3
  
  # Check if running
  if systemctl is-active --quiet frpc.service; then
    log_success "FRPC service is running"
    
    # Check logs for connection
    if journalctl -u frpc.service -n 20 | grep -q "login to server success"; then
      log_success "FRPC connected to server successfully"
      return 0
    else
      log_warning "FRPC started but connection status unknown"
      log_info "Check logs: journalctl -u frpc.service -f"
    fi
  else
    log_error "FRPC service failed to start"
    log_info "Check logs: journalctl -u frpc.service -n 50"
    return 1
  fi
}

#############################################
# Configure firewall
#############################################
configure_frpc_firewall() {
  log_info "Configuring firewall for FRPC..."
  
  # Allow outgoing connections to FRPC server
  local server_ip="${FRPC_SERVER_ADDR}"
  local server_port="${FRPC_SERVER_PORT:-7000}"
  
  if [[ -n "$server_ip" ]]; then
    log_command "ufw allow out to $server_ip port $server_port proto tcp comment 'FRPC to server'"
  fi
  
  log_success "Firewall configured"
}

#############################################
# Create management scripts
#############################################
create_management_scripts() {
  log_info "Creating management scripts..."
  
  # FRPC status script
  cat > /usr/local/bin/frpc-status <<'EOF'
#!/bin/bash
# FRPC Status Check

echo "=== FRPC Service Status ==="
systemctl status frpc.service --no-pager

echo ""
echo "=== FRPC Connections ==="
if command -v ss &>/dev/null; then
  ss -tnp | grep frpc || echo "No active connections"
else
  netstat -tnp | grep frpc || echo "No active connections"
fi

echo ""
echo "=== Recent Logs ==="
journalctl -u frpc.service -n 10 --no-pager
EOF
  
  chmod +x /usr/local/bin/frpc-status
  
  # FRPC restart script
  cat > /usr/local/bin/frpc-restart <<'EOF'
#!/bin/bash
# FRPC Service Restart

echo "Restarting FRPC service..."
systemctl restart frpc.service

sleep 2

if systemctl is-active --quiet frpc.service; then
  echo "✅ FRPC service restarted successfully"
else
  echo "❌ FRPC service failed to restart"
  echo "Check logs: journalctl -u frpc.service -n 20"
  exit 1
fi
EOF
  
  chmod +x /usr/local/bin/frpc-restart
  
  log_success "Management scripts created"
}

#############################################
# Create monitoring check
#############################################
create_monitoring_check() {
  log_info "Creating monitoring check..."
  
  local check_script="/usr/lib/check_mk_agent/local/frpc_status"
  
  mkdir -p "$(dirname "$check_script")"
  
  cat > "$check_script" <<'EOF'
#!/bin/bash
# CheckMK Local Check: FRPC Status

if systemctl is-active --quiet frpc.service; then
  if journalctl -u frpc.service -n 5 | grep -q "login to server success\|start proxy success"; then
    echo "0 FRPC_Status - FRPC service is running and connected"
  else
    echo "1 FRPC_Status - FRPC service is running but connection unclear"
  fi
else
  echo "2 FRPC_Status - FRPC service is not running"
fi
EOF
  
  chmod +x "$check_script"
  
  log_success "Monitoring check created"
}

#############################################
# Display installation summary
#############################################
display_installation_summary() {
  local hostname=$(hostname)
  
  print_separator "="
  echo ""
  display_box "FRPC Installation Complete!" \
    "" \
    "Binary: $FRPC_INSTALL_DIR/frpc" \
    "Config: $FRPC_CONFIG_DIR/frpc.ini" \
    "Logs: ${FRPC_LOG_DIR}/frpc.log" \
    "" \
    "Server: ${FRPC_SERVER_ADDR}:${FRPC_SERVER_PORT:-7000}" \
    "Hostname: $hostname" \
    "" \
    "Commands:" \
    "  systemctl status frpc" \
    "  frpc-status" \
    "  frpc-restart" \
    "  journalctl -u frpc -f" \
    "" \
    "Service: Active and enabled"
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting FRPC client setup..."
  
  # Check configuration
  if [[ -z "${FRPC_SERVER_ADDR:-}" ]]; then
    log_error "FRPC_SERVER_ADDR not configured"
    log_info "Please configure FRPC settings and run this module again"
    exit 1
  fi
  
  # Install FRPC
  download_frpc
  configure_frpc
  create_systemd_service
  configure_frpc_firewall
  
  # Create additional components
  create_management_scripts
  create_monitoring_check
  
  # Test connection
  test_frpc_connection || log_warning "Connection test inconclusive"
  
  log_module_end "$MODULE_NAME" "success"
  
  display_installation_summary
}

# Run main function
main "$@"
