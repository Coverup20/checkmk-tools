#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REMOTE="do:testmonbck"
DEFAULT_EXTERNAL_MOUNT_BASE="/mnt/checkmk-spaces"
DEFAULT_CACHE_BASE="/var/cache/rclone"
DEFAULT_LOG_BASE="/var/log"
DEFAULT_VFS_CACHE_MAX_SIZE="10G"
DEFAULT_VFS_CACHE_MAX_AGE="24h"
DEFAULT_DIR_CACHE_TIME="5m"
DEFAULT_POLL_INTERVAL="1m"
DEFAULT_TIMEOUT="30s"
DEFAULT_CONTIMEOUT="10s"
DEFAULT_RETRIES="10"
DEFAULT_LOW_LEVEL_RETRIES="20"

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

  [[ -f /etc/fuse.conf ]] || die "/etc/fuse.conf not found (install fuse3)."

  if grep -q '^user_allow_other$' /etc/fuse.conf 2>/dev/null; then
    log "user_allow_other already enabled in fuse.conf"
    return 0
  fi

  log "Enabling user_allow_other in fuse.conf..."
  cp /etc/fuse.conf "/etc/fuse.conf.backup.$(date +%s)" 2>/dev/null || true

  if grep -q '^#.*user_allow_other' /etc/fuse.conf 2>/dev/null; then
    sed -i 's/^#.*user_allow_other.*$/user_allow_other/' /etc/fuse.conf 2>/dev/null || true
  else
    echo "user_allow_other" >> /etc/fuse.conf
  fi

  grep -q '^user_allow_other$' /etc/fuse.conf 2>/dev/null || warn "Could not verify user_allow_other in fuse.conf"
}

# ---- EXTERNAL MOUNTPOINT NORMALIZATION / SAFETY ----

normalize_abs_mountpoint() {
  local mp="$1"
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
  case "${mp}" in
    "${site_home}"| "${site_home}/"*) die "Mountpoint must be EXTERNAL to the site. Refusing: ${mp} (site_home=${site_home})" ;;
  esac
}

default_external_mountpoint_for_site() {
  local site="$1"
  printf "%s/%s" "${DEFAULT_EXTERNAL_MOUNT_BASE}" "${site}"
}

default_cache_dir_for_site() {
  local site="$1"
  printf "%s/%s" "${DEFAULT_CACHE_BASE}" "${site}"
}

default_log_file_for_site() {
  local site="$1"
  printf "%s/rclone-%s-mount.log" "${DEFAULT_LOG_BASE}" "${site}"
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
    region="$(prompt_default "DO Spaces region (e.g. nyc3, fra1, ams3)" "ams3")"
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
    warn "Remote test 'rclone lsd ${remote_name}:' failed. Credentials may still be valid; list may be blocked. You can verify with: RCLONE_CONFIG=${rclone_config} rclone ls ${remote_full}"
  else
    log "Remote test OK."
  fi
}

# ---- SYSTEMD UNIT ----

write_unit() {
  local unit_path="$1" unit_name="$2" site="$3" site_user="$4" site_group="$5"
  local rclone_config="$6" rclone_bin="$7" remote="$8" mountpoint="$9"
  local cache_dir="${10}" log_file="${11}"
  local vfs_cache_max_size="${12}" vfs_cache_max_age="${13}" dir_cache_time="${14}" poll_interval="${15}"
  local timeout="${16}" contimeout="${17}" retries="${18}" low_level_retries="${19}"

  local uid gid
  uid="$(id -u "${site_user}")"
  gid="$(getent group "${site_group}" >/dev/null 2>&1 && id -g "${site_user}" || id -g "${site_user}")"

  log "Writing systemd unit: ${unit_name} to ${unit_path}"
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
# More robust stop behavior for FUSE
TimeoutStopSec=20
ExecStart=${rclone_bin} mount ${remote} ${mountpoint} \\
  --allow-other \\
  --uid ${uid} --gid ${gid} \\
  --umask 002 \\
  --vfs-cache-mode full \\
  --cache-dir ${cache_dir} \\
  --vfs-cache-max-size ${vfs_cache_max_size} \\
  --vfs-cache-max-age ${vfs_cache_max_age} \\
  --dir-cache-time ${dir_cache_time} \\
  --poll-interval ${poll_interval} \\
  --timeout ${timeout} \\
  --contimeout ${contimeout} \\
  --retries ${retries} \\
  --low-level-retries ${low_level_retries} \\
  --log-file ${log_file} \\
  --log-level INFO
ExecStop=/bin/fusermount3 -uz ${mountpoint}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOFU

  [[ -f "${unit_path}" ]] || die "Failed to write unit file: ${unit_path}"
}

write_cleanup_script() {
  local cleanup_script="$1" mountpoint="$2" retention_days="${3:-90}"
  
  log "Creating cleanup script: ${cleanup_script}"
  cat > "${cleanup_script}" <<'EOFCLEANUP'
#!/usr/bin/env bash
set -euo pipefail

MOUNTPOINT="${1:?missing mountpoint}"
RETENTION_DAYS="${2:-90}"
LOGFILE="/var/log/checkmk-backup-cleanup.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGFILE"; }

log "Starting backup cleanup for: $MOUNTPOINT"
log "Retention: ${RETENTION_DAYS} days"

if [[ ! -d "$MOUNTPOINT" ]]; then
  log "ERROR: Mountpoint not found: $MOUNTPOINT"
  exit 1
fi

# First, rename backups without timestamp (only complete backups)
log "Renaming backups without timestamp..."
RENAMED=0
while IFS= read -r -d '' backup; do
  BACKUP_NAME="$(basename "$backup")"
  
  # Skip incomplete backups
  if [[ "$BACKUP_NAME" =~ -incomplete ]]; then
    log "Skipping incomplete backup: $BACKUP_NAME"
    continue
  fi
  
  # Check if backup is stable (not modified in last 2 minutes)
  LAST_MODIFIED=$(stat -c %Y "$backup" 2>/dev/null || echo "0")
  CURRENT_TIME=$(date +%s)
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  
  if [[ $AGE_SECONDS -lt 120 ]]; then
    log "Backup too recent (${AGE_SECONDS}s old), skipping: $BACKUP_NAME"
    continue
  fi
  
  # Check backup size (must be > 100KB to be valid)
  if [[ -d "$backup" ]]; then
    BACKUP_SIZE=$(du -sb "$backup" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$backup" 2>/dev/null || echo "0")
  fi
  
  if [[ $BACKUP_SIZE -lt 102400 ]]; then
    log "Backup too small (${BACKUP_SIZE} bytes), skipping: $BACKUP_NAME"
    continue
  fi
  
  # Check if backup already has timestamp pattern (YYYY-MM-DD-HHhMM)
  if [[ ! "$BACKUP_NAME" =~ -[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}h[0-9]{2}$ ]]; then
    # Get modification time and create timestamp
    MTIME=$(stat -c %Y "$backup" 2>/dev/null || echo "0")
    if [[ "$MTIME" != "0" ]]; then
      TIMESTAMP=$(date -d "@${MTIME}" '+%Y-%m-%d-%Hh%M' 2>/dev/null || date '+%Y-%m-%d-%Hh%M')
      NEW_NAME="${BACKUP_NAME}-${TIMESTAMP}"
      NEW_PATH="${MOUNTPOINT}/${NEW_NAME}"
      
      log "Renaming: $BACKUP_NAME -> $NEW_NAME (age: ${AGE_SECONDS}s, size: ${BACKUP_SIZE} bytes)"
      if mv "$backup" "$NEW_PATH"; then
        RENAMED=$((RENAMED+1))
      else
        log "WARNING: Failed to rename $backup"
      fi
    fi
  fi
done < <(find "$MOUNTPOINT" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) -name 'Check_MK-*' -print0 2>/dev/null)

log "Renamed $RENAMED backup(s)"

# Find and delete backups older than retention period
DELETED=0
while IFS= read -r -d '' backup; do
  log "Deleting old backup: $backup"
  rm -rf "$backup" && DELETED=$((DELETED+1))
done < <(find "$MOUNTPOINT" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) -mtime +${RETENTION_DAYS} -print0 2>/dev/null)

log "Cleanup completed. Deleted $DELETED backup(s)."
EOFCLEANUP

  chmod 0755 "${cleanup_script}"
}

write_cleanup_units() {
  local site="$1" mountpoint="$2" retention_days="${3:-90}"
  local cleanup_script="/usr/local/sbin/checkmk_backup_cleanup_${site}.sh"
  local rename_script="/usr/local/sbin/checkmk_backup_rename_${site}.sh"
  local service_file="/etc/systemd/system/checkmk-backup-cleanup@${site}.service"
  local timer_file="/etc/systemd/system/checkmk-backup-cleanup@${site}.timer"
  local rename_service="/etc/systemd/system/checkmk-backup-rename@${site}.service"
  local rename_timer="/etc/systemd/system/checkmk-backup-rename@${site}.timer"
  
  # Create cleanup script (with rename logic)
  write_cleanup_script "${cleanup_script}" "${mountpoint}" "${retention_days}"
  
  # Create rename-only script for path monitoring
  log "Creating rename script: ${rename_script}"
  cat > "${rename_script}" <<'EOFRENAME'
#!/usr/bin/env bash
set -euo pipefail

MOUNTPOINT="${1:?missing mountpoint}"
LOGFILE="/var/log/checkmk-backup-rename.log"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGFILE"; }

if [[ ! -d "$MOUNTPOINT" ]]; then
  log "ERROR: Mountpoint not found: $MOUNTPOINT"
  exit 1
fi

# Rename backups without timestamp (only complete backups)
RENAMED=0
while IFS= read -r -d '' backup; do
  BACKUP_NAME="$(basename "$backup")"
  
  # Skip incomplete backups
  if [[ "$BACKUP_NAME" =~ -incomplete ]]; then
    continue
  fi
  
  # Check if backup is stable (not modified in last 2 minutes)
  LAST_MODIFIED=$(stat -c %Y "$backup" 2>/dev/null || echo "0")
  CURRENT_TIME=$(date +%s)
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  
  if [[ $AGE_SECONDS -lt 120 ]]; then
    log "Backup too recent (${AGE_SECONDS}s old), waiting for stability: $BACKUP_NAME"
    continue
  fi
  
  # Check backup size (must be > 100KB to be valid)
  if [[ -d "$backup" ]]; then
    BACKUP_SIZE=$(du -sb "$backup" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$backup" 2>/dev/null || echo "0")
  fi
  
  if [[ $BACKUP_SIZE -lt 102400 ]]; then
    log "Backup too small (${BACKUP_SIZE} bytes), might be incomplete: $BACKUP_NAME"
    continue
  fi
  
  # Check if backup already has timestamp pattern
  if [[ ! "$BACKUP_NAME" =~ -[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}h[0-9]{2}$ ]]; then
    TIMESTAMP=$(date '+%Y-%m-%d-%Hh%M')
    NEW_NAME="${BACKUP_NAME}-${TIMESTAMP}"
    NEW_PATH="${MOUNTPOINT}/${NEW_NAME}"
    
    log "Renaming: $BACKUP_NAME -> $NEW_NAME (age: ${AGE_SECONDS}s, size: ${BACKUP_SIZE} bytes)"
    if mv "$backup" "$NEW_PATH" 2>/dev/null; then
      RENAMED=$((RENAMED+1))
    else
      log "WARNING: Failed to rename or already renamed: $backup"
    fi
  fi
done < <(find "$MOUNTPOINT" -mindepth 1 -maxdepth 1 \( -type f -o -type d \) -name 'Check_MK-*' ! -name '*-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*' -print0 2>/dev/null)

[[ $RENAMED -gt 0 ]] && log "Renamed $RENAMED backup(s)" || log "No backups to rename"
EOFRENAME
  
  chmod 0755 "${rename_script}"
  
  log "Creating cleanup and rename systemd units for site: ${site}"
  
  # Cleanup service (daily)
  cat > "${service_file}" <<EOFSVC
[Unit]
Description=Cleanup old backups for Checkmk site ${site}

[Service]
Type=oneshot
ExecStart=${cleanup_script} ${mountpoint} ${retention_days}
EOFSVC

  # Cleanup timer (daily)
  cat > "${timer_file}" <<EOFTMR
[Unit]
Description=Daily cleanup timer for Checkmk site ${site} backups

[Timer]
OnCalendar=daily
OnBootSec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOFTMR

  # Rename service (triggered by timer)
  cat > "${rename_service}" <<EOFRENSVC
[Unit]
Description=Rename backup after creation for Checkmk site ${site}

[Service]
Type=oneshot
ExecStart=${rename_script} ${mountpoint}
EOFRENSVC

  # Timer unit (checks every minute)
  local rename_timer="/etc/systemd/system/checkmk-backup-rename@${site}.timer"
  cat > "${rename_timer}" <<EOFRENTMR
[Unit]
Description=Timer for backup rename for Checkmk site ${site}

[Timer]
OnCalendar=*:0/1
Persistent=true
Unit=checkmk-backup-rename@${site}.service

[Install]
WantedBy=timers.target
EOFRENTMR

  log "Cleanup and rename units created for site ${site}"
}

stop_unmount_disable() {
  local unit_name="$1" mountpoint="$2"
  systemctl stop "${unit_name}" >/dev/null 2>&1 || true
  systemctl disable "${unit_name}" >/dev/null 2>&1 || true
  if mount | grep -qF " on ${mountpoint} "; then
    fusermount3 -uz "${mountpoint}" || true
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

  # Ensure directory/file ownership for rclone config
  local config_dir
  config_dir="$(dirname "${rclone_config}")"
  if [[ -d "${config_dir}" ]]; then
    chown -R "${site_user}:${site_group}" "${config_dir}" || warn "Could not fix ownership of ${config_dir}"
    chmod 755 "${config_dir}" || true
    chown "${site_user}:${site_group}" "$(dirname "${config_dir}")" 2>/dev/null || true
    chmod 755 "$(dirname "${config_dir}")" 2>/dev/null || true
  fi
  if [[ -f "${rclone_config}" ]]; then
    chown "${site_user}:${site_group}" "${rclone_config}" || warn "Could not fix ownership of ${rclone_config}"
    chmod 600 "${rclone_config}" || true
  fi

  local remote_name bucket_name remote
  remote_name="$(prompt_default "Enter rclone remote name" "do")"
  bucket_name="$(prompt_default "Enter bucket name" "testmonbck")"
  remote="${remote_name}:${bucket_name}"
  
  ensure_remote_configured "${rclone_config}" "${remote}"

  local mp_default
  mp_default="$(default_external_mountpoint_for_site "${site}")"
  mountpoint="$(prompt_default "Enter EXTERNAL mountpoint path (absolute)" "${mp_default}")"
  mountpoint="$(normalize_abs_mountpoint "${mountpoint}")"
  assert_mountpoint_outside_site "${site_home}" "${mountpoint}"

  unit_name="$(prompt_default "Enter systemd unit name" "rclone-${site}-spaces.service")"
  unit_path="/etc/systemd/system/${unit_name}"

  local cache_dir log_file
  cache_dir="$(prompt_default "Enter rclone cache dir" "$(default_cache_dir_for_site "${site}")")"
  log_file="$(prompt_default "Enter rclone log file" "$(default_log_file_for_site "${site}")")"

  local vfs_cache_max_size vfs_cache_max_age dir_cache_time poll_interval timeout contimeout retries low_level_retries
  vfs_cache_max_size="$(prompt_default "VFS cache max size" "${DEFAULT_VFS_CACHE_MAX_SIZE}")"
  vfs_cache_max_age="$(prompt_default "VFS cache max age" "${DEFAULT_VFS_CACHE_MAX_AGE}")"
  dir_cache_time="$(prompt_default "Dir cache time" "${DEFAULT_DIR_CACHE_TIME}")"
  poll_interval="$(prompt_default "Poll interval" "${DEFAULT_POLL_INTERVAL}")"
  timeout="$(prompt_default "Network timeout" "${DEFAULT_TIMEOUT}")"
  contimeout="$(prompt_default "Connect timeout" "${DEFAULT_CONTIMEOUT}")"
  retries="$(prompt_default "Retries" "${DEFAULT_RETRIES}")"
  low_level_retries="$(prompt_default "Low-level retries" "${DEFAULT_LOW_LEVEL_RETRIES}")"

  log "Summary:"
  echo "  Site:          ${site}"
  echo "  Site home:     ${site_home}"
  echo "  Run as user:   ${site_user}:${site_group}"
  echo "  rclone config: ${rclone_config}"
  echo "  Remote:        ${remote}"
  echo "  Mountpoint:    ${mountpoint}"
  echo "  Cache dir:     ${cache_dir}"
  echo "  Log file:      ${log_file}"
  echo "  Unit:          ${unit_name}"
  echo

  install_rclone_stable
  ensure_fuse_allow_other

  # Create mountpoint directory
  mkdir -p "${mountpoint}"
  chown "${site_user}:${site_group}" "${mountpoint}"
  chmod 2775 "${mountpoint}" || true

  # Create cache dir
  mkdir -p "${cache_dir}"
  chown "${site_user}:${site_group}" "${cache_dir}"
  chmod 750 "${cache_dir}" || true

  # Create log file (and its parent if needed)
  mkdir -p "$(dirname "${log_file}")"
  touch "${log_file}"
  chown "${site_user}:${site_group}" "${log_file}"
  chmod 640 "${log_file}" || true

  local rclone_bin
  rclone_bin="$(command -v rclone)"
  [[ -x "${rclone_bin}" ]] || die "rclone binary not executable: ${rclone_bin}"

  # Replace any previous unit, then write new one
  stop_unmount_disable "${unit_name}" "${mountpoint}"
  write_unit "${unit_path}" "${unit_name}" "${site}" "${site_user}" "${site_group}" \
    "${rclone_config}" "${rclone_bin}" "${remote}" "${mountpoint}" \
    "${cache_dir}" "${log_file}" \
    "${vfs_cache_max_size}" "${vfs_cache_max_age}" "${dir_cache_time}" "${poll_interval}" \
    "${timeout}" "${contimeout}" "${retries}" "${low_level_retries}"

  systemctl daemon-reload
  systemctl enable --now "${unit_name}"

  log "Service status:"
  systemctl status "${unit_name}" --no-pager -l || true

  log "Mount check: waiting for mount to be ready..."
  local max_attempts=15
  local attempt=0
  local mounted=false
  
  while [[ $attempt -lt $max_attempts ]]; do
    if mount | grep -qF " on ${mountpoint} "; then
      mounted=true
      log "Mount verified successfully after $((attempt + 1)) attempts."
      break
    fi
    attempt=$((attempt + 1))
    log "Attempt ${attempt}/${max_attempts}: mount not yet ready, waiting..."
    sleep 2
  done
  
  if [[ "${mounted}" != "true" ]]; then
    warn "Mount not present after ${max_attempts} attempts (30 seconds). Checking logs..."
    systemctl status "${unit_name}" --no-pager -l || true
    echo ""
    log "Last 50 lines from journalctl:"
    journalctl -u "${unit_name}" -n 50 --no-pager || true
    die "Mount not present after service start."
  fi

  log "Smoke test as ${site_user}:"
  if su - "${site_user}" -c "cd '${mountpoint}' && ls -la . | head -n 20"; then
    log "Smoke test passed."
  else
    warn "Smoke test failed. Service may still be starting up."
  fi

  # Setup cleanup and rename monitoring
  log ""
  local setup_cleanup retention_days
  if confirm_default_no "Setup automatic backup cleanup?"; then
    retention_days="$(prompt_default "Retention days" "90")"
    log "Retention: ${retention_days} days"
    
    write_cleanup_units "${site}" "${mountpoint}" "$retention_days"
    systemctl daemon-reload
    systemctl enable --now "checkmk-backup-cleanup@${site}.timer"
    systemctl enable --now "checkmk-backup-rename@${site}.timer"
    log "Cleanup timer enabled for site ${site}"
    log "Backup rename timer enabled (checks every minute)"
  fi

  log "SETUP COMPLETE (always-on mount)."
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
      unit_name="$(prompt_default "Enter systemd unit name to remove" "rclone-monitoring-spaces.service")"
    fi

    unit_path="/etc/systemd/system/${unit_name}"

    # Try parse mountpoint from unit file (more reliable than ExecStart property)
    if [[ -f "${unit_path}" ]]; then
      mountpoint="$(awk '
        $1=="ExecStart=" {
          for (i=1; i<=NF; i++) {
            if ($i=="mount") { print $(i+2); exit }
          }
        }' "${unit_path}" 2>/dev/null || true)"
    else
      mountpoint=""
    fi

    if [[ -z "${mountpoint}" ]]; then
      warn "Could not parse mountpoint from unit file. Asking manually."
      mountpoint="$(prompt_default "Enter mountpoint path to unmount" "/mnt/checkmk-spaces/monitoring")"
    fi
    mountpoint="$(normalize_abs_mountpoint "${mountpoint}")"

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

    if confirm_default_no "Also remove mountpoint directory ${mountpoint}?"; then
      rm -rf "${mountpoint}" || warn "Failed to remove mountpoint directory."
    fi

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

  local cache_dir log_file
  cache_dir="$(prompt_default "Enter rclone cache dir to remove (optional)" "$(default_cache_dir_for_site "${site}")")"
  log_file="$(prompt_default "Enter rclone log file to remove (optional)" "$(default_log_file_for_site "${site}")")"

  log "Removing:"
  echo "  Site:       ${site}"
  echo "  Site home:  ${site_home}"
  echo "  Mountpoint: ${mountpoint}"
  echo "  Unit:       ${unit_name}"
  echo "  Cache dir:  ${cache_dir}"
  echo "  Log file:   ${log_file}"
  echo

  stop_unmount_disable "${unit_name}" "${mountpoint}"

  if [[ -f "${unit_path}" ]]; then
    rm -f "${unit_path}"
    log "Removed unit file: ${unit_path}"
  else
    warn "Unit file not found: ${unit_path}"
  fi

  systemctl daemon-reload

  if confirm_default_no "Also remove cache dir ${cache_dir}?"; then
    rm -rf "${cache_dir}" || warn "Failed to remove cache dir."
  fi

  if confirm_default_no "Also remove log file ${log_file}?"; then
    rm -f "${log_file}" || warn "Failed to remove log file."
  fi

  if confirm_default_no "Also remove mountpoint directory ${mountpoint}?"; then
    rm -rf "${mountpoint}" || warn "Failed to remove mountpoint directory."
  fi
  
  # Remove cleanup units if they exist
  local cleanup_timer="/etc/systemd/system/checkmk-backup-cleanup@${site}.timer"
  local cleanup_service="/etc/systemd/system/checkmk-backup-cleanup@${site}.service"
  local cleanup_script="/usr/local/sbin/checkmk_backup_cleanup_${site}.sh"
  local rename_timer="/etc/systemd/system/checkmk-backup-rename@${site}.timer"
  local rename_service="/etc/systemd/system/checkmk-backup-rename@${site}.service"
  local rename_script="/usr/local/sbin/checkmk_backup_rename_${site}.sh"
  
  if [[ -f "${cleanup_timer}" || -f "${cleanup_service}" ]]; then
    log "Removing cleanup timer and service..."
    systemctl stop "checkmk-backup-cleanup@${site}.timer" 2>/dev/null || true
    systemctl disable "checkmk-backup-cleanup@${site}.timer" 2>/dev/null || true
    rm -f "${cleanup_timer}" "${cleanup_service}" "${cleanup_script}"
  fi
  
  if [[ -f "${rename_timer}" || -f "${rename_service}" ]]; then
    log "Removing backup rename timer..."
    systemctl stop "checkmk-backup-rename@${site}.timer" 2>/dev/null || true
    systemctl disable "checkmk-backup-rename@${site}.timer" 2>/dev/null || true
    rm -f "${rename_timer}" "${rename_service}" "${rename_script}"
  fi
  
  systemctl daemon-reload

  log "REMOVE COMPLETE."
}

usage() {
  cat <<EOFU
Usage:
  $0 setup    # interactive setup (install rclone, fuse.conf, systemd unit, enable+start always-on mount)
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
