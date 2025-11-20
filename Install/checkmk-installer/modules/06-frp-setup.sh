#!/usr/bin/env bash
# 06-frp-setup.sh - FRP Server/Client installation and configuration
# Installs and configures either FRPS (server) or FRPC (client)

set -euo pipefail

MODULE_NAME="FRP Setup"
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
# Ask installation type
#############################################
ask_installation_type() {
  echo ""
  echo "${YELLOW}FRP Installation Type${NC}"
  echo ""
  echo "  1) FRPS - FRP Server (accepts connections from clients)"
  echo "  2) FRPC - FRP Client (connects to FRP server)"
  echo ""
  
  local choice
  while true; do
    read -p "Select installation type (1-2): " choice
    case "$choice" in
      1)
        echo "server"
        return 0
        ;;
      2)
        echo "client"
        return 0
        ;;
      *)
        echo "Invalid choice. Please select 1 or 2."
        ;;
    esac
  done
}

#############################################
# Download FRP
#############################################
download_frp() {
  local type="$1"  # "server" or "client"
  
  log_info "Downloading FRP..."
  
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
  
  # Find and copy binary
  if [[ "$type" == "server" ]]; then
    local frp_bin=$(find /tmp -name "frps" -type f | head -1)
    if [[ -n "$frp_bin" ]]; then
      cp "$frp_bin" "$FRP_INSTALL_DIR/frps"
      chmod +x "$FRP_INSTALL_DIR/frps"
      log_success "FRPS binary installed"
    else
      log_error "FRPS binary not found in archive"
      return 1
    fi
  else
    local frp_bin=$(find /tmp -name "frpc" -type f | head -1)
    if [[ -n "$frp_bin" ]]; then
      cp "$frp_bin" "$FRP_INSTALL_DIR/frpc"
      chmod +x "$FRP_INSTALL_DIR/frpc"
      log_success "FRPC binary installed"
    else
      log_error "FRPC binary not found in archive"
      return 1
    fi
  fi
  
  # Cleanup
  rm -rf /tmp/frp_* "$dest"
}

#############################################
# Configure FRPS (Server)
#############################################
configure_frps() {
  log_info "Configuring FRPS server..."
  
  # Ask for configuration
  echo ""
  echo "${YELLOW}FRPS Server Configuration${NC}"
  echo ""
  
  local bind_port
  local token
  local dashboard_port
  local dashboard_user
  local dashboard_pwd
  local enable_tls
  local cert_file
  local key_file
  
  read -p "Bind port [7000]: " bind_port
  bind_port="${bind_port:-7000}"
  
  read -p "Authentication token: " token
  
  read -p "Dashboard port [7500]: " dashboard_port
  dashboard_port="${dashboard_port:-7500}"
  
  read -p "Dashboard username [admin]: " dashboard_user
  dashboard_user="${dashboard_user:-admin}"
  
  read -p "Dashboard password: " dashboard_pwd
  
  echo ""
  read -p "Enable TLS? (y/n) [n]: " enable_tls
  enable_tls="${enable_tls:-n}"
  
  if [[ "$enable_tls" == "y" ]]; then
    read -p "TLS certificate file path: " cert_file
    read -p "TLS key file path: " key_file
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
# Configure FRPC (Client)
#############################################
configure_frpc() {
  log_info "Configuring FRPC client..."
  
  # Ask for configuration
  echo ""
  echo "${YELLOW}FRPC Client Configuration${NC}"
  echo ""
  
  local server_addr
  local server_port
  local token
  local checkmk_remote_port
  local ssh_remote_port
  local hostname=$(hostname)
  
  read -p "FRP server address: " server_addr
  
  read -p "FRP server port [7000]: " server_port
  server_port="${server_port:-7000}"
  
  read -p "Authentication token: " token
  
  read -p "Remote port for CheckMK agent (6556): " checkmk_remote_port
  
  echo ""
  read -p "Enable SSH tunnel? (y/n) [n]: " enable_ssh
  enable_ssh="${enable_ssh:-n}"
  
  if [[ "$enable_ssh" == "y" ]]; then
    read -p "Remote port for SSH (22): " ssh_remote_port
  fi
  
  # Create config directory
  mkdir -p "$FRP_CONFIG_DIR"
  
  local config_file="$FRP_CONFIG_DIR/frpc.toml"
  
  # Create FRPC configuration
  cat > "$config_file" <<EOF
# FRPC Client Configuration for $hostname

serverAddr = "$server_addr"
serverPort = $server_port

# Authentication
auth.method = "token"
auth.token = "$token"

# Logging
log.to = "$FRP_LOG_DIR/frpc.log"
log.level = "info"

# CheckMK Agent Proxy
[[proxies]]
name = "checkmk-$hostname"
type = "tcp"
localIP = "127.0.0.1"
localPort = 6556
remotePort = $checkmk_remote_port
transport.useEncryption = true
transport.useCompression = true
EOF

  if [[ "$enable_ssh" == "y" ]] && [[ -n "$ssh_remote_port" ]]; then
    cat >> "$config_file" <<EOF

# SSH Tunnel
[[proxies]]
name = "ssh-$hostname"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = $ssh_remote_port
transport.useEncryption = true
transport.useCompression = true
EOF
  fi
  
  chmod 600 "$config_file"
  
  log_success "FRPC configured: $config_file"
  
  # Store config for later display
  FRPC_SERVER_ADDR="$server_addr"
  FRPC_SERVER_PORT="$server_port"
  FRPC_REMOTE_PORT="$checkmk_remote_port"
  FRPC_SSH_REMOTE_PORT="$ssh_remote_port"
}

#############################################
# Create systemd service
#############################################
create_systemd_service() {
  local type="$1"  # "server" or "client"
  
  log_info "Creating systemd service..."
  
  if [[ "$type" == "server" ]]; then
    local service_file="/etc/systemd/system/frps.service"
    local binary="frps"
    local config="frps.toml"
    local description="FRP Server"
  else
    local service_file="/etc/systemd/system/frpc.service"
    local binary="frpc"
    local config="frpc.toml"
    local description="FRP Client"
  fi
  
  cat > "$service_file" <<EOF
[Unit]
Description=$description
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=$FRP_INSTALL_DIR/$binary -c $FRP_CONFIG_DIR/$config
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
  log_command "systemctl enable ${binary}.service"
  log_command "systemctl start ${binary}.service"
  
  # Wait and check status
  sleep 2
  
  if systemctl is-active --quiet ${binary}.service; then
    log_success "$description service started successfully"
  else
    log_error "$description service failed to start"
    log_info "Check logs: journalctl -u ${binary}.service -n 50"
    return 1
  fi
}

#############################################
# Configure firewall
#############################################
configure_firewall() {
  local type="$1"
  
  log_info "Configuring firewall..."
  
  if [[ "$type" == "server" ]]; then
    # Open FRP server port
    log_command "ufw allow ${FRPS_BIND_PORT}/tcp comment 'FRP Server'"
    
    # Open dashboard port (only from localhost ideally, but for simplicity allow all)
    log_command "ufw allow ${FRPS_DASHBOARD_PORT}/tcp comment 'FRP Dashboard'"
  else
    # Client: allow outgoing to FRP server
    if [[ -n "${FRPC_SERVER_ADDR}" ]]; then
      log_command "ufw allow out to ${FRPC_SERVER_ADDR} port ${FRPC_SERVER_PORT} proto tcp comment 'FRPC to server'"
    fi
  fi
  
  log_success "Firewall configured"
}

#############################################
# Display installation summary
#############################################
display_summary() {
  local type="$1"
  
  echo ""
  print_separator "="
  echo ""
  
  if [[ "$type" == "server" ]]; then
    display_box "FRPS Server Installation Complete!" \
      "" \
      "Binary: $FRP_INSTALL_DIR/frps" \
      "Config: $FRP_CONFIG_DIR/frps.toml" \
      "Logs: $FRP_LOG_DIR/frps.log" \
      "" \
      "Server listening on port: $FRPS_BIND_PORT" \
      "Dashboard: http://$(hostname -I | awk '{print $1}'):$FRPS_DASHBOARD_PORT" \
      "Token: $FRPS_TOKEN" \
      "" \
      "Commands:" \
      "  systemctl status frps" \
      "  journalctl -u frps -f" \
      "" \
      "Service: Active and enabled"
  else
    display_box "FRPC Client Installation Complete!" \
      "" \
      "Binary: $FRP_INSTALL_DIR/frpc" \
      "Config: $FRP_CONFIG_DIR/frpc.toml" \
      "Logs: $FRP_LOG_DIR/frpc.log" \
      "" \
      "Server: $FRPC_SERVER_ADDR:$FRPC_SERVER_PORT" \
      "CheckMK remote port: $FRPC_REMOTE_PORT" \
      "" \
      "Commands:" \
      "  systemctl status frpc" \
      "  journalctl -u frpc -f" \
      "" \
      "Service: Active and enabled"
  fi
  
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting FRP setup..."
  
  # Ask what to install
  local install_type
  install_type=$(ask_installation_type)
  
  log_info "Installing FRP $install_type..."
  
  # Download FRP
  download_frp "$install_type"
  
  # Configure
  if [[ "$install_type" == "server" ]]; then
    configure_frps
  else
    configure_frpc
  fi
  
  # Create systemd service
  create_systemd_service "$install_type"
  
  # Configure firewall
  configure_firewall "$install_type"
  
  log_module_end "$MODULE_NAME" "success"
  
  display_summary "$install_type"
}

# Run main function
main "$@"
