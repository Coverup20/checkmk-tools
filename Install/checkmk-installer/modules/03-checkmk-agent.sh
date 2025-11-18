#!/usr/bin/env bash
# 03-checkmk-agent.sh - CheckMK Agent installation module
# Installs CheckMK monitoring agent on client systems

set -euo pipefail

MODULE_NAME="CheckMK Agent Installation"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER_ROOT="$(dirname "$SCRIPT_DIR")"

# Source utilities
source "${INSTALLER_ROOT}/utils/colors.sh"
source "${INSTALLER_ROOT}/utils/logger.sh"
source "${INSTALLER_ROOT}/utils/validate.sh"

# Load configuration
if [[ -f "${INSTALLER_ROOT}/.env" ]]; then
  set -a
  source "${INSTALLER_ROOT}/.env"
  set +a
else
  log_error "Configuration file not found. Run config-wizard.sh first."
  exit 1
fi

# Module start
log_module_start "$MODULE_NAME"

#############################################
# Download CheckMK agent
#############################################
download_checkmk_agent() {
  local server="${CHECKMK_SERVER:-}"
  local site="${CHECKMK_SITE_NAME:-monitoring}"
  local dest="/tmp/check-mk-agent.deb"
  
  if [[ -z "$server" ]]; then
    log_error "CHECKMK_SERVER not configured"
    return 1
  fi
  
  log_info "Downloading CheckMK agent from server..."
  
  local agent_url="http://${server}:${CHECKMK_HTTP_PORT:-5000}/${site}/check_mk/agents/check-mk-agent_2.4.0-1_all.deb"
  
  if ! log_command "wget --no-check-certificate -O '$dest' '$agent_url'"; then
    log_warning "Failed to download from server, trying alternative method..."
    
    # Try to use local copy if available
    local local_agent="${INSTALLER_ROOT}/scripts/Install/Agent-FRPC/check-mk-agent.deb"
    if [[ -f "$local_agent" ]]; then
      log_info "Using local agent package"
      cp "$local_agent" "$dest"
    else
      log_error "No agent package available"
      return 1
    fi
  fi
  
  log_success "Agent package downloaded"
  echo "$dest"
}

#############################################
# Install CheckMK agent
#############################################
install_checkmk_agent() {
  local package="$1"
  
  log_info "Installing CheckMK agent..."
  
  # Install dependencies
  log_command "apt-get update"
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y xinetd"
  
  # Install agent package
  if ! log_command "dpkg -i '$package'"; then
    log_warning "dpkg reported errors, trying to fix..."
    log_command "apt-get install -f -y"
  fi
  
  log_success "CheckMK agent installed"
}

#############################################
# Configure agent via xinetd
#############################################
configure_xinetd() {
  log_info "Configuring xinetd for CheckMK agent..."
  
  local allowed_hosts="${CHECKMK_SERVER:-127.0.0.1}"
  
  cat > /etc/xinetd.d/check_mk <<EOF
service check_mk
{
    type           = UNLISTED
    port           = 6556
    socket_type    = stream
    protocol       = tcp
    wait           = no
    user           = root
    server         = /usr/bin/check_mk_agent
    only_from      = ${allowed_hosts} 127.0.0.1
    disable        = no
}
EOF
  
  # Restart xinetd
  log_command "systemctl restart xinetd"
  log_command "systemctl enable xinetd"
  
  log_success "xinetd configured"
}

#############################################
# Configure systemd socket (alternative to xinetd)
#############################################
configure_systemd_socket() {
  log_info "Configuring systemd socket for CheckMK agent..."
  
  # Create socket unit
  cat > /etc/systemd/system/check-mk-agent.socket <<EOF
[Unit]
Description=Check_MK Agent Socket
Documentation=http://mathias-kettner.com/checkmk.html

[Socket]
ListenStream=6556
Accept=yes

[Install]
WantedBy=sockets.target
EOF
  
  # Create service unit
  cat > /etc/systemd/system/check-mk-agent@.service <<EOF
[Unit]
Description=Check_MK Agent
Documentation=http://mathias-kettner.com/checkmk.html

[Service]
Type=simple
ExecStart=/usr/bin/check_mk_agent
StandardInput=socket
StandardOutput=socket
User=root
EOF
  
  # Enable and start socket
  log_command "systemctl daemon-reload"
  log_command "systemctl enable check-mk-agent.socket"
  log_command "systemctl start check-mk-agent.socket"
  
  log_success "Systemd socket configured"
}

#############################################
# Install agent plugins
#############################################
install_agent_plugins() {
  log_info "Installing agent plugins..."
  
  local plugins_dir="/usr/lib/check_mk_agent/plugins"
  mkdir -p "$plugins_dir"
  
  # Copy plugins from local scripts if available
  local local_plugins="${INSTALLER_ROOT}/scripts/script-check-ubuntu/polling"
  
  if [[ -d "$local_plugins" ]]; then
    log_debug "Copying plugins from: $local_plugins"
    
    for plugin in "$local_plugins"/*; do
      if [[ -f "$plugin" ]]; then
        local plugin_name=$(basename "$plugin")
        cp "$plugin" "$plugins_dir/"
        chmod +x "$plugins_dir/$plugin_name"
        log_debug "Installed plugin: $plugin_name"
      fi
    done
    
    log_success "Agent plugins installed"
  else
    log_warning "No local plugins found"
  fi
}

#############################################
# Configure firewall
#############################################
configure_agent_firewall() {
  log_info "Configuring firewall for agent..."
  
  local server_ip="${CHECKMK_SERVER:-}"
  
  if [[ -n "$server_ip" ]]; then
    log_command "ufw allow from $server_ip to any port 6556 proto tcp comment 'CheckMK Server'"
  else
    log_command "ufw allow 6556/tcp comment 'CheckMK Agent'"
  fi
  
  log_success "Firewall configured"
}

#############################################
# Test agent connection
#############################################
test_agent() {
  log_info "Testing agent..."
  
  if timeout 5 telnet 127.0.0.1 6556 </dev/null 2>/dev/null | grep -q "<<<check_mk>>>"; then
    log_success "Agent is responding correctly"
    return 0
  else
    log_warning "Agent test failed or timed out"
    return 1
  fi
}

#############################################
# Create agent wrapper for custom checks
#############################################
create_agent_wrapper() {
  log_info "Creating agent wrapper script..."
  
  cat > /usr/local/bin/check_mk_agent_wrapper.sh <<'EOF'
#!/bin/bash
# CheckMK Agent Wrapper
# Runs custom checks before standard agent output

# Run standard agent
/usr/bin/check_mk_agent

# Add custom local checks
if [[ -d /usr/lib/check_mk_agent/local ]]; then
  for check in /usr/lib/check_mk_agent/local/*; do
    if [[ -x "$check" ]]; then
      "$check"
    fi
  done
fi
EOF
  
  chmod +x /usr/local/bin/check_mk_agent_wrapper.sh
  
  # Create local checks directory
  mkdir -p /usr/lib/check_mk_agent/local
  
  log_success "Agent wrapper created"
}

#############################################
# Register agent with server (auto-discovery)
#############################################
register_with_server() {
  local server="${CHECKMK_SERVER:-}"
  local site="${CHECKMK_SITE_NAME:-monitoring}"
  
  if [[ -z "$server" ]]; then
    log_warning "CHECKMK_SERVER not configured, skipping auto-registration"
    return 0
  fi
  
  log_info "Attempting auto-registration with server..."
  
  local hostname=$(hostname)
  local api_url="http://${server}:${CHECKMK_HTTP_PORT:-5000}/${site}/check_mk/api/1.0"
  
  # This would require API credentials - just log the command for manual execution
  log_info "To register this host, run on the CheckMK server:"
  echo "  cmk -I $hostname"
  echo "  cmk -O"
}

#############################################
# Display agent info
#############################################
display_agent_info() {
  local server_ip=$(hostname -I | awk '{print $1}')
  
  print_separator "="
  echo ""
  display_box "CheckMK Agent Installation Complete!" \
    "" \
    "Agent listening on: ${server_ip}:6556" \
    "Plugins directory: /usr/lib/check_mk_agent/plugins" \
    "Local checks: /usr/lib/check_mk_agent/local" \
    "" \
    "Test agent: telnet localhost 6556" \
    "View output: check_mk_agent" \
    "" \
    "Next: Add this host to CheckMK server"
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting CheckMK agent installation..."
  
  # Determine configuration method
  local use_systemd="${USE_SYSTEMD_SOCKET:-yes}"
  
  # Download and install agent
  local package=$(download_checkmk_agent)
  install_checkmk_agent "$package"
  
  # Configure connection method
  if [[ "$use_systemd" == "yes" ]]; then
    configure_systemd_socket
  else
    configure_xinetd
  fi
  
  # Additional configuration
  install_agent_plugins
  create_agent_wrapper
  configure_agent_firewall
  
  # Test agent
  sleep 2
  test_agent || log_warning "Agent test inconclusive, check manually"
  
  # Try to register with server
  register_with_server
  
  log_module_end "$MODULE_NAME" "success"
  
  display_agent_info
}

# Run main function
main "$@"
