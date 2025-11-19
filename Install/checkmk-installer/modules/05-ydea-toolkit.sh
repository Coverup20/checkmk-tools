#!/usr/bin/env bash
# 05-ydea-toolkit.sh - Ydea Toolkit installation and configuration
# Installs Ydea Cloud API toolkit for ticket management

set -euo pipefail

MODULE_NAME="Ydea Toolkit Installation"
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
YDEA_INSTALL_DIR="/opt/ydea-toolkit"
YDEA_LOG_DIR="/var/log"
YDEA_BIN="/usr/local/bin/ydea-toolkit"

#############################################
# Install dependencies
#############################################
install_dependencies() {
  log_info "Installing dependencies..."
  
  local deps=("curl" "jq" "cron")
  
  log_command "apt-get update"
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y ${deps[*]}"
  
  log_success "Dependencies installed"
}

#############################################
# Deploy Ydea Toolkit
#############################################
deploy_ydea_toolkit() {
  log_info "Deploying Ydea Toolkit..."
  
  local src="${INSTALLER_ROOT}/scripts/Ydea-Toolkit"
  
  if [[ ! -d "$src" ]]; then
    log_error "Ydea Toolkit source not found: $src"
    return 1
  fi
  
  # Create installation directory
  mkdir -p "$YDEA_INSTALL_DIR"
  
  # Copy toolkit files
  log_command "cp -r '$src'/* '$YDEA_INSTALL_DIR/'"
  
  # Set permissions
  chmod +x "$YDEA_INSTALL_DIR"/*.sh 2>/dev/null || true
  
  # Create symlink
  ln -sf "$YDEA_INSTALL_DIR/ydea-toolkit.sh" "$YDEA_BIN"
  
  log_success "Ydea Toolkit deployed to: $YDEA_INSTALL_DIR"
}

#############################################
# Configure Ydea Toolkit
#############################################
configure_ydea_toolkit() {
  log_info "Configuring Ydea Toolkit..."
  
  local env_file="$YDEA_INSTALL_DIR/.env"
  
  # Check if configuration exists
  if [[ -z "${YDEA_ID:-}" ]] || [[ -z "${YDEA_API_KEY:-}" ]]; then
    log_warning "Ydea credentials not configured"
    log_info "Run: $YDEA_BIN config"
    return 0
  fi
  
  # Create .env file
  cat > "$env_file" <<EOF
# Ydea Cloud API Configuration
# Generated: $(date)

# API Credentials
export YDEA_ID="${YDEA_ID}"
export YDEA_API_KEY="${YDEA_API_KEY}"
export YDEA_USER_ID_CREATE_TICKET="${YDEA_USER_ID_CREATE_TICKET:-4675}"
export YDEA_USER_ID_CREATE_NOTE="${YDEA_USER_ID_CREATE_NOTE:-4675}"

# Logging Configuration
export YDEA_LOG_FILE="${YDEA_LOG_DIR}/ydea-toolkit.log"
export YDEA_LOG_MAX_SIZE="10485760"  # 10MB
export YDEA_LOG_MAX_FILES="5"
export YDEA_DEBUG="${YDEA_DEBUG:-0}"

# Tracking Configuration
export YDEA_TRACKING_FILE="${YDEA_LOG_DIR}/ydea-tickets-tracking.json"
export YDEA_TRACKING_RETENTION_DAYS="${YDEA_TRACKING_RETENTION_DAYS:-365}"

# Monitoring Configuration
export YDEA_MONITOR_INTERVAL="${YDEA_MONITOR_INTERVAL:-30}"  # minutes
EOF
  
  chmod 600 "$env_file"
  
  # Initialize tracking file
  local tracking_file="${YDEA_LOG_DIR}/ydea-tickets-tracking.json"
  if [[ ! -f "$tracking_file" ]]; then
    echo '{"tickets":[],"last_update":""}' > "$tracking_file"
    chmod 666 "$tracking_file"
  fi
  
  log_success "Ydea Toolkit configured"
}

#############################################
# Install monitoring script
#############################################
install_monitoring_script() {
  log_info "Installing ticket monitoring script..."
  
  local monitor_script="$YDEA_INSTALL_DIR/ydea-ticket-monitor.sh"
  
  if [[ ! -f "$monitor_script" ]]; then
    log_warning "Monitoring script not found, creating minimal version..."
    
    cat > "$monitor_script" <<'EOF'
#!/bin/bash
# Ydea Ticket Monitor
# Updates tracked tickets status

set -euo pipefail

TOOLKIT="/usr/local/bin/ydea-toolkit"

if [[ ! -f "$TOOLKIT" ]]; then
  echo "ERROR: Ydea toolkit not found"
  exit 1
fi

# Update tracking
"$TOOLKIT" update-tracking

# Cleanup old resolved tickets
"$TOOLKIT" cleanup-tracking

exit 0
EOF
    
    chmod +x "$monitor_script"
  fi
  
  log_success "Monitoring script installed"
}

#############################################
# Configure systemd timer
#############################################
configure_systemd_timer() {
  log_info "Configuring systemd timer for monitoring..."
  
  # Copy templates
  local template_service="${INSTALLER_ROOT}/templates/systemd/ydea-ticket-monitor.service"
  local template_timer="${INSTALLER_ROOT}/templates/systemd/ydea-ticket-monitor.timer"
  
  if [[ -f "$template_service" ]]; then
    cp "$template_service" /etc/systemd/system/
  else
    # Create service unit
    cat > /etc/systemd/system/ydea-ticket-monitor.service <<EOF
[Unit]
Description=Ydea Ticket Monitor
After=network.target

[Service]
Type=oneshot
ExecStart=$YDEA_INSTALL_DIR/ydea-ticket-monitor.sh
StandardOutput=journal
StandardError=journal
EOF
  fi
  
  if [[ -f "$template_timer" ]]; then
    cp "$template_timer" /etc/systemd/system/
  else
    # Create timer unit
    cat > /etc/systemd/system/ydea-ticket-monitor.timer <<EOF
[Unit]
Description=Ydea Ticket Monitor Timer
Requires=ydea-ticket-monitor.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=${YDEA_MONITOR_INTERVAL:-30}min
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF
  fi
  
  # Enable and start timer
  log_command "systemctl daemon-reload"
  log_command "systemctl enable ydea-ticket-monitor.timer"
  log_command "systemctl start ydea-ticket-monitor.timer"
  
  log_success "Systemd timer configured (runs every ${YDEA_MONITOR_INTERVAL:-30} minutes)"
}

#############################################
# Configure cron (alternative to systemd)
#############################################
configure_cron() {
  log_info "Configuring cron for monitoring..."
  
  local cron_template="${INSTALLER_ROOT}/templates/cron/checkmk-monitoring"
  
  if [[ -f "$cron_template" ]]; then
    cp "$cron_template" /etc/cron.d/ydea-monitoring
  else
    cat > /etc/cron.d/ydea-monitoring <<EOF
# Ydea Ticket Monitoring Cron Jobs

# Update tracked tickets every 30 minutes
*/30 * * * * root $YDEA_INSTALL_DIR/ydea-ticket-monitor.sh >> ${YDEA_LOG_DIR}/ydea-monitor.log 2>&1

# Cleanup resolved tickets daily at 3 AM
0 3 * * * root $YDEA_BIN cleanup-tracking >> ${YDEA_LOG_DIR}/ydea-toolkit.log 2>&1
EOF
  fi
  
  chmod 644 /etc/cron.d/ydea-monitoring
  
  log_success "Cron jobs configured"
}

#############################################
# Test Ydea connection
#############################################
test_ydea_connection() {
  log_info "Testing Ydea API connection..."
  
  if [[ -z "${YDEA_ID:-}" ]] || [[ -z "${YDEA_API_KEY:-}" ]]; then
    log_warning "Ydea credentials not configured, skipping connection test"
    return 0
  fi
  
  # Test login
  if "$YDEA_BIN" login > /dev/null 2>&1; then
    log_success "Ydea API connection successful"
    return 0
  else
    log_error "Ydea API connection failed"
    log_info "Please verify credentials and run: $YDEA_BIN config"
    return 1
  fi
}

#############################################
# Create helper scripts
#############################################
create_helper_scripts() {
  log_info "Creating helper scripts..."
  
  # Create ticket creation helper
  cat > /usr/local/bin/create-checkmk-ticket <<'EOF'
#!/bin/bash
# Quick ticket creation for CheckMK alerts

YDEA_TOOLKIT="/usr/local/bin/ydea-toolkit"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <host> <service> [description]"
  exit 1
fi

HOST="$1"
SERVICE="$2"
DESCRIPTION="${3:-Alert from CheckMK}"

"$YDEA_TOOLKIT" create \
  --codice "$HOST" \
  --host "$HOST" \
  --service "$SERVICE" \
  --titolo "[$SERVICE] $HOST" \
  --descrizione "$DESCRIPTION" \
  --priorita "Urgente" \
  --tipo "Nethserver"
EOF
  
  chmod +x /usr/local/bin/create-checkmk-ticket
  
  # Create ticket status checker
  cat > /usr/local/bin/check-ticket-status <<'EOF'
#!/bin/bash
# Check status of a ticket

YDEA_TOOLKIT="/usr/local/bin/ydea-toolkit"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <ticket_id>"
  exit 1
fi

"$YDEA_TOOLKIT" get "$1"
EOF
  
  chmod +x /usr/local/bin/check-ticket-status
  
  log_success "Helper scripts created"
}

#############################################
# Display installation summary
#############################################
display_installation_summary() {
  print_separator "="
  echo ""
  display_box "Ydea Toolkit Installation Complete!" \
    "" \
    "Installation: $YDEA_INSTALL_DIR" \
    "Command: $YDEA_BIN" \
    "Logs: ${YDEA_LOG_DIR}/ydea-toolkit.log" \
    "Tracking: ${YDEA_LOG_DIR}/ydea-tickets-tracking.json" \
    "" \
    "Commands:" \
    "  ydea-toolkit login      - Test connection" \
    "  ydea-toolkit list       - List tickets" \
    "  ydea-toolkit create     - Create ticket" \
    "  ydea-toolkit stats      - Show statistics" \
    "  ydea-toolkit config     - Configure toolkit" \
    "" \
    "Helpers:" \
    "  create-checkmk-ticket <host> <service>" \
    "  check-ticket-status <ticket_id>" \
    "" \
    "Monitoring: Every ${YDEA_MONITOR_INTERVAL:-30} minutes"
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting Ydea Toolkit installation..."
  
  # Install components
  install_dependencies
  deploy_ydea_toolkit
  configure_ydea_toolkit
  install_monitoring_script
  
  # Configure monitoring
  local use_systemd="${USE_SYSTEMD_TIMER:-yes}"
  if [[ "$use_systemd" == "yes" ]]; then
    configure_systemd_timer
  else
    configure_cron
  fi
  
  # Additional setup
  create_helper_scripts
  
  # Test connection
  test_ydea_connection || log_warning "Connection test failed, configure manually"
  
  log_module_end "$MODULE_NAME" "success"
  
  display_installation_summary
}

# Run main function
main "$@"
