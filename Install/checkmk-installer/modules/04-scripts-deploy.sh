#!/usr/bin/env bash
# 04-scripts-deploy.sh - Deploy monitoring scripts
# Deploys all monitoring scripts from local repository

set -euo pipefail

MODULE_NAME="Monitoring Scripts Deployment"
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

# Script source directory (go up 2 levels to repo root)
SCRIPTS_SRC="$(dirname "$(dirname "$INSTALLER_ROOT")")"

#############################################
# Deploy notification scripts
#############################################
deploy_notify_scripts() {
  log_info "Deploying notification scripts..."
  
  local src="${SCRIPTS_SRC}/script-notify-checkmk"
  local dest="/opt/script-notify-checkmk"
  
  if [[ ! -d "$src" ]]; then
    log_warning "Notification scripts not found in: $src"
    return 0
  fi
  
  # Create destination
  mkdir -p "$dest"
  
  # Copy scripts
  cp -r "$src"/* "$dest/"
  log_write "INFO" "Copied notification scripts"
  
  # Set permissions on all executables
  chmod -R +x "$dest"/*.sh "$dest"/mail* "$dest"/telegram* "$dest"/ydea* "$dest"/dump_env 2>/dev/null || true
  
  # Create symlinks for main notification scripts
  for script_name in mail_realip telegram_realip ydea_realip; do
    if [[ -f "$dest/$script_name" ]]; then
      ln -sf "$dest/$script_name" "/usr/local/bin/$script_name"
      log_debug "Linked: $script_name"
    fi
  done
  
  log_success "Notification scripts deployed to: $dest"
}

#############################################
# Deploy check scripts by platform
#############################################
deploy_check_scripts() {
  local platform="$1"
  
  log_info "Deploying $platform check scripts..."
  
  local src="${SCRIPTS_SRC}/script-check-${platform}"
  local dest="/opt/script-check-${platform}"
  
  if [[ ! -d "$src" ]]; then
    log_warning "Check scripts for $platform not found"
    return 0
  fi
  
  # Create destination
  mkdir -p "$dest"
  
  # Copy scripts
  cp -r "$src"/* "$dest/"
  log_write "INFO" "Copied Proxmox scripts"
  
  # Set permissions
  chmod -R +x "$dest"/*.sh "$dest"/*.pl "$dest"/*.py 2>/dev/null || true
  
  # Install polling scripts to CheckMK agent
  if [[ -d "$dest/polling" ]]; then
    local agent_plugins="/usr/lib/check_mk_agent/plugins"
    if [[ -d "$agent_plugins" ]]; then
      log_debug "Installing polling scripts to agent..."
      cp -r "$dest/polling"/* "$agent_plugins/" 2>/dev/null || true
      chmod +x "$agent_plugins"/* 2>/dev/null || true
    fi
  fi
  
  log_success "$platform check scripts deployed"
}

#############################################
# Deploy tool scripts
#############################################
deploy_tool_scripts() {
  log_info "Deploying tool scripts..."
  
  local src="${SCRIPTS_SRC}/script-tools"
  local dest="/opt/script-tools"
  
  if [[ ! -d "$src" ]]; then
    log_warning "Tool scripts not found"
    return 0
  fi
  
  # Create destination
  mkdir -p "$dest"
  
  # Copy scripts
  cp -r "$src"/* "$dest/"
  log_write "INFO" "Copied tool scripts"
  
  # Set permissions
  chmod -R +x "$dest"/*.sh 2>/dev/null || true  
  # Create symlinks for commonly used tools
  local common_tools=(
    "checkmk-tuning-interactive-v5.sh"
    "deploy-plain-agent.sh"
    "install-agent-interactive.sh"
    "smart-wrapper.sh"
  )
  
  for tool in "${common_tools[@]}"; do
    if [[ -f "$dest/$tool" ]]; then
      local link_name=$(basename "$tool" .sh)
      ln -sf "$dest/$tool" "/usr/local/bin/$link_name"
      log_debug "Linked: $link_name"
    fi
  done
  
  log_success "Tool scripts deployed to: $dest"
}

#############################################
# Deploy Proxmox scripts
#############################################
deploy_proxmox_scripts() {
  log_info "Deploying Proxmox scripts..."
  
  local src="${SCRIPTS_SRC}/Proxmox"
  local dest="/opt/script-check-proxmox"
  
  if [[ ! -d "$src" ]]; then
    log_warning "Proxmox scripts not found"
    return 0
  fi
  
  # Create destination
  mkdir -p "$dest"
  
  # Copy scripts
  cp -r "$src"/* "$dest/"
  log_write "INFO" "Copied NS7 check scripts"
  
  # Set permissions
  chmod -R +x "$dest"/*.sh 2>/dev/null || true
  
  log_success "Proxmox scripts deployed to: $dest"
}

#############################################
# Deploy fix scripts
#############################################
deploy_fix_scripts() {
  log_info "Deploying fix scripts..."
  
  local src="${SCRIPTS_SRC}/Fix"
  local dest="/opt/script-fix"
  
  if [[ ! -d "$src" ]]; then
    log_warning "Fix scripts not found"
    return 0
  fi
  
  # Create destination
  mkdir -p "$dest"
  
  # Copy scripts
  cp -r "$src"/* "$dest/"
  log_write "INFO" "Copied fix scripts"
  
  # Set permissions
  chmod -R +x "$dest"/*.sh "$dest"/*.ps1 "$dest"/*.bat 2>/dev/null || true
  
  log_success "Fix scripts deployed to: $dest"
}

#############################################
# Create master update script
#############################################
create_update_script() {
  log_info "Creating master update script..."
  
  cat > /usr/local/bin/update-checkmk-scripts <<'EOF'
#!/bin/bash
# Update all CheckMK scripts from GitHub or local source

set -euo pipefail

REPO_URL="https://github.com/Coverup20/checkmk-tools.git"
LOCAL_REPO="/opt/checkmk-tools"
BACKUP_DIR="/opt/backups/scripts"

echo "=== CheckMK Scripts Update ==="
echo ""

# Create backup
echo "Creating backup..."
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/scripts-backup-$(date +%Y%m%d_%H%M%S).tar.gz"
tar czf "$BACKUP_FILE" /opt/script-* /usr/local/bin/*checkmk* 2>/dev/null || true
echo "Backup created: $BACKUP_FILE"
echo ""

# Update from GitHub or local
if [[ -d "$LOCAL_REPO" ]]; then
  echo "Updating from local repository..."
  cd "$LOCAL_REPO"
  git pull origin main
else
  echo "Cloning repository..."
  git clone "$REPO_URL" "$LOCAL_REPO"
fi

echo ""
echo "Deploying updated scripts..."

# Re-run deployment
if [[ -f "$LOCAL_REPO/Install/checkmk-installer/modules/04-scripts-deploy.sh" ]]; then
  bash "$LOCAL_REPO/Install/checkmk-installer/modules/04-scripts-deploy.sh"
else
  echo "ERROR: Deployment script not found"
  exit 1
fi

echo ""
echo "Update completed!"
EOF
  
  chmod +x /usr/local/bin/update-checkmk-scripts
  
  log_success "Update script created: /usr/local/bin/update-checkmk-scripts"
}

#############################################
# Install remote launcher scripts
#############################################
install_remote_launchers() {
  log_info "Installing remote launcher scripts..."
  
  local launchers_src="${SCRIPTS_SRC}"
  local count=0
  
  # Find all r* launcher scripts
  for launcher in "$launchers_src"/*/r*; do
    if [[ -f "$launcher" ]]; then
      local launcher_name=$(basename "$launcher")
      cp "$launcher" "/usr/local/bin/$launcher_name"
      chmod +x "/usr/local/bin/$launcher_name"
      ((count++))
      log_debug "Installed: $launcher_name"
    fi
  done
  
  log_success "Installed $count remote launcher scripts"
}

#############################################
# Configure CheckMK to use scripts
#############################################
configure_checkmk_notifications() {
  log_info "Configuring CheckMK notification scripts..."
  
  local site_name="${CHECKMK_SITE_NAME:-monitoring}"
  local omd_root="/omd/sites/$site_name"
  local notify_dir="$omd_root/local/share/check_mk/notifications"
  
  if [[ ! -d "$omd_root" ]]; then
    log_warning "CheckMK site not found, skipping notification configuration"
    return 0
  fi
  
  # Create notifications directory
  su - "$site_name" -c "mkdir -p '$notify_dir'" 2>/dev/null || true
  
  # Link notification scripts
  for script in /opt/script-notify-checkmk/*; do
    if [[ -f "$script" ]] && [[ -x "$script" ]]; then
      local script_name=$(basename "$script")
      su - "$site_name" -c "ln -sf '$script' '$notify_dir/$script_name'" 2>/dev/null || true
      log_debug "Linked notification: $script_name"
    fi
  done
  
  log_success "Notification scripts configured"
}

#############################################
# Create script inventory
#############################################
create_script_inventory() {
  log_info "Creating script inventory..."
  
  local inventory_file="/opt/checkmk-scripts-inventory.txt"
  
  cat > "$inventory_file" <<EOF
# CheckMK Scripts Inventory
# Generated: $(date)

## Notification Scripts
Location: /opt/script-notify-checkmk/
EOF
  
  if [[ -d "/opt/script-notify-checkmk" ]]; then
    ls -1 /opt/script-notify-checkmk/ >> "$inventory_file"
  fi
  
  cat >> "$inventory_file" <<EOF

## Check Scripts (NS7)
Location: /opt/script-check-ns7/
EOF
  
  if [[ -d "/opt/script-check-ns7" ]]; then
    ls -1 /opt/script-check-ns7/ >> "$inventory_file"
  fi
  
  cat >> "$inventory_file" <<EOF

## Check Scripts (NS8)
Location: /opt/script-check-ns8/
EOF
  
  if [[ -d "/opt/script-check-ns8" ]]; then
    ls -1 /opt/script-check-ns8/ >> "$inventory_file"
  fi
  
  cat >> "$inventory_file" <<EOF

## Check Scripts (Ubuntu)
Location: /opt/script-check-ubuntu/
EOF
  
  if [[ -d "/opt/script-check-ubuntu" ]]; then
    ls -1 /opt/script-check-ubuntu/ >> "$inventory_file"
  fi
  
  cat >> "$inventory_file" <<EOF

## Tool Scripts
Location: /opt/script-tools/
EOF
  
  if [[ -d "/opt/script-tools" ]]; then
    ls -1 /opt/script-tools/ >> "$inventory_file"
  fi
  
  log_success "Inventory created: $inventory_file"
}

#############################################
# Display deployment summary
#############################################
display_deployment_summary() {
  local total_scripts=$(find /opt/script-* -type f 2>/dev/null | wc -l)
  local total_links=$(find /usr/local/bin -type l 2>/dev/null | wc -l)
  
  print_separator "="
  echo ""
  display_box "Scripts Deployment Complete!" \
    "" \
    "Total scripts deployed: $total_scripts" \
    "Symlinks created: $total_links" \
    "" \
    "Directories:" \
    "  - /opt/script-notify-checkmk/" \
    "  - /opt/script-check-*/" \
    "  - /opt/script-tools/" \
    "  - /opt/script-fix/" \
    "" \
    "Update command: update-checkmk-scripts" \
    "Inventory: /opt/checkmk-scripts-inventory.txt"
  echo ""
  print_separator "="
}

#############################################
# Main execution
#############################################
main() {
  log_info "Starting scripts deployment..."
  
  # Check if scripts directory exists
  if [[ ! -d "$SCRIPTS_SRC" ]]; then
    log_error "Scripts directory not found: $SCRIPTS_SRC"
    exit 1
  fi
  
  # Deploy all script categories
  deploy_notify_scripts
  deploy_check_scripts "ns7"
  deploy_check_scripts "ns8"
  deploy_check_scripts "ubuntu"
  deploy_check_scripts "windows"
  deploy_tool_scripts
  deploy_proxmox_scripts
  deploy_fix_scripts
  
  # Install additional components
  install_remote_launchers
  create_update_script
  create_script_inventory
  
  # Configure CheckMK if available
  configure_checkmk_notifications
  
  log_module_end "$MODULE_NAME" "success"
  
  display_deployment_summary
}

# Run main function
main "$@"
