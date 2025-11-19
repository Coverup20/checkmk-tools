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
# Get latest CheckMK version URL
#############################################
get_latest_checkmk_url() {
  log_info "Finding latest CheckMK RAW version..." >&2
  
  local os_codename
  os_codename=$(lsb_release -sc)
  
  # Scrape the download page to find the latest stable version
  local latest_version
  latest_version=$(curl -s https://checkmk.com/download | grep -oP 'Stable:.*?v\K[0-9]+\.[0-9]+\.[0-9]+p[0-9]+' | head -1 || echo "")
  
  if [[ -z "$latest_version" ]]; then
    log_warning "Could not determine latest version from website, trying alternative method..." >&2
    # Try to list versions from download server
    latest_version=$(curl -s https://download.checkmk.com/checkmk/ | grep -oP 'href="[0-9]+\.[0-9]+\.[0-9]+p[0-9]+/"' | grep -oP '[0-9]+\.[0-9]+\.[0-9]+p[0-9]+' | sort -V | tail -1 || echo "")
  fi
  
  if [[ -z "$latest_version" ]]; then
    log_warning "Could not auto-detect version, using default 2.4.0p16" >&2
    latest_version="2.4.0p16"
  fi
  
  local url="https://download.checkmk.com/checkmk/${latest_version}/check-mk-raw-${latest_version}_0.${os_codename}_amd64.deb"
  
  log_info "Latest version: $latest_version for $os_codename" >&2
  echo "$url"
}

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
  
  # Install the package using dpkg directly to force reinstallation
  if ! log_command "dpkg -i '$package'"; then
    log_error "Failed to install CheckMK package"
    log_info "Attempting to fix dependencies..."
    log_command "apt-get install -f -y"
    return 1
  fi
  
  # Fix any dependency issues
  log_command "apt-get install -f -y"
  
  # Verify omd command is available
  if ! command -v omd &> /dev/null; then
    log_error "omd command not found after installation"
    log_info "Attempting to fix symlinks..."
    
    # Recreate symlink if needed
    if [[ -d /omd/versions ]]; then
      local version
      version=$(find /omd/versions/ -maxdepth 1 -type d ! -name "versions" ! -name "default" -printf "%f\n" | head -1)
      if [[ -n "$version" ]]; then
        log_debug "Found version: $version"
        ln -sf "/omd/versions/$version/bin/omd" /usr/bin/omd
      fi
    fi
    
    # Check again
    if ! command -v omd &> /dev/null; then
      log_error "Failed to fix omd command"
      return 1
    fi
  fi
  
  # Ensure /omd/apache directory exists (needed for site enable)
  if [[ ! -d /omd/apache ]]; then
    log_debug "Creating /omd/apache directory"
    mkdir -p /omd/apache
    chmod 755 /omd/apache
  fi
  
  log_success "CheckMK package installed"
}

#############################################
# Create CheckMK site
#############################################
create_checkmk_site() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  
  log_info "Creating CheckMK site: $site_name"
  
  # Ensure /omd/sites directory exists
  if [[ ! -d /omd/sites ]]; then
    log_debug "Creating /omd/sites directory"
    mkdir -p /omd/sites
    chmod 755 /omd/sites
  fi
  
  # Check if site already exists (safely handle empty directory)
  if [[ -d "/omd/sites/$site_name" ]]; then
    log_warning "Site '$site_name' already exists"
    
    # Enable site if disabled
    if omd status "$site_name" 2>&1 | grep -q "This site is disabled"; then
      log_info "Enabling existing site..."
      omd enable "$site_name" || log_warning "Could not enable site"
    fi
    
    return 0
  fi
  
  # Create site and capture the auto-generated password
  local create_output
  create_output=$(omd create "$site_name" 2>&1)
  local exit_code=$?
  
  # Always show the output for debugging
  log_debug "omd create output: $create_output"
  
  if [[ $exit_code -ne 0 ]]; then
    log_error "Failed to create site"
    log_error "Output: $create_output"
    return 1
  fi
  
  # Extract auto-generated password from output
  # Output format: "Created new site monitoring with version 2.4.0p16.cre.
  #                 The site can be started with omd start monitoring.
  #                 The default GUI is available at http://...
  #                 The admin user for the web applications is cmkadmin with password: <PASSWORD>"
  CHECKMK_AUTO_PASSWORD=$(echo "$create_output" | grep -oP 'password: \K\S+' || echo "")
  
  if [[ -z "$CHECKMK_AUTO_PASSWORD" ]]; then
    log_warning "Could not extract auto-generated password from output"
    log_debug "omd create output: $create_output"
  else
    log_debug "Captured auto-generated password"
  fi
  
  # Enable the site (required before configuration)
  log_info "Enabling site..."
  if ! omd enable "$site_name" 2>&1; then
    log_error "Failed to enable site"
    return 1
  fi
  
  log_success "Site '$site_name' created and enabled"
}

#############################################
# Configure CheckMK site
#############################################
configure_checkmk_site() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  
  log_info "Configuring CheckMK site..."
  
  # Keep auto-generated password - do not override with htpasswd
  log_debug "Using auto-generated admin password from site creation"
  
  # Configure site settings
  log_debug "Configuring site settings"
  local server_ip
  server_ip=$(hostname -I | awk '{print $1}')
  omd config "$site_name" set APACHE_TCP_ADDR "$server_ip"
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
    # Use dpkg with force options to handle cleanup issues
    if dpkg -i --force-all $agent_deb 2>&1 | tee -a "$LOG_FILE"; then
      log_success "Local agent installed"
    else
      log_warning "Agent installation had errors but continuing..."
    fi
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
display_installation_summary() {
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  local http_port="${CHECKMK_HTTP_PORT:-5000}"
  local admin_password="${CHECKMK_AUTO_PASSWORD:-N/A}"
  local server_ip
  server_ip=$(hostname -I | awk '{print $1}')
  
  echo ""
  echo "=========================================="
  echo "CheckMK Installation Complete!"
  echo "=========================================="
  echo ""
  echo "  Site Name: $site_name"
  echo "  Web Interface: http://${server_ip}:${http_port}/${site_name}/"
  echo "  Admin User: cmkadmin"
  echo "  Admin Password: $admin_password (AUTO-GENERATED)"
  echo ""
  echo "  Commands:"
  echo "    - omd status $site_name"
  echo "    - omd start/stop/restart $site_name"
  echo "    - omd config $site_name"
  echo ""
  echo "  Backup: /usr/local/bin/backup-checkmk.sh"
  echo "=========================================="
  echo ""
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting CheckMK server installation..."
  
  # Auto-detect latest version if URL not provided
  local url="${CHECKMK_DEB_URL:-}"
  if [[ -z "$url" ]]; then
    log_info "No URL provided, auto-detecting latest version..."
    url=$(get_latest_checkmk_url)
  fi
  
  if [[ -z "${CHECKMK_ADMIN_PASSWORD:-}" ]]; then
    log_error "CHECKMK_ADMIN_PASSWORD not set in configuration"
    exit 1
  fi
  
  # Execute installation steps
  install_checkmk_dependencies
  
  download_checkmk "$url"
  install_checkmk_package "/tmp/check-mk-raw.deb"
  
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
  
  display_installation_summary
}

# Run main function
main "$@"
