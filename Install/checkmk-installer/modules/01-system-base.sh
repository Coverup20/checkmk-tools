#!/usr/bin/env bash
# 01-system-base.sh - Base system configuration module
# Configures: SSH, NTP, UFW, Fail2Ban, base packages, unattended-upgrades

set -euo pipefail

MODULE_NAME="System Base Configuration"
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
# SSH Configuration
#############################################
configure_ssh() {
  log_info "Configuring SSH server..."
  
  local ssh_config="/etc/ssh/sshd_config"
  local ssh_port="${SSH_PORT:-22}"
  local permit_root="${PERMIT_ROOT_LOGIN:-no}"
  local client_alive_interval="${CLIENT_ALIVE_INTERVAL:-300}"
  local client_alive_countmax="${CLIENT_ALIVE_COUNTMAX:-3}"
  local login_grace_time="${LOGIN_GRACE_TIME:-60}"
  
  # Backup original config
  if [[ ! -f "${ssh_config}.bak" ]]; then
    log_command "cp $ssh_config ${ssh_config}.bak"
  fi
  
  # Update SSH configuration
  log_debug "Setting SSH port to $ssh_port"
  sed -i "s/^#\?Port .*/Port $ssh_port/" "$ssh_config"
  
  log_debug "Setting PermitRootLogin to $permit_root"
  sed -i "s/^#\?PermitRootLogin .*/PermitRootLogin $permit_root/" "$ssh_config"
  
  log_debug "Setting ClientAliveInterval to $client_alive_interval"
  sed -i "s/^#\?ClientAliveInterval .*/ClientAliveInterval $client_alive_interval/" "$ssh_config"
  
  log_debug "Setting ClientAliveCountMax to $client_alive_countmax"
  sed -i "s/^#\?ClientAliveCountMax .*/ClientAliveCountMax $client_alive_countmax/" "$ssh_config"
  
  log_debug "Setting LoginGraceTime to $login_grace_time"
  sed -i "s/^#\?LoginGraceTime .*/LoginGraceTime $login_grace_time/" "$ssh_config"
  
  # Disable password authentication (use keys only)
  if [[ "${SSH_PASSWORD_AUTH:-yes}" == "no" ]]; then
    log_debug "Disabling password authentication"
    sed -i "s/^#\?PasswordAuthentication .*/PasswordAuthentication no/" "$ssh_config"
  fi
  
  # Restart SSH
  log_command "systemctl restart sshd"
  
  log_success "SSH configured successfully (port: $ssh_port)"
}

#############################################
# Change root password
#############################################
change_root_password() {
  if [[ -n "${ROOT_PASSWORD:-}" ]]; then
    log_info "Changing root password..."
    echo "root:${ROOT_PASSWORD}" | chpasswd
    log_success "Root password changed"
  fi
}

#############################################
# NTP Configuration
#############################################
configure_ntp() {
  log_info "Configuring NTP (systemd-timesyncd)..."
  
  local ntp_servers="${NTP_SERVERS:-0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org}"
  local timezone="${TIMEZONE:-UTC}"
  
  # Set timezone
  log_command "timedatectl set-timezone $timezone"
  log_success "Timezone set to $timezone"
  
  # Configure timesyncd
  local timesyncd_conf="/etc/systemd/timesyncd.conf"
  
  if [[ ! -f "${timesyncd_conf}.bak" ]]; then
    log_command "cp $timesyncd_conf ${timesyncd_conf}.bak"
  fi
  
  cat > "$timesyncd_conf" <<EOF
[Time]
NTP=$ntp_servers
FallbackNTP=time.cloudflare.com time.google.com
EOF
  
  # Enable and start timesyncd
  log_command "systemctl enable systemd-timesyncd"
  log_command "systemctl restart systemd-timesyncd"
  
  log_success "NTP configured with servers: $ntp_servers"
}

#############################################
# Install base packages
#############################################
install_base_packages() {
  log_info "Installing base packages..."
  
  # Update package lists
  log_command "apt-get update"
  
  # Base packages
  local packages=(
    "curl"
    "wget"
    "git"
    "vim"
    "nano"
    "htop"
    "net-tools"
    "dnsutils"
    "jq"
    "unzip"
    "build-essential"
    "software-properties-common"
    "apt-transport-https"
    "ca-certificates"
    "gnupg"
    "lsb-release"
    "sudo"
    "rsync"
    "screen"
    "tmux"
  )
  
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y ${packages[*]}"
  
  log_success "Base packages installed"
}

#############################################
# Configure unattended-upgrades
#############################################
configure_unattended_upgrades() {
  log_info "Configuring automatic security updates..."
  
  # Install unattended-upgrades
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y unattended-upgrades"
  
  # Configure
  local config="/etc/apt/apt.conf.d/50unattended-upgrades"
  
  cat > "$config" <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};

Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
EOF
  
  # Enable automatic updates
  cat > "/etc/apt/apt.conf.d/20auto-upgrades" <<EOF
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "7";
APT::Periodic::Unattended-Upgrade "1";
EOF
  
  log_success "Automatic security updates configured"
}

#############################################
# Configure UFW (Firewall)
#############################################
configure_ufw() {
  log_info "Configuring UFW firewall..."
  
  # Install UFW
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y ufw"
  
  # Reset UFW to default
  log_command "ufw --force reset"
  
  # Default policies
  log_command "ufw default deny incoming"
  log_command "ufw default allow outgoing"
  
  # Allow SSH
  local ssh_port="${SSH_PORT:-22}"
  log_command "ufw allow $ssh_port/tcp comment 'SSH'"
  
  # Allow CheckMK if applicable
  if [[ "${INSTALL_CHECKMK_SERVER:-no}" == "yes" ]]; then
    log_command "ufw allow 5000/tcp comment 'CheckMK HTTP'"
    log_command "ufw allow 6556/tcp comment 'CheckMK Agent'"
  fi
  
  # Allow HTTP/HTTPS if needed
  if [[ "${OPEN_HTTP_HTTPS:-no}" == "yes" ]]; then
    log_command "ufw allow 80/tcp comment 'HTTP'"
    log_command "ufw allow 443/tcp comment 'HTTPS'"
  fi
  
  # Enable UFW
  log_command "ufw --force enable"
  
  log_success "UFW firewall configured and enabled"
}

#############################################
# Configure Fail2Ban
#############################################
configure_fail2ban() {
  log_info "Configuring Fail2Ban..."
  
  # Install Fail2Ban
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban"
  
  # Create local configuration
  local jail_local="/etc/fail2ban/jail.local"
  
  cat > "$jail_local" <<EOF
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5
destemail = ${FAIL2BAN_EMAIL:-root@localhost}
sendername = Fail2Ban
action = %(action_mwl)s

[sshd]
enabled = true
port = ${SSH_PORT:-22}
logpath = %(sshd_log)s
backend = systemd
maxretry = 3
bantime = 7200
EOF
  
  # Enable and start Fail2Ban
  log_command "systemctl enable fail2ban"
  log_command "systemctl restart fail2ban"
  
  log_success "Fail2Ban configured and started"
}

#############################################
# Configure Postfix (minimal)
#############################################
configure_postfix() {
  log_info "Configuring Postfix for local mail..."
  
  # Pre-configure postfix
  echo "postfix postfix/main_mailer_type string 'Internet Site'" | debconf-set-selections
  echo "postfix postfix/mailname string $(hostname -f)" | debconf-set-selections
  
  # Install postfix
  log_command "DEBIAN_FRONTEND=noninteractive apt-get install -y postfix mailutils"
  
  # Configure as internet site
  local postfix_main="/etc/postfix/main.cf"
  
  if [[ -n "${SMTP_RELAY_HOST:-}" ]]; then
    log_debug "Configuring SMTP relay: ${SMTP_RELAY_HOST}"
    postconf -e "relayhost = ${SMTP_RELAY_HOST}"
  fi
  
  # Restart postfix
  log_command "systemctl restart postfix"
  
  log_success "Postfix configured"
}

#############################################
# System hardening
#############################################
system_hardening() {
  log_info "Applying system hardening..."
  
  # Disable IPv6 if not needed
  if [[ "${DISABLE_IPV6:-no}" == "yes" ]]; then
    log_debug "Disabling IPv6"
    cat >> /etc/sysctl.conf <<EOF

# Disable IPv6
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
    sysctl -p > /dev/null
  fi
  
  # Enable SYN cookies
  echo "net.ipv4.tcp_syncookies = 1" >> /etc/sysctl.conf
  
  # Ignore ICMP redirects
  echo "net.ipv4.conf.all.accept_redirects = 0" >> /etc/sysctl.conf
  
  # Apply changes
  sysctl -p > /dev/null
  
  log_success "System hardening applied"
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting system base configuration..."
  
  # Execute all configuration steps
  change_root_password
  configure_ssh
  configure_ntp
  install_base_packages
  configure_unattended_upgrades
  configure_ufw
  configure_fail2ban
  configure_postfix
  system_hardening
  
  log_module_end "$MODULE_NAME" "success"
  
  print_separator
  log_success "System base configuration completed successfully!"
  echo ""
  log_info "Next steps:"
  echo "  - SSH port: ${SSH_PORT:-22}"
  echo "  - Firewall: Active (use 'ufw status' to check)"
  echo "  - Fail2Ban: Active (use 'fail2ban-client status' to check)"
  echo ""
}

# Run main function
main "$@"
