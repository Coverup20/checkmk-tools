#!/usr/bin/env bash
# 02-checkmk-server.sh - CheckMK Server installation module
# Installs and configures CheckMK monitoring server

set -euo pipefail

MODULE_NAME="CheckMK Server Installation"
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
else
  log_error "Configuration file not found. Run config-wizard.sh first."
  exit 1
fi

# Module start
log_module_start "$MODULE_NAME"

#############################################
# Download CheckMK
#############################################
download_checkmk() {
  local url="$1"
  local dest="/tmp/check-mk-raw.deb"
  
  log_info "Downloading CheckMK from: $url"
  
  if [[ -f "$dest" ]]; then
    log_warning "CheckMK package already exists, using cached version"
    return 0
  fi
  
  if ! log_command "wget -O '$dest' '$url'"; then
    log_error "Failed to download CheckMK"
    return 1
  fi
  
  log_success "CheckMK downloaded to $dest"
  echo "$dest"
}

#############################################
# Install CheckMK dependencies
#############################################
install_checkmk_dependencies() {
  log_info "Installing CheckMK dependencies..."
  
  local deps=(
    "apache2"
    "libapache2-mod-fcgid"
    "libpython3.11"
    "librrd8"
    "libsensors5"
    "python3"
    "python3-pip"
    "rrdtool"
    "snmp"
    "php-cli"
    "php-gd"
    "libxml2"
    "libffi8"
    "libpcap0.8"
    "cron"
    "time"
    "traceroute"
    "graphviz"
  )
  
  log_command "apt-get update"
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y ${deps[*]}"
  
  log_success "Dependencies installed"
}

#############################################
# Install CheckMK package
#############################################
install_checkmk_package() {
  local package="$1"
  
  log_info "Installing CheckMK package..."
  
  if ! log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y '$package'"; then
    log_error "Failed to install CheckMK package"
    return 1
  fi
  
  log_success "CheckMK package installed"
}

#############################################
# Create CheckMK site
#############################################
create_checkmk_site() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  
  log_info "Creating CheckMK site: $site_name"
  
  # Check if site already exists
  if omd sites | grep -q "$site_name"; then
    log_warning "Site '$site_name' already exists"
    return 0
  fi
  
  # Create site
  if ! log_command "omd create '$site_name'"; then
    log_error "Failed to create site"
    return 1
  fi
  
  log_success "Site '$site_name' created"
}

#############################################
# Configure CheckMK site
#############################################
configure_checkmk_site() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  local admin_password="${CHECKMK_ADMIN_PASSWORD}"
  
  log_info "Configuring CheckMK site..."
  
  # Set admin password
  log_debug "Setting admin password"
  su - "$site_name" -c "htpasswd -b ~/etc/htpasswd cmkadmin '$admin_password'" 2>/dev/null || true
  
  # Configure site settings
  log_debug "Configuring site settings"
  omd config "$site_name" set APACHE_TCP_ADDR 0.0.0.0
  omd config "$site_name" set APACHE_TCP_PORT "${CHECKMK_HTTP_PORT:-5000}"
  
  # Enable livestatus
  omd config "$site_name" set LIVESTATUS_TCP on
  omd config "$site_name" set LIVESTATUS_TCP_PORT 6557
  
  # Configure core
  omd config "$site_name" set CORE cmc
  
  # Configure web server
  omd config "$site_name" set AUTOSTART on
  
  log_success "Site configured"
}

#############################################
# Configure Apache
#############################################
configure_apache() {
  log_info "Configuring Apache..."
  
  # Enable required modules
  local modules=("proxy" "proxy_http" "rewrite" "headers" "ssl")
  
  for mod in "${modules[@]}"; do
    log_command "a2enmod $mod"
  done
  
  # Restart Apache
  log_command "systemctl restart apache2"
  
  log_success "Apache configured"
}

#############################################
# Start CheckMK site
#############################################
start_checkmk_site() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  
  log_info "Starting CheckMK site..."
  
  if ! log_command "omd start '$site_name'"; then
    log_error "Failed to start site"
    return 1
  fi
  
  log_success "CheckMK site started"
}

#############################################
# Configure firewall for CheckMK
#############################################
configure_checkmk_firewall() {
  local http_port="${CHECKMK_HTTP_PORT:-5000}"
  
  log_info "Configuring firewall for CheckMK..."
  
  # Allow CheckMK HTTP
  log_command "ufw allow $http_port/tcp comment 'CheckMK Web Interface'"
  
  # Allow CheckMK agent
  log_command "ufw allow 6556/tcp comment 'CheckMK Agent'"
  
  # Allow Livestatus
  log_command "ufw allow 6557/tcp comment 'CheckMK Livestatus'"
  
  log_success "Firewall configured"
}

#############################################
# Install CheckMK agent locally
#############################################
install_local_agent() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  
  log_info "Installing CheckMK agent on local system..."
  
  local agent_deb="/omd/sites/$site_name/share/check_mk/agents/check-mk-agent_*.deb"
  
  if ls $agent_deb 1> /dev/null 2>&1; then
    log_command "dpkg -i $agent_deb"
    log_success "Local agent installed"
  else
    log_warning "Agent package not found, skipping local agent installation"
  fi
}

#############################################
# Apply performance tuning
#############################################
apply_performance_tuning() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  local omd_root="/omd/sites/$site_name"
  
  log_info "Applying performance tuning..."
  
  # Apache tuning
  cat >> /etc/apache2/conf-available/checkmk-tuning.conf <<EOF
# CheckMK Performance Tuning
Timeout 300
KeepAlive On
MaxKeepAliveRequests 100
KeepAliveTimeout 5

<IfModule mpm_prefork_module>
    StartServers             10
    MinSpareServers          5
    MaxSpareServers         20
    MaxRequestWorkers      150
    MaxConnectionsPerChild   0
</IfModule>
EOF
  
  a2enconf checkmk-tuning 2>/dev/null || true
  
  # Site-specific tuning
  if [[ -f "$omd_root/etc/apache/apache.conf" ]]; then
    echo "# Performance tuning" >> "$omd_root/etc/apache/apache.conf"
  fi
  
  log_success "Performance tuning applied"
}

#############################################
# Create backup script
#############################################
create_backup_script() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  
  log_info "Creating backup script..."
  
  cat > /usr/local/bin/backup-checkmk.sh <<EOF
#!/bin/bash
# CheckMK Backup Script
set -euo pipefail

BACKUP_DIR="/opt/backups/checkmk"
SITE_NAME="$site_name"
DATE=\$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="\${BACKUP_DIR}/\${SITE_NAME}_\${DATE}.tar.gz"

mkdir -p "\$BACKUP_DIR"

echo "Creating backup: \$BACKUP_FILE"
omd backup "\$SITE_NAME" "\$BACKUP_FILE"

# Keep only last 30 days
find "\$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "Backup completed: \$BACKUP_FILE"
EOF
  
  chmod +x /usr/local/bin/backup-checkmk.sh
  
  # Add to cron
  (crontab -l 2>/dev/null || true; echo "0 2 * * * /usr/local/bin/backup-checkmk.sh >> /var/log/checkmk-backup.log 2>&1") | crontab -
  
  log_success "Backup script created (runs daily at 2 AM)"
}

#############################################
# Display site information
#############################################
display_site_info() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  local http_port="${CHECKMK_HTTP_PORT:-5000}"
  local server_ip=$(hostname -I | awk '{print $1}')
  
  print_separator "="
  echo ""
  display_box "CheckMK Installation Complete!" \
    "" \
    "Site Name: $site_name" \
    "Web Interface: http://${server_ip}:${http_port}/${site_name}/" \
    "Admin User: cmkadmin" \
    "Admin Password: (as configured)" \
    "" \
    "Commands:" \
    "  - omd status $site_name" \
    "  - omd start/stop/restart $site_name" \
    "  - omd config $site_name" \
    "" \
    "Backup: /usr/local/bin/backup-checkmk.sh"
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting CheckMK server installation..."
  
  # Check if URL is provided
  if [[ -z "${CHECKMK_DEB_URL:-}" ]]; then
    log_error "CHECKMK_DEB_URL not set in configuration"
    exit 1
  fi
  
  if [[ -z "${CHECKMK_ADMIN_PASSWORD:-}" ]]; then
    log_error "CHECKMK_ADMIN_PASSWORD not set in configuration"
    exit 1
  fi
  
  # Execute installation steps
  install_checkmk_dependencies
  
  local package=$(download_checkmk "$CHECKMK_DEB_URL")
  install_checkmk_package "$package"
  
  create_checkmk_site
  configure_checkmk_site
  configure_apache
  apply_performance_tuning
  configure_checkmk_firewall
  
  start_checkmk_site
  
  # Optional: install local agent
  if [[ "${INSTALL_LOCAL_AGENT:-yes}" == "yes" ]]; then
    install_local_agent
  fi
  
  create_backup_script
  
  log_module_end "$MODULE_NAME" "success"
  
  display_site_info
}

# Run main function
main "$@"
