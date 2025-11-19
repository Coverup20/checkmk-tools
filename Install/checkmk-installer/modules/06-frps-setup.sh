#!/usr/bin/env bash
# 06-frps-setup.sh - FRPS Server installation and configuration
# Installs and configures FRP Server for accepting client connections

set -euo pipefail

MODULE_NAME="FRPS Server Setup"
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
FRP_INSTALL_DIR="/usr/local/bin"
FRP_CONFIG_DIR="/etc/frp"
FRP_LOG_DIR="/var/log"

#############################################
# Check existing installation
#############################################
check_existing_installation() {
  local frps_exists=false
  local service_exists=false
  
  if [[ -f "$FRP_INSTALL_DIR/frps" ]]; then
    frps_exists=true
  fi
  
  if systemctl list-units --full --all | grep -q "frps.service"; then
    service_exists=true
  fi
  
  if [[ "$frps_exists" == "true" ]] || [[ "$service_exists" == "true" ]]; then
    echo ""
    echo "${YELLOW}⚠️  FRPS installation detected${NC}"
    echo ""
    
    if [[ "$frps_exists" == "true" ]]; then
      echo "Binary found: $FRP_INSTALL_DIR/frps"
    fi
    
    if [[ "$service_exists" == "true" ]]; then
      echo "Service found: frps.service"
      if systemctl is-active --quiet frps.service; then
        echo "Status: ${GREEN}Active${NC}"
      else
        echo "Status: ${RED}Inactive${NC}"
      fi
    fi
    
    if [[ -f "$FRP_CONFIG_DIR/frps.toml" ]]; then
      echo "Config found: $FRP_CONFIG_DIR/frps.toml"
    fi
    
    echo ""
    read -p "Reinstall FRPS? This will overwrite existing installation (y/n): " reinstall
    
    if [[ "$reinstall" != "y" ]]; then
      log_info "Installation cancelled by user"
      exit 0
    fi
    
    # Stop existing service
    if systemctl is-active --quiet frps.service; then
      log_info "Stopping existing FRPS service..."
      systemctl stop frps.service
    fi
    
    log_info "Proceeding with reinstallation..."
  fi
}

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
# Download FRPS
#############################################
download_frps() {
  log_info "Downloading FRPS..."
  
  local version="${FRPC_VERSION:-0.52.3}"
  local arch=$(detect_architecture)
  local download_url="https://github.com/fatedier/frp/releases/download/v${version}/frp_${version}_linux_${arch}.tar.gz"
  local dest="/tmp/frp.tar.gz"
  
  log_debug "Download URL: $download_url"
  
  # Download from GitHub
  if ! log_command "wget -O '$dest' '$download_url'"; then
    log_error "Failed to download FRP"
    return 1
  fi
  
  # Extract
  log_command "tar -xzf '$dest' -C /tmp/"
  
  # Find and copy FRPS binary
  local frps_bin=$(find /tmp -name "frps" -type f | head -1)
  if [[ -n "$frps_bin" ]]; then
    cp "$frps_bin" "$FRP_INSTALL_DIR/frps"
    chmod +x "$FRP_INSTALL_DIR/frps"
    log_success "FRPS binary installed"
  else
    log_error "FRPS binary not found in archive"
    return 1
  fi
  
  # Cleanup
  rm -rf /tmp/frp_* "$dest"
}

#############################################
# Configure FRPS
#############################################
configure_frps() {
  log_info "Configuring FRPS server..."
  
  # Get configuration from .env or ask interactively
  local bind_port="${FRPC_SERVER_PORT:-}"
  local token="${FRPC_TOKEN:-}"
  local dashboard_port="7500"
  local dashboard_user="${FRPC_ADMIN_USER:-}"
  local dashboard_pwd="${FRPC_ADMIN_PWD:-}"
  local enable_tls="n"
  local cert_file=""
  local key_file=""
  
  # Ask for missing configuration
  if [[ -z "$bind_port" ]] || [[ -z "$token" ]] || [[ -z "$dashboard_user" ]] || [[ -z "$dashboard_pwd" ]]; then
    echo ""
    echo "${YELLOW}FRPS Server Configuration${NC}"
    echo ""
    
    if [[ -z "$bind_port" ]]; then
      read -p "Bind port [7000]: " bind_port
      bind_port="${bind_port:-7000}"
    fi
    
    if [[ -z "$token" ]]; then
      read -p "Authentication token: " token
    fi
    
    read -p "Dashboard port [7500]: " dashboard_port
    dashboard_port="${dashboard_port:-7500}"
    
    if [[ -z "$dashboard_user" ]]; then
      read -p "Dashboard username [admin]: " dashboard_user
      dashboard_user="${dashboard_user:-admin}"
    fi
    
    if [[ -z "$dashboard_pwd" ]]; then
      read -p "Dashboard password: " dashboard_pwd
    fi
    
    echo ""
    read -p "Enable TLS? (y/n) [n]: " enable_tls
    enable_tls="${enable_tls:-n}"
    
    if [[ "$enable_tls" == "y" ]]; then
      read -p "TLS certificate file path: " cert_file
      read -p "TLS key file path: " key_file
    fi
  fi
  
  # Create config directory
  mkdir -p "$FRP_CONFIG_DIR"
  
  local config_file="$FRP_CONFIG_DIR/frps.toml"
  
  # Create FRPS configuration
  cat > "$config_file" <<EOF
[common]
bindPort = $bind_port

# Authentication
auth.method = "token"
auth.token  = "$token"

EOF

  if [[ "$enable_tls" == "y" ]] && [[ -n "$cert_file" ]] && [[ -n "$key_file" ]]; then
    cat >> "$config_file" <<EOF
# TLS configuration
tls.enable   = true
tls.certFile = "$cert_file"
tls.keyFile  = "$key_file"

EOF
  fi

  cat >> "$config_file" <<EOF
# Dashboard
dashboard_port = $dashboard_port
dashboard_user = "$dashboard_user"
dashboard_pwd  = "$dashboard_pwd"

# Logging
log.to = "$FRP_LOG_DIR/frps.log"
log.level = "info"
EOF
  
  chmod 600 "$config_file"
  
  log_success "FRPS configured: $config_file"
  
  # Store config for later display
  FRPS_BIND_PORT="$bind_port"
  FRPS_DASHBOARD_PORT="$dashboard_port"
  FRPS_TOKEN="$token"
}

#############################################
# Create systemd service
#############################################
create_systemd_service() {
  log_info "Creating systemd service..."
  
  local service_file="/etc/systemd/system/frps.service"
  
  cat > "$service_file" <<EOF
[Unit]
Description=FRP Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=$FRP_INSTALL_DIR/frps -c $FRP_CONFIG_DIR/frps.toml
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$FRP_LOG_DIR

[Install]
WantedBy=multi-user.target
EOF
  
  # Reload and enable service
  log_command "systemctl daemon-reload"
  log_command "systemctl enable frps.service"
  log_command "systemctl start frps.service"
  
  # Wait and check status
  sleep 2
  
  if systemctl is-active --quiet frps.service; then
    log_success "FRPS service started successfully"
  else
    log_error "FRPS service failed to start"
    log_info "Check logs: journalctl -u frps.service -n 50"
    return 1
  fi
}

#############################################
# Configure firewall
#############################################
configure_firewall() {
  log_info "Configuring firewall..."
  
  # Open FRP server port
  log_command "ufw allow ${FRPS_BIND_PORT}/tcp comment 'FRP Server'"
  
  # Open dashboard port
  log_command "ufw allow ${FRPS_DASHBOARD_PORT}/tcp comment 'FRP Dashboard'"
  
  log_success "Firewall configured"
}

#############################################
# Display installation summary
#############################################
display_summary() {
  local server_ip=$(hostname -I | awk '{print $1}')
  
  echo ""
  print_separator "="
  echo ""
  
  display_box "FRPS Server Installation Complete!" \
    "" \
    "Binary: $FRP_INSTALL_DIR/frps" \
    "Config: $FRP_CONFIG_DIR/frps.toml" \
    "Logs: $FRP_LOG_DIR/frps.log" \
    "" \
    "Server listening on port: $FRPS_BIND_PORT" \
    "Dashboard: http://${server_ip}:$FRPS_DASHBOARD_PORT" \
    "Token: $FRPS_TOKEN" \
    "" \
    "Commands:" \
    "  systemctl status frps" \
    "  journalctl -u frps -f" \
    "  tail -f $FRP_LOG_DIR/frps.log" \
    "" \
    "Service: Active and enabled"
  
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting FRPS server setup..."
  
  # Check existing installation
  check_existing_installation
  
  # Download FRPS
  download_frps
  
  # Configure
  configure_frps
  
  # Create systemd service
  create_systemd_service
  
  # Configure firewall
  configure_firewall
  
  log_module_end "$MODULE_NAME" "success"
  
  display_summary
}

# Run main function
main "$@"
