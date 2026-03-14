#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REMOTE="do:testmonbck"

# NEW: external mount base (outside /opt/omd/sites/<SITE>/)
DEFAULT_EXTERNAL_MOUNT_BASE="/mnt/checkmk-spaces"

DEFAULT_SITES_BASES=("/opt/omd/sites" "/omd/sites")

log() { printf '%s\n' "[$(date '+%F %T')] $*"; }
warn() { printf '%s\n' "WARN: $*" >&2; }
die() { printf '%s\n' "ERROR: $*" >&2; exit 1; }

require_root() { [[ "${EUID}" -eq 0 ]] || die "Run as root."; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"; }

# Prompt on stderr, return only the value on stdout (safe for $(...))
prompt_default() {
  local prompt="$1" def="$2" out
  if [[ -n "${def}" ]]; then
    printf "%s [%s]: " "${prompt}" "${def}" >&2
  else
    printf "%s: " "${prompt}" >&2
  fi
  IFS= read -r out
  [[ -z "${out}" ]] && out="${def}"
  printf "%s" "${out}"
}

# No-echo prompt (for secrets)
prompt_secret() {
  local prompt="$1" out
  printf "%s: " "${prompt}" >&2
  stty -echo
  IFS= read -r out
  stty echo
  printf "\n" >&2
  printf "%s" "${out}"
}

confirm_default_no() {
  local prompt="$1" ans
  printf "%s [y/N]: " "${prompt}" >&2
  IFS= read -r ans
  [[ "${ans}" =~ ^[Yy]$ ]]
}

# Try to discover site bases that actually exist
discover_site_bases() {
  local b
  for b in "${DEFAULT_SITES_BASES[@]}"; do
    [[ -d "${b}" ]] && echo "${b}"
  done
}

# List sites via omd if available, else via directories under discovered bases
list_sites() {
  if command -v omd >/dev/null 2>&1; then
    omd sites 2>/dev/null | awk 'NR>1 && $1 ~ /^[a-zA-Z0-9_][a-zA-Z0-9_-]*$/ {print $1}' | sort -u
    return 0
  fi

  local bases
  bases="$(discover_site_bases || true)"
  [[ -n "${bases}" ]] || return 1

  while IFS= read -r base; do
    find "${base}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null || true
  done <<< "${bases}" | sort -u
}

pick_site_interactive_or_manual() {
  local sites
  sites="$(list_sites || true)"

  if [[ -z "${sites}" ]]; then
    warn "No sites auto-discovered. You can still proceed by entering site name manually."
    local site_manual
    site_manual="$(prompt_default "Enter site name" "monitoring")"
    echo "${site_manual}"
    return 0
  fi

  log "Available OMD sites:"
  local i=0
  while IFS= read -r s; do
    i=$((i+1))
    printf "  [%d] %s\n" "$i" "$s"
  done <<< "${sites}"

  local choice
  while true; do
    printf "Select site number (or type a site name): " >&2
    read -r choice
    if [[ "${choice}" =~ ^[0-9]+$ ]]; then
      local selected
      selected="$(awk -v n="${choice}" 'NR==n {print; exit}' <<< "${sites}")"
      [[ -n "${selected}" ]] || { warn "Invalid selection."; continue; }
      echo "${selected}"
      return 0
    fi
    if [[ "${choice}" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_-]*$ ]]; then
      echo "${choice}"
      return 0
    fi
    warn "Invalid input."
  done
}

resolve_site_home() {
  local site="$1"

  if command -v omd >/dev/null 2>&1; then
    local home
    home="$(omd config "${site}" show HOME 2>/dev/null | awk '{print $NF}' || true)"
    [[ -n "${home}" && -d "${home}" ]] && { echo "${home}"; return 0; }
  fi

  local base
  while IFS= read -r base; do
    if [[ -d "${base}/${site}" ]]; then
      echo "${base}/${site}"
      return 0
    fi
  done < <(discover_site_bases || true)

  local guess="/opt/omd/sites/${site}"
  prompt_default "Enter full site home path" "${guess}"
}

site_user_from_site() { echo "$1"; }

install_rclone_stable() {
  need_cmd curl
  
  # Check if rclone is already installed and recent enough
  if command -v rclone >/dev/null 2>&1; then
    log "rclone is already installed: $(rclone version 2>/dev/null | head -n 1 || echo 'version unknown')"
    log "Skipping installation. To force reinstall, remove rclone first."
    return 0
  fi
  
  log "Installing rclone (stable) from rclone.org..."
  local install_script="/tmp/rclone-install-$$.sh"
  
  if curl -fsSL https://rclone.org/install.sh -o "${install_script}"; then
    bash "${install_script}"
    rm -f "${install_script}"
  else
    die "Failed to download rclone install script"
  fi
  
  need_cmd rclone
  log "Installed: $(rclone version | head -n 1)"
}

ensure_fuse_allow_other() {
  log "Ensuring /etc/fuse.conf enables user_allow_other..."
  
  if [[ ! -f /etc/fuse.conf ]]; then
    die "/etc/fuse.conf not found (install fuse3)."
  fi
  
  log "fuse.conf found, checking content..."

  # Simple approach: check if user_allow_other is already enabled
  if grep -q '^user_allow_other$' /etc/fuse.conf 2>/dev/null; then
    log "user_allow_other already enabled in fuse.conf"
    return 0
  fi
  
  log "Enabling user_allow_other in fuse.conf..."
  
  # Backup
  cp /etc/fuse.conf "/etc/fuse.conf.backup.$(date +%s)" 2>/dev/null || true
  
  # If commented, uncomment it
  if grep -q '^#.*user_allow_other' /etc/fuse.conf 2>/dev/null; then
    log "Uncommenting user_allow_other..."
    sed -i 's/^#.*user_allow_other$/user_allow_other/' /etc/fuse.conf 2>/dev/null || true
  else
    log "Adding user_allow_other..."
    echo "user_allow_other" >> /etc/fuse.conf
  fi
  
  # Verify
  if grep -q '^user_allow_other$' /etc/fuse.conf 2>/dev/null; then
    log "fuse.conf configured successfully."
  else
    warn "Could not verify user_allow_other in fuse.conf, but continuing..."
  fi
}

# ---- EXTERNAL MOUNTPOINT NORMALIZATION / SAFETY ----

normalize_abs_mountpoint() {
  local mp="$1"
  # trim spaces
  mp="${mp#"${mp%%[![:space:]]*}"}"
  mp="${mp%"${mp##*[![:space:]]}"}"
  [[ -n "${mp}" ]] || die "Mountpoint cannot be empty."
  [[ "${mp}" == /* ]] || die "Mountpoint must be an ABSOLUTE path (start with '/')."
  [[ "${mp}" != *".."* ]] || die "Mountpoint cannot contain '..'."
  mp="${mp%/}"
  [[ -n "${mp}" && "${mp}" != "/" ]] || die "Refusing mountpoint '${mp}'."
  printf "%s" "${mp}"
}

assert_mountpoint_outside_site() {
  local site_home="$1" mp="$2"
  # Ensure mp is NOT inside site_home
  case "${mp}" in
    "${site_home}"| "${site_home}/"*) die "Mountpoint must be EXTERNAL to the site. Refusing: ${mp} (site_home=${site_home})" ;;
  esac
}

default_external_mountpoint_for_site() {
  local site="$1"
  printf "%s/%s" "${DEFAULT_EXTERNAL_MOUNT_BASE}" "${site}"
}

# ---- RCLONE REMOTE / CREDENTIALS MANAGEMENT ----

remote_exists() {
  local rclone_config="$1" remote_name="$2"
  RCLONE_CONFIG="${rclone_config}" rclone config show "${remote_name}" >/dev/null 2>&1
}

create_or_update_remote_s3() {
  local rclone_config="$1" remote_name="$2"
  local provider="$3" access_key="$4" secret_key="$5" region="$6" endpoint="$7"

  log "Creating/updating rclone remote '${remote_name}' in ${rclone_config} ..."
  RCLONE_CONFIG="${rclone_config}" rclone config create "${remote_name}" s3 \
    provider="${provider}" \
    env_auth="false" \
    access_key_id="${access_key}" \
    secret_access_key="${secret_key}" \
    region="${region}" \
    endpoint="${endpoint}" \
    acl="private" \
    --obscure
}

ensure_remote_configured() {
  local rclone_config="$1" remote_full="$2"
  local remote_name="${remote_full%%:*}"
  [[ -n "${remote_name}" && "${remote_full}" == *:* ]] || die "Remote must be in form name:bucket (e.g. do:mybucket). Got: ${remote_full}"

  if remote_exists "${rclone_config}" "${remote_name}"; then
    if confirm_default_no "Remote '${remote_name}' already exists. Reconfigure it?"; then
      log "Reconfiguring existing remote '${remote_name}'."
    else
      log "Remote '${remote_name}' already configured."
      return 0
    fi
  else
    log "Remote '${remote_name}' not found in ${rclone_config}. Will create it now."
  fi

  local mode
  mode="$(prompt_default "Remote type (do/aws)" "do")"

  local access_key secret_key region endpoint provider
  access_key="$(prompt_default "S3 Access Key ID" "")"
  [[ -n "${access_key}" ]] || die "Access Key ID cannot be empty."
  secret_key="$(prompt_secret "S3 Secret Access Key")"
  [[ -n "${secret_key}" ]] || die "Secret Access Key cannot be empty."

  if [[ "${mode}" == "do" ]]; then
    region="$(prompt_default "DO Spaces region (e.g. nyc3, fra1, ams3)" "fra1")"
    endpoint="$(prompt_default "DO Spaces endpoint URL" "https://${region}.digitaloceanspaces.com")"
    provider="DigitalOcean"
  else
    region="$(prompt_default "AWS region (e.g. eu-west-1)" "eu-west-1")"
    endpoint="$(prompt_default "AWS S3 endpoint URL (leave default for AWS)" "https://s3.${region}.amazonaws.com")"
    provider="AWS"
  fi

  create_or_update_remote_s3 "${rclone_config}" "${remote_name}" "${provider}" "${access_key}" "${secret_key}" "${region}" "${endpoint}"

  log "Testing remote connectivity (may fail if bucket ACL/policy blocks list):"
  if ! RCLONE_CONFIG="${rclone_config}" rclone lsd "${remote_name}:" >/dev/null 2>&1; then
    warn "Remote test 'rclone lsd ${remote_name}:' failed. Credentials may still be valid, but list may be blocked. You can verify with: RCLONE_CONFIG=${rclone_config} rclone ls ${remote_full}"
  else
    log "Remote test OK."
  fi
}

# ---- SYSTEMD UNIT ----

write_unit() {
  local unit_path="$1" unit_name="$2" site="$3" site_user="$4" site_group="$5"
  local rclone_config="$6" rclone_bin="$7" remote="$8" mountpoint="$9"

  log "Writing systemd unit: ${unit_name} to ${unit_path}"
  log "Unit parameters: site=${site}, user=${site_user}, group=${site_group}, remote=${remote}, mountpoint=${mountpoint}"
  
  cat > "${unit_path}" <<EOFU
[Unit]
Description=Rclone mount ${remote} for Checkmk site ${site} (external mountpoint)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${site_user}
Group=${site_group}
Environment=RCLONE_CONFIG=${rclone_config}
ExecStart=${rclone_bin} mount ${remote} ${mountpoint} --allow-other --uid $(id -u "${site_user}") --gid $(id -g "${site_group}") --umask 002 --vfs-cache-mode writes
ExecStop=/bin/fusermount3 -u ${mountpoint}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOFU
  
  if [[ ! -f "${unit_path}" ]]; then
    die "Failed to write unit file: ${unit_path}"
  fi
  
  log "Unit file written successfully ($(wc -l < "${unit_path}") lines)"
}

stop_unmount_disable() {
  local unit_name="$1" mountpoint="$2"
  systemctl stop "${unit_name}" >/dev/null 2>&1 || true
  systemctl disable "${unit_name}" >/dev/null 2>&1 || true
  if mount | grep -qF " on ${mountpoint} "; then
    fusermount3 -u "${mountpoint}" || true
  fi
}

setup_flow() {
  need_cmd systemctl
  need_cmd fusermount3

  local site site_home site_user site_group
  site="$(pick_site_interactive_or_manual)"
  site_home="$(resolve_site_home "${site}")"
  [[ -d "${site_home}" ]] || die "Site home does not exist: ${site_home}"

  site_user="$(site_user_from_site "${site}")"
  if ! id "${site_user}" >/dev/null 2>&1; then
    warn "Default site user '${site_user}' not found."
    site_user="$(prompt_default "Enter site user to run rclone under" "${site}")"
    id "${site_user}" >/dev/null 2>&1 || die "User '${site_user}' not found."
  fi

  site_group="${site_user}"
  if ! getent group "${site_group}" >/dev/null 2>&1; then
    warn "Group '${site_group}' not found; using primary group of ${site_user}."
    site_group="$(id -gn "${site_user}")"
  fi

  local rclone_config="${site_home}/.config/rclone/rclone.conf"
  if [[ ! -f "${rclone_config}" ]]; then
    warn "rclone config not found at ${rclone_config}."
    rclone_config="$(prompt_default "Enter full path to rclone.conf for site" "${rclone_config}")"
    [[ -f "${rclone_config}" ]] || die "rclone config still not found: ${rclone_config}"
  fi

  # Ensure proper permissions for rclone config
  log "Checking permissions for rclone config: ${rclone_config}"
  local config_dir
  config_dir="$(dirname "${rclone_config}")"
  
  # Fix directory permissions
  if [[ -d "${config_dir}" ]]; then
    chown -R "${site_user}:${site_group}" "${config_dir}" || warn "Could not fix ownership of ${config_dir}"
    chmod 755 "${config_dir}" || true
    # Also fix parent .config directory
    chown "${site_user}:${site_group}" "$(dirname "${config_dir}")" 2>/dev/null || true
    chmod 755 "$(dirname "${config_dir}")" 2>/dev/null || true
  fi
  
  # Fix config file permissions
  if [[ -f "${rclone_config}" ]]; then
    chown "${site_user}:${site_group}" "${rclone_config}" || warn "Could not fix ownership of ${rclone_config}"
    chmod 600 "${rclone_config}" || true
    log "Fixed permissions: $(ls -la "${rclone_config}")"
  fi

  local remote mountpoint unit_name unit_path
  remote="$(prompt_default "Enter rclone remote (format name:bucket)" "${DEFAULT_REMOTE}")"

  ensure_remote_configured "${rclone_config}" "${remote}"

  # NEW: external mountpoint default is /mnt/checkmk-spaces/<site>
  local mp_default
  mp_default="$(default_external_mountpoint_for_site "${site}")"
  mountpoint="$(prompt_default "Enter EXTERNAL mountpoint path (absolute)" "${mp_default}")"
  mountpoint="$(normalize_abs_mountpoint "${mountpoint}")"
  assert_mountpoint_outside_site "${site_home}" "${mountpoint}"

  unit_name="$(prompt_default "Enter systemd unit name" "rclone-${site}-spaces.service")"
  unit_path="/etc/systemd/system/${unit_name}"

  log "Summary:"
  echo "  Site:          ${site}"
  echo "  Site home:     ${site_home}"
  echo "  Run as user:   ${site_user}:${site_group}"
  echo "  rclone config: ${rclone_config}"
  echo "  Remote:        ${remote}"
  echo "  Mountpoint:    ${mountpoint}"
  echo "  Unit:          ${unit_name}"
  echo

  install_rclone_stable
  ensure_fuse_allow_other

  log "Creating mountpoint directory: ${mountpoint}"
  mkdir -p "${mountpoint}"
  chown "${site_user}:${site_group}" "${mountpoint}"
  chmod 2775 "${mountpoint}" || true
  log "Mountpoint directory created and configured."

  local rclone_bin
  rclone_bin="$(command -v rclone)"
  [[ -x "${rclone_bin}" ]] || die "rclone binary not executable: ${rclone_bin}"
  log "Using rclone binary: ${rclone_bin}"

  log "Stopping and disabling any existing service..."
  stop_unmount_disable "${unit_name}" "${mountpoint}"
  
  log "Creating systemd unit file..."
  write_unit "${unit_path}" "${unit_name}" "${site}" "${site_user}" "${site_group}" "${rclone_config}" "${rclone_bin}" "${remote}" "${mountpoint}"
  
  [[ -f "${unit_path}" ]] || die "Failed to create unit file: ${unit_path}"
  log "Unit file created successfully: ${unit_path}"

  log "Reloading systemd daemon..."
  systemctl daemon-reload
  
  log "Enabling and starting service: ${unit_name}"
  systemctl enable --now "${unit_name}"

  sleep 2
  
  log "Service status:"
  systemctl status "${unit_name}" --no-pager -l || true

  log "Mount check:"
  if mount | grep -F "${mountpoint}"; then
    log "Mount verified successfully."
  else
    warn "Mount not present after service start. Checking service status..."
    systemctl status "${unit_name}" --no-pager -l || true
    journalctl -u "${unit_name}" -n 50 --no-pager || true
    die "Mount not present after service start."
  fi

  log "Smoke test as ${site_user}:"
  if su - "${site_user}" -c "cd '${mountpoint}' && ls -la . | head -n 20"; then
    log "Smoke test passed."
  else
    warn "Smoke test failed. Service may still be starting up."
  fi

  log "SETUP COMPLETE."
}

remove_flow() {
  need_cmd systemctl
  need_cmd fusermount3

  log "Remove mode: you can remove by selecting a site OR by specifying a unit directly."
  local remove_by
  remove_by="$(prompt_default "Remove by (site/unit)" "site")"

  local site site_home mountpoint unit_name unit_path

  if [[ "${remove_by}" == "unit" ]]; then
    local units choice selected
    units="$(systemctl list-unit-files 'rclone-*.service' --no-legend 2>/dev/null | awk '{print $1}' | sort -u || true)"

    if [[ -n "${units}" ]]; then
      log "Available rclone units:"
      local i=0
      while IFS= read -r u; do
        i=$((i+1))
        printf "  [%d] %s\n" "$i" "$u"
      done <<< "${units}"

      while true; do
        printf "Select unit number (or type full unit name): " >&2
        read -r choice
        if [[ "${choice}" =~ ^[0-9]+$ ]]; then
          selected="$(awk -v n="${choice}" 'NR==n {print; exit}' <<< "${units}")"
          [[ -n "${selected}" ]] || { warn "Invalid selection."; continue; }
          unit_name="${selected}"
          break
        fi
        if [[ "${choice}" =~ ^rclone-.*\.service$ ]]; then
          unit_name="${choice}"
          break
        fi
        warn "Invalid input."
      done
    else
      warn "No rclone-*.service units found. Proceeding with manual entry."
      unit_name="$(prompt_default "Enter systemd unit name to remove" "rclone-testmonbck.service")"
    fi

    local exec mp
    exec="$(systemctl show -p ExecStart --value "${unit_name}" 2>/dev/null || true)"
    mp="$(awk '
      {
        for (i=1; i<=NF; i++) {
          if ($i=="mount" && (i+2)<=NF) { print $(i+2); exit }
        }
      }' <<< "${exec}")"

    if [[ -z "${mp}" ]]; then
      warn "Could not parse mountpoint from unit ExecStart. Asking manually."
      mountpoint="$(prompt_default "Enter mountpoint path to unmount" "/mnt/checkmk-spaces/monitoring")"
    else
      mountpoint="${mp}"
    fi

    mountpoint="$(normalize_abs_mountpoint "${mountpoint}")"
    unit_path="/etc/systemd/system/${unit_name}"

    log "Removing unit: ${unit_name}"
    log "Mountpoint: ${mountpoint}"

    stop_unmount_disable "${unit_name}" "${mountpoint}"

    if [[ -f "${unit_path}" ]]; then
      rm -f "${unit_path}"
      log "Removed unit file: ${unit_path}"
    else
      warn "Unit file not found: ${unit_path}"
    fi
    systemctl daemon-reload
    log "REMOVE COMPLETE."
    return 0
  fi

  site="$(pick_site_interactive_or_manual)"
  site_home="$(resolve_site_home "${site}")"

  local mp_default
  mp_default="$(default_external_mountpoint_for_site "${site}")"
  mountpoint="$(prompt_default "Enter EXTERNAL mountpoint path to unmount (absolute)" "${mp_default}")"
  mountpoint="$(normalize_abs_mountpoint "${mountpoint}")"
  assert_mountpoint_outside_site "${site_home}" "${mountpoint}"

  unit_name="$(prompt_default "Enter systemd unit name to remove" "rclone-${site}-spaces.service")"
  unit_path="/etc/systemd/system/${unit_name}"

  log "Removing:"
  echo "  Site:       ${site}"
  echo "  Site home:  ${site_home}"
  echo "  Mountpoint: ${mountpoint}"
  echo "  Unit:       ${unit_name}"
  echo

  stop_unmount_disable "${unit_name}" "${mountpoint}"

  if [[ -f "${unit_path}" ]]; then
    rm -f "${unit_path}"
    log "Removed unit file: ${unit_path}"
  else
    warn "Unit file not found: ${unit_path}"
  fi

  systemctl daemon-reload
  log "REMOVE COMPLETE."
}

usage() {
  cat <<EOFU
Usage:
  $0 setup    # interactive setup (install rclone, fuse.conf, systemd unit, start)
  $0 remove   # interactive remove (stop/disable unit, unmount, delete unit)

Examples:
  sudo $0 setup
  sudo $0 remove
EOFU
}

main() {
  require_root
  local action="${1:-}"
  case "${action}" in
    setup)  setup_flow ;;
    remove) remove_flow ;;
    -h|--help|"") usage; exit 0 ;;
    *) die "Unknown action: ${action}. Use: setup|remove" ;;
  esac
}

main "$@"
