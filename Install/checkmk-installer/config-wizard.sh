#!/usr/bin/env bash
# config-wizard.sh - Interactive configuration wizard
# Guides user through complete system configuration

set -euo pipefail

INSTALLER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source utilities
source "${INSTALLER_ROOT}/utils/colors.sh"
source "${INSTALLER_ROOT}/utils/menu.sh"
source "${INSTALLER_ROOT}/utils/validate.sh"

ENV_FILE="${INSTALLER_ROOT}/.env"
ENV_TEMPLATE="${INSTALLER_ROOT}/.env.template"

#############################################
# Welcome
#############################################
show_wizard_welcome() {
  clear
  print_header "CheckMK Configuration Wizard"
  echo ""
  echo "This wizard will guide you through the configuration process."
  echo "You can press ENTER to accept default values shown in [brackets]."
  echo ""
  press_any_key
}

#############################################
# Backup existing configuration
#############################################
backup_existing_config() {
  if [[ -f "$ENV_FILE" ]]; then
    local backup="${ENV_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$ENV_FILE" "$backup"
    print_success "Existing configuration backed up to: $backup"
  fi
}

#############################################
# System Base Configuration
#############################################
configure_system_base() {
  print_header "System Base Configuration"
  echo ""
  
  TIMEZONE=$(input_text "Timezone" "Europe/Rome")
  SSH_PORT=$(input_port "SSH Port" "22")
  PERMIT_ROOT_LOGIN=$(select_from_list "Permit root login via SSH?" "no" "yes" "without-password")
  CLIENT_ALIVE_INTERVAL=$(input_text "SSH ClientAliveInterval (seconds)" "300" "^[0-9]+$")
  CLIENT_ALIVE_COUNTMAX=$(input_text "SSH ClientAliveCountMax" "3" "^[0-9]+$")
  LOGIN_GRACE_TIME=$(input_text "SSH LoginGraceTime (seconds)" "60" "^[0-9]+$")
  SSH_PASSWORD_AUTH=$(select_from_list "Allow SSH password authentication?" "yes" "no")
  
  echo ""
  if confirm "Change root password?" "n"; then
    ROOT_PASSWORD=$(input_password "New root password" true)
  else
    ROOT_PASSWORD=""
  fi
  
  echo ""
  NTP_SERVERS=$(input_text "NTP servers (space-separated)" "0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org")
  
  echo ""
  OPEN_HTTP_HTTPS=$(select_from_list "Open HTTP/HTTPS ports in firewall?" "no" "yes")
  FAIL2BAN_EMAIL=$(input_email "Fail2Ban notification email" "root@localhost")
  
  echo ""
  SMTP_RELAY_HOST=$(input_text "SMTP relay host (optional)" "")
  
  if [[ -n "$SMTP_RELAY_HOST" ]]; then
    SMTP_RELAY_USER=$(input_text "SMTP username" "")
    SMTP_RELAY_PASSWORD=$(input_password "SMTP password" false)
  else
    SMTP_RELAY_USER=""
    SMTP_RELAY_PASSWORD=""
  fi
  
  echo ""
  DISABLE_IPV6=$(select_from_list "Disable IPv6?" "no" "yes")
  
  print_success "System base configuration complete"
  press_any_key
}

#############################################
# CheckMK Server Configuration
#############################################
configure_checkmk_server() {
  print_header "CheckMK Server Configuration"
  echo ""
  
  if ! confirm "Will this be a CheckMK server?" "y"; then
    INSTALL_CHECKMK_SERVER="no"
    return 0
  fi
  
  INSTALL_CHECKMK_SERVER="yes"
  
  echo ""
  print_info "CheckMK download URL"
  echo "Example: https://download.checkmk.com/checkmk/2.4.0p15/check-mk-raw-2.4.0p15_0.jammy_amd64.deb"
  CHECKMK_DEB_URL=$(input_url "CheckMK .deb URL" "")
  
  echo ""
  CHECKMK_SITE_NAME=$(input_text "CheckMK site name" "monitoring" "^[a-z][a-z0-9_-]*$")
  CHECKMK_HTTP_PORT=$(input_port "CheckMK HTTP port" "5000")
  CHECKMK_ADMIN_PASSWORD=$(input_password "CheckMK admin password" true)
  
  echo ""
  INSTALL_LOCAL_AGENT=$(select_from_list "Install CheckMK agent locally?" "yes" "no")
  
  print_success "CheckMK server configuration complete"
  press_any_key
}

#############################################
# CheckMK Agent Configuration
#############################################
configure_checkmk_agent() {
  print_header "CheckMK Agent Configuration"
  echo ""
  
  if ! confirm "Will this be a CheckMK agent (client)?" "n"; then
    return 0
  fi
  
  echo ""
  CHECKMK_SERVER=$(input_ip "CheckMK server IP address" "")
  CHECKMK_HTTP_PORT=$(input_port "CheckMK server HTTP port" "5000")
  CHECKMK_SITE_NAME=$(input_text "CheckMK site name on server" "monitoring")
  
  echo ""
  USE_SYSTEMD_SOCKET=$(select_from_list "Use systemd socket (recommended)?" "yes" "no")
  
  print_success "CheckMK agent configuration complete"
  press_any_key
}

#############################################
# Ydea Toolkit Configuration
#############################################
configure_ydea_toolkit() {
  print_header "Ydea Toolkit Configuration"
  echo ""
  
  if ! confirm "Configure Ydea Cloud integration?" "n"; then
    return 0
  fi
  
  echo ""
  print_info "Ydea Cloud API Credentials"
  echo "You can find these in your Ydea Cloud account settings"
  echo ""
  
  YDEA_ID=$(input_text "Ydea ID" "" "^[0-9]+$")
  YDEA_API_KEY=$(input_password "Ydea API Key" false)
  
  echo ""
  YDEA_USER_ID_CREATE_TICKET=$(input_text "User ID for creating tickets" "4675" "^[0-9]+$")
  YDEA_USER_ID_CREATE_NOTE=$(input_text "User ID for creating notes" "4675" "^[0-9]+$")
  
  echo ""
  print_info "Tracking Configuration"
  YDEA_TRACKING_RETENTION_DAYS=$(input_text "Ticket tracking retention (days)" "365" "^[0-9]+$")
  YDEA_MONITOR_INTERVAL=$(input_text "Monitoring interval (minutes)" "30" "^[0-9]+$")
  
  echo ""
  USE_SYSTEMD_TIMER=$(select_from_list "Use systemd timer for monitoring?" "yes" "no")
  YDEA_DEBUG=$(select_from_list "Enable debug logging?" "0" "1")
  
  print_success "Ydea toolkit configuration complete"
  press_any_key
}

#############################################
# FRPC Configuration
#############################################
configure_frpc() {
  print_header "FRPC Client Configuration"
  echo ""
  
  if ! confirm "Configure FRPC client?" "n"; then
    return 0
  fi
  
  echo ""
  print_info "FRPC Server Details"
  FRPC_SERVER_ADDR=$(input_hostname "FRPC server address" "")
  FRPC_SERVER_PORT=$(input_port "FRPC server port" "7000")
  FRPC_TOKEN=$(input_password "FRPC authentication token" false)
  
  echo ""
  print_info "FRPC Port Mapping"
  FRPC_REMOTE_PORT=$(input_port "Remote port for CheckMK agent" "")
  FRPC_SSH_REMOTE_PORT=$(input_port "Remote port for SSH (optional)" "")
  
  echo ""
  print_info "FRPC Admin Interface"
  FRPC_ADMIN_USER=$(input_text "Admin username" "admin")
  FRPC_ADMIN_PWD=$(input_password "Admin password" false)
  
  echo ""
  FRPC_VERSION=$(input_text "FRPC version" "0.52.3")
  FRPC_DOMAIN=$(input_text "Domain for HTTP proxies (optional)" "example.com")
  
  print_success "FRPC configuration complete"
  press_any_key
}

#############################################
# Generate configuration file
#############################################
generate_config_file() {
  print_header "Generating Configuration"
  echo ""
  
  print_info "Writing configuration to: $ENV_FILE"
  
  cat > "$ENV_FILE" <<EOF
# CheckMK Installer Configuration
# Generated: $(date)
# Wizard version: 1.0

#############################################
# System Base Configuration
#############################################
TIMEZONE="${TIMEZONE:-UTC}"
SSH_PORT="${SSH_PORT:-22}"
PERMIT_ROOT_LOGIN="${PERMIT_ROOT_LOGIN:-no}"
CLIENT_ALIVE_INTERVAL="${CLIENT_ALIVE_INTERVAL:-300}"
CLIENT_ALIVE_COUNTMAX="${CLIENT_ALIVE_COUNTMAX:-3}"
LOGIN_GRACE_TIME="${LOGIN_GRACE_TIME:-60}"
SSH_PASSWORD_AUTH="${SSH_PASSWORD_AUTH:-yes}"
ROOT_PASSWORD="${ROOT_PASSWORD:-}"

NTP_SERVERS="${NTP_SERVERS:-0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org}"

OPEN_HTTP_HTTPS="${OPEN_HTTP_HTTPS:-no}"
FAIL2BAN_EMAIL="${FAIL2BAN_EMAIL:-root@localhost}"
SMTP_RELAY_HOST="${SMTP_RELAY_HOST:-}"
SMTP_RELAY_USER="${SMTP_RELAY_USER:-}"
SMTP_RELAY_PASSWORD="${SMTP_RELAY_PASSWORD:-}"

DISABLE_IPV6="${DISABLE_IPV6:-no}"

#############################################
# CheckMK Server Configuration
#############################################
INSTALL_CHECKMK_SERVER="${INSTALL_CHECKMK_SERVER:-no}"
CHECKMK_DEB_URL="${CHECKMK_DEB_URL:-}"
CHECKMK_SITE_NAME="${CHECKMK_SITE_NAME:-monitoring}"
CHECKMK_HTTP_PORT="${CHECKMK_HTTP_PORT:-5000}"
CHECKMK_ADMIN_PASSWORD="${CHECKMK_ADMIN_PASSWORD:-}"
INSTALL_LOCAL_AGENT="${INSTALL_LOCAL_AGENT:-yes}"

#############################################
# CheckMK Agent Configuration
#############################################
CHECKMK_SERVER="${CHECKMK_SERVER:-}"
USE_SYSTEMD_SOCKET="${USE_SYSTEMD_SOCKET:-yes}"

#############################################
# Ydea Toolkit Configuration
#############################################
YDEA_ID="${YDEA_ID:-}"
YDEA_API_KEY="${YDEA_API_KEY:-}"
YDEA_USER_ID_CREATE_TICKET="${YDEA_USER_ID_CREATE_TICKET:-4675}"
YDEA_USER_ID_CREATE_NOTE="${YDEA_USER_ID_CREATE_NOTE:-4675}"
YDEA_TRACKING_RETENTION_DAYS="${YDEA_TRACKING_RETENTION_DAYS:-365}"
YDEA_MONITOR_INTERVAL="${YDEA_MONITOR_INTERVAL:-30}"
USE_SYSTEMD_TIMER="${USE_SYSTEMD_TIMER:-yes}"
YDEA_DEBUG="${YDEA_DEBUG:-0}"

#############################################
# FRPC Configuration
#############################################
FRPC_SERVER_ADDR="${FRPC_SERVER_ADDR:-}"
FRPC_SERVER_PORT="${FRPC_SERVER_PORT:-7000}"
FRPC_TOKEN="${FRPC_TOKEN:-}"
FRPC_REMOTE_PORT="${FRPC_REMOTE_PORT:-}"
FRPC_SSH_REMOTE_PORT="${FRPC_SSH_REMOTE_PORT:-}"
FRPC_ADMIN_USER="${FRPC_ADMIN_USER:-admin}"
FRPC_ADMIN_PWD="${FRPC_ADMIN_PWD:-admin}"
FRPC_VERSION="${FRPC_VERSION:-0.52.3}"
FRPC_DOMAIN="${FRPC_DOMAIN:-example.com}"

#############################################
# Advanced Options
#############################################
VERBOSE="${VERBOSE:-0}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
EOF
  
  chmod 600 "$ENV_FILE"
  
  print_success "Configuration file created!"
  echo ""
  print_info "Configuration saved to: $ENV_FILE"
  echo ""
  press_any_key
}

#############################################
# Configuration summary
#############################################
show_configuration_summary() {
  print_header "Configuration Summary"
  echo ""
  
  echo "${CYAN}System Base:${NC}"
  echo "  Timezone: ${TIMEZONE}"
  echo "  SSH Port: ${SSH_PORT}"
  echo "  Root Login: ${PERMIT_ROOT_LOGIN}"
  echo ""
  
  if [[ "${INSTALL_CHECKMK_SERVER:-no}" == "yes" ]]; then
    echo "${CYAN}CheckMK Server:${NC}"
    echo "  Site Name: ${CHECKMK_SITE_NAME}"
    echo "  HTTP Port: ${CHECKMK_HTTP_PORT}"
    echo ""
  fi
  
  if [[ -n "${CHECKMK_SERVER:-}" ]]; then
    echo "${CYAN}CheckMK Agent:${NC}"
    echo "  Server: ${CHECKMK_SERVER}"
    echo "  Method: ${USE_SYSTEMD_SOCKET}"
    echo ""
  fi
  
  if [[ -n "${YDEA_ID:-}" ]]; then
    echo "${CYAN}Ydea Toolkit:${NC}"
    echo "  Ydea ID: ${YDEA_ID}"
    echo "  Monitoring: Every ${YDEA_MONITOR_INTERVAL} min"
    echo ""
  fi
  
  if [[ -n "${FRPC_SERVER_ADDR:-}" ]]; then
    echo "${CYAN}FRPC Client:${NC}"
    echo "  Server: ${FRPC_SERVER_ADDR}:${FRPC_SERVER_PORT}"
    echo "  Remote Port: ${FRPC_REMOTE_PORT}"
    echo ""
  fi
  
  press_any_key
}

#############################################
# Main wizard flow
#############################################
main() {
  show_wizard_welcome
  
  # Backup existing config
  backup_existing_config
  
  # Run configuration steps
  configure_system_base
  configure_checkmk_server
  configure_checkmk_agent
  configure_ydea_toolkit
  configure_frpc
  
  # Generate config file
  generate_config_file
  
  # Show summary
  show_configuration_summary
  
  print_separator "="
  print_success "Configuration wizard complete!"
  print_separator "="
  echo ""
  print_info "You can now run the installer to deploy your configuration"
  echo ""
}

# Run wizard
main "$@"
