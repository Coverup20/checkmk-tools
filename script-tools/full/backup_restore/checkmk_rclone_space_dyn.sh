#!/usr/bin/env bash
set -euo pipefail

# checkmk_cloud_backup_push.sh
VERSION="1.0.2"   # Versione script (aggiornare ad ogni modifica)
# Usage:
#   checkmk_cloud_backup_push.sh setup
#   checkmk_cloud_backup_push.sh run <site>
#   checkmk_cloud_backup_push.sh remove <site>
#
# Notes:
# - Designed for OMD/Checkmk sites under /opt/omd/sites/<site>
# - Pushes the newest backup archive file from local backup dir to rclone remote
# - Uses systemd templated service + optional timer

SCRIPT_NAME="$(basename "$0")"
SITES_BASE="/opt/omd/sites"
SYSTEMD_DIR="/etc/systemd/system"
WRAPPER_PATH="/usr/local/sbin/checkmk_cloud_backup_push_run.sh"

log() { echo "[$(date '+%F %T')] $*"; }
err() { echo "[$(date '+%F %T')] ERROR: $*" >&2; }
die() { err "$*"; exit 1; }
warn() { echo "WARN: $*" >&2; }

need_root() {
  [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run as root."
}

# Prompt functions
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

# Rclone remote management
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
    warn "Remote test 'rclone lsd ${remote_name}:' failed. Credentials may still be valid, but list may be blocked. You can verify with: RCLONE_CONFIG=${rclone_config} rclone ls ${remote_full}"
  else
    log "Remote test OK."
  fi
}

list_sites() {
  if [[ -d "$SITES_BASE" ]]; then
    find "$SITES_BASE" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
  else
    return 1
  fi
}

pick_site_interactive() {
  local sites
  mapfile -t sites < <(list_sites || true)
  [[ "${#sites[@]}" -gt 0 ]] || die "No OMD sites found in $SITES_BASE"

  log "Available OMD sites:"
  local i=1
  for s in "${sites[@]}"; do
    echo "  $i) $s"
    i=$((i+1))
  done

  local choice
  read -r -p "Select site number: " choice
  [[ "$choice" =~ ^[0-9]+$ ]] || die "Invalid selection."
  (( choice >= 1 && choice <= ${#sites[@]} )) || die "Out of range."
  echo "${sites[$((choice-1))]}"
}

write_wrapper() {
  cat > "$WRAPPER_PATH" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Wrapper invoked by systemd service:
#   checkmk_cloud_backup_push_run.sh <site> <remote> <remote_prefix> <backup_dir> <rclone_conf> <retries> <bwlimit> <retention_days_local> <retention_days_remote>

SITE="${1:?missing site}"
REMOTE="${2:?missing remote (e.g. do:bucket)}"
REMOTE_PREFIX="${3:?missing remote prefix (e.g. checkmk/site)}"
BACKUP_DIR="${4:?missing backup dir}"
RCLONE_CONF="${5:?missing rclone conf}"
RETRIES="${6:-3}"
BWLIMIT="${7:-0}"
RETENTION_DAYS_LOCAL="${8:-30}"
RETENTION_DAYS_REMOTE="${9:-90}"

log() { echo "[$(date '+%F %T')] $*"; }
err() { echo "[$(date '+%F %T')] ERROR: $*" >&2; }

SITEHOME="/opt/omd/sites/${SITE}"
LOCKFILE="/run/lock/checkmk-cloud-backup-push-${SITE}.lock"
LOGDIR="/var/log/checkmk-cloud-backup"
mkdir -p "$LOGDIR"

# Ensure we do not run concurrently for the same site
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  err "Another push is running for site=$SITE (lock: $LOCKFILE)."
  exit 2
fi

# Validate environment
[[ -d "$SITEHOME" ]] || { err "Site home not found: $SITEHOME"; exit 3; }
[[ -d "$BACKUP_DIR" ]] || { err "Backup dir not found: $BACKUP_DIR"; exit 4; }
[[ -r "$RCLONE_CONF" ]] || { err "rclone.conf not readable: $RCLONE_CONF"; exit 5; }

# Pick newest backup (file or directory) - search both and sort by timestamp
mapfile -t candidates < <(
  { 
    find "$BACKUP_DIR" -maxdepth 1 -type f \
      \( -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar' -o -name '*.mkbackup' -o -name '*.zip' \) \
      -printf '%T@ %p\n' 2>/dev/null
    find "$BACKUP_DIR" -maxdepth 1 -type d \
      -name 'Check_MK-*' -printf '%T@ %p\n' 2>/dev/null
  } | sort -nr
)

if [[ "${#candidates[@]}" -eq 0 ]]; then
  err "No backup archives or directories found in $BACKUP_DIR"
  exit 6
fi

NEWEST_PATH="$(echo "${candidates[0]}" | cut -d' ' -f2-)"
NEWEST_FILE="$(basename "$NEWEST_PATH")"

# Skip incomplete backups
if [[ "$NEWEST_FILE" =~ -incomplete ]]; then
  log "Skipping incomplete backup: $NEWEST_FILE"
  exit 0
fi

# Check if backup is stable (not modified in last 2 minutes)
if [[ -d "$NEWEST_PATH" || -f "$NEWEST_PATH" ]]; then
  LAST_MODIFIED=$(stat -c %Y "$NEWEST_PATH" 2>/dev/null || echo "0")
  CURRENT_TIME=$(date +%s)
  AGE_SECONDS=$((CURRENT_TIME - LAST_MODIFIED))
  
  if [[ $AGE_SECONDS -lt 120 ]]; then
    log "Backup too recent (${AGE_SECONDS}s old), waiting for stability: $NEWEST_FILE"
    exit 0
  fi
  
  # Check backup size (must be > 100KB to be valid)
  if [[ -d "$NEWEST_PATH" ]]; then
    BACKUP_SIZE=$(du -sb "$NEWEST_PATH" 2>/dev/null | awk '{print $1}')
  else
    BACKUP_SIZE=$(stat -c %s "$NEWEST_PATH" 2>/dev/null || echo "0")
  fi
  
  if [[ $BACKUP_SIZE -lt 102400 ]]; then
    log "Backup too small (${BACKUP_SIZE} bytes), might be incomplete: $NEWEST_FILE"
    exit 0
  fi
  
  log "Backup stable and valid (age: ${AGE_SECONDS}s, size: ${BACKUP_SIZE} bytes)"
fi

# Rename backup with timestamp if it doesn't have one
TIMESTAMP="$(date '+%Y-%m-%d-%Hh%M')"
TIMESTAMPED_NAME="${NEWEST_FILE}-${TIMESTAMP}"
TIMESTAMPED_PATH="${BACKUP_DIR}/${TIMESTAMPED_NAME}"

# Only rename if not already timestamped
if [[ "$NEWEST_FILE" != *"-"[0-9][0-9][0-9][0-9]"-"[0-9][0-9]"-"[0-9][0-9]"-"* ]]; then
  log "Renaming backup with timestamp: $NEWEST_FILE -> $TIMESTAMPED_NAME"
  if mv "$NEWEST_PATH" "$TIMESTAMPED_PATH"; then
    NEWEST_PATH="$TIMESTAMPED_PATH"
    NEWEST_FILE="$TIMESTAMPED_NAME"
    log "Backup renamed successfully"
  else
    err "Failed to rename backup, using original name"
  fi
else
  log "Backup already has timestamp: $NEWEST_FILE"
fi

DEST="${REMOTE%/}/${REMOTE_PREFIX%/}/"
[[ "$REMOTE_PREFIX" == "." || -z "$REMOTE_PREFIX" ]] && DEST="${REMOTE%/}/"

log "Selected backup: $NEWEST_PATH"
log "Destination: ${DEST}${SITE}/"
log "Using rclone config: $RCLONE_CONF"
log "Retries: $RETRIES"

# rclone options
COMMON_OPTS=(
  "--config=$RCLONE_CONF"
  "--log-file=${LOGDIR}/push-${SITE}.log"
  "--log-level=INFO"
  "--retries=$RETRIES"
  "--retries-sleep=10s"
  "--low-level-retries=10"
  "--stats=30s"
  "--stats-one-line"
  "--checksum"
)

if [[ "$BWLIMIT" != "0" ]]; then
  COMMON_OPTS+=("--bwlimit=$BWLIMIT")
fi

# Push backup (file or directory)
REMOTE_SITE_PATH="${DEST}${SITE}"

# Note: S3/Spaces don't support empty directories, paths are created automatically when uploading files
log "Remote destination: $REMOTE_SITE_PATH"

if [[ -d "$NEWEST_PATH" ]]; then
  # It's a directory - copy entire directory
  log "Copying directory to remote: ${REMOTE_SITE_PATH}/${NEWEST_FILE}/"
  rclone copy "$NEWEST_PATH/" "${REMOTE_SITE_PATH}/${NEWEST_FILE}/" "${COMMON_OPTS[@]}"
else
  # It's a file - use atomic copy with temp name
  TMP_NAME=".${NEWEST_FILE}.partial"
  REMOTE_TMP="${REMOTE_SITE_PATH}/${TMP_NAME}"
  REMOTE_FINAL="${REMOTE_SITE_PATH}/${NEWEST_FILE}"
  
  log "Copying file to remote temp: $REMOTE_TMP"
  rclone copyto "$NEWEST_PATH" "$REMOTE_TMP" "${COMMON_OPTS[@]}"
  
  log "Moving to final name: $REMOTE_FINAL"
  rclone moveto "$REMOTE_TMP" "$REMOTE_FINAL" "${COMMON_OPTS[@]}" || {
    err "Move failed, cleaning up temp"
    rclone delete "$REMOTE_TMP" "${COMMON_OPTS[@]}" 2>/dev/null || true
    exit 7
  }
fi

log "Push completed successfully."

# Cleanup old local backups - DUAL-SLOT logic (keep only 2 most recent)
if [[ "$RETENTION_DAYS_LOCAL" -gt 0 ]]; then
  log "Cleaning up local backups (keeping only ${RETENTION_DAYS_LOCAL} most recent)..."
  
  # List all backups sorted by modification time (newest first)
  mapfile -t all_backups < <(
    { 
      find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type f \
        \( -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar' -o -name '*.mkbackup' -o -name '*.zip' \) \
        -printf '%T@ %p\n' 2>/dev/null
      find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
        -name 'Check_MK-*' -printf '%T@ %p\n' 2>/dev/null
    } | sort -nr | cut -d' ' -f2-
  )
  
  # Keep only the N most recent (RETENTION_DAYS_LOCAL = number to keep)
  kept=0
  for backup in "${all_backups[@]}"; do
    kept=$((kept + 1))
    if [[ $kept -gt $RETENTION_DAYS_LOCAL ]]; then
      log "Removing old local backup: $(basename "$backup")"
      rm -rf "$backup" 2>/dev/null || true
    else
      log "Keeping local backup: $(basename "$backup")"
    fi
  done
  
  log "Local cleanup completed (${kept} backup(s) remaining)."
fi

# Cleanup old remote backups - SIMPLIFIED logic (keep only RETENTION_DAYS_REMOTE most recent)
if [[ "$RETENTION_DAYS_REMOTE" -gt 0 ]]; then
  log "Cleaning up remote backups (keeping only ${RETENTION_DAYS_REMOTE} most recent)..."
  
  # List all directories and archives (exclude metadata/info files)
  mapfile -t all_backups < <(
    rclone lsf "$REMOTE_SITE_PATH" --dirs-only "${COMMON_OPTS[@]}" 2>/dev/null || true
    rclone lsf "$REMOTE_SITE_PATH" --files-only "${COMMON_OPTS[@]}" 2>/dev/null | grep -E '\.(tgz|tar\.gz|tar|zip)$' || true
  )
  
  if [[ ${#all_backups[@]} -eq 0 ]]; then
    log "No remote backups found (this might be the first upload)."
  else
    # Sort by date extracted from filename (newest first)
    # Note: sort -r on full name is wrong when job01 < job00 alphabetically but job00 is newer by date
    mapfile -t sorted_backups < <(
      printf '%s\n' "${all_backups[@]}" | \
        sed 's/.*\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}-[0-9]\{2\}h[0-9]\{2\}\).*/\1 &/' | \
        sort -r | \
        cut -d' ' -f2-
    )
    
    # Keep only N most recent
    kept=0
    for backup in "${sorted_backups[@]}"; do
      kept=$((kept + 1))
      
      if [[ $kept -gt $RETENTION_DAYS_REMOTE ]]; then
        log "Deleting old remote backup: $backup"
        if [[ "$backup" == */ ]]; then
          # It's a directory - purge it
          rclone purge "${REMOTE_SITE_PATH}/${backup%/}" "${COMMON_OPTS[@]}" 2>/dev/null || true
        else
          # It's a file - delete it
          rclone delete "${REMOTE_SITE_PATH}/${backup}" "${COMMON_OPTS[@]}" 2>/dev/null || true
        fi
      else
        log "Keeping remote backup: $backup"
      fi
    done
    
    log "Remote cleanup completed (${kept} backup(s) checked)."
  fi
fi

log "All operations completed."
EOF

  chmod 0755 "$WRAPPER_PATH"
}

write_systemd_units() {
  # Service template
  cat > "${SYSTEMD_DIR}/checkmk-cloud-backup-push@.service" <<'EOF'
[Unit]
Description=Checkmk Cloud Backup Push (rclone) for site %i
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=root
Group=root

# Defaults can be overridden via:
#   /etc/default/checkmk-cloud-backup-push-%i
EnvironmentFile=-/etc/default/checkmk-cloud-backup-push-%i

# Sensible defaults
Environment=REMOTE=do:testmonbck
Environment=REMOTE_PREFIX=checkmk-backups
Environment=BACKUP_DIR=/var/backups/checkmk
Environment=RCLONE_CONF=/opt/omd/sites/%i/.config/rclone/rclone.conf
Environment=RETRIES=3
Environment=BWLIMIT=0
Environment=RETENTION_DAYS_LOCAL=2
Environment=RETENTION_DAYS_REMOTE=1

ExecStart=/usr/local/sbin/checkmk_cloud_backup_push_run.sh %i "${REMOTE}" "${REMOTE_PREFIX}" "${BACKUP_DIR}" "${RCLONE_CONF}" "${RETRIES}" "${BWLIMIT}" "${RETENTION_DAYS_LOCAL}" "${RETENTION_DAYS_REMOTE}"

TimeoutStartSec=0
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7

[Install]
WantedBy=multi-user.target
EOF

  # Path unit for monitoring backup directory
  cat > "${SYSTEMD_DIR}/checkmk-cloud-backup-push@.path" <<'EOF'
[Unit]
Description=Monitor backup directory for Checkmk site %i

[Path]
# Monitor the backup directory for modifications
PathModified=/var/backups/checkmk
# Check every minute after a change is detected
TriggerLimitIntervalSec=1m
TriggerLimitBurst=5
Unit=checkmk-cloud-backup-push@%i.service

[Install]
WantedBy=multi-user.target
EOF

  # Optional timer template (active polling every minute)
  cat > "${SYSTEMD_DIR}/checkmk-cloud-backup-push@.timer" <<'EOF'
[Unit]
Description=Timer for Checkmk Cloud Backup Push (rclone) for site %i

[Timer]
# Check every minute for new backups
OnCalendar=*:0/1
Persistent=true
Unit=checkmk-cloud-backup-push@%i.service

[Install]
WantedBy=timers.target
EOF
}

write_defaults_file() {
  local site="$1"
  local remote="${2:-do:testmonbck}"
  local retention_local="${3:-30}"
  local retention_remote="${4:-90}"
  local remote_prefix="${5:-checkmk-backups}"
  local defaults="/etc/default/checkmk-cloud-backup-push-${site}"
  if [[ -f "$defaults" ]]; then
    log "Defaults file already exists: $defaults (not overwriting)"
    return 0
  fi

  cat > "$defaults" <<EOF
# Overrides for site ${site}
# Example:
# REMOTE=do:testmonbck
# REMOTE_PREFIX=checkmk-backups  # Cartella nel bucket (scelta in fase di installazione)
# BACKUP_DIR=/var/backups/checkmk
# RCLONE_CONF=/opt/omd/sites/${site}/.config/rclone/rclone.conf
# RETRIES=3
# BWLIMIT=0
# RETENTION_DAYS_LOCAL=2   # Number of backups to keep locally (dual-slot)
# RETENTION_DAYS_REMOTE=1   # Number of backups to keep on cloud (single backup)

REMOTE=${remote}
REMOTE_PREFIX=${remote_prefix}
BACKUP_DIR=/var/backups/checkmk
RCLONE_CONF=/opt/omd/sites/${site}/.config/rclone/rclone.conf
RETRIES=3
BWLIMIT=0
RETENTION_DAYS_LOCAL=${retention_local}
RETENTION_DAYS_REMOTE=${retention_remote}
EOF

  chmod 0644 "$defaults"
  log "Created defaults file: $defaults"
}

check_dependencies() {
  log "Checking system dependencies..."
  
  local missing=()
  
  # Check for systemd (required for service management)
  if ! command -v systemctl >/dev/null 2>&1; then
    missing+=("systemd")
  fi
  
  # Check for curl (needed for rclone installation)
  if ! command -v curl >/dev/null 2>&1; then
    missing+=("curl")
  fi
  
  # Check for coreutils (du, awk are part of base system)
  if ! command -v du >/dev/null 2>&1; then
    missing+=("coreutils")
  fi
  
  if ! command -v awk >/dev/null 2>&1; then
    missing+=("gawk")
  fi
  
  # If critical dependencies are missing, try to install them
  if [[ ${#missing[@]} -gt 0 ]]; then
    log "Missing dependencies: ${missing[*]}"
    log "Attempting to install missing packages..."
    
    # Detect package manager and install
    if command -v apt-get >/dev/null 2>&1; then
      apt-get update -qq
      for pkg in "${missing[@]}"; do
        log "Installing $pkg via apt..."
        apt-get install -y "$pkg" || warn "Failed to install $pkg"
      done
    elif command -v yum >/dev/null 2>&1; then
      for pkg in "${missing[@]}"; do
        log "Installing $pkg via yum..."
        yum install -y "$pkg" || warn "Failed to install $pkg"
      done
    elif command -v dnf >/dev/null 2>&1; then
      for pkg in "${missing[@]}"; do
        log "Installing $pkg via dnf..."
        dnf install -y "$pkg" || warn "Failed to install $pkg"
      done
    else
      die "No supported package manager found (apt/yum/dnf). Please install manually: ${missing[*]}"
    fi
    
    # Verify all critical dependencies are now available
    local still_missing=()
    for pkg in "${missing[@]}"; do
      local cmd="$pkg"
      [[ "$pkg" == "gawk" ]] && cmd="awk"
      [[ "$pkg" == "coreutils" ]] && cmd="du"
      if ! command -v "$cmd" >/dev/null 2>&1; then
        still_missing+=("$pkg")
      fi
    done
    
    if [[ ${#still_missing[@]} -gt 0 ]]; then
      die "Failed to install required dependencies: ${still_missing[*]}"
    fi
    
    log "All dependencies installed successfully"
  else
    log "All system dependencies are present"
  fi
}

setup() {
  need_root
  
  # Check and install system dependencies first
  check_dependencies
  
  # Check if rclone is installed, if not install it
  if ! command -v rclone >/dev/null 2>&1; then
    log "rclone not found. Installing rclone..."
    
    # Try to install rclone using official script
    if curl -fsSL https://rclone.org/install.sh | bash; then
      log "rclone installed successfully"
    else
      die "Failed to install rclone automatically. Please install manually: curl https://rclone.org/install.sh | sudo bash"
    fi
    
    # Verify installation
    if ! command -v rclone >/dev/null 2>&1; then
      die "rclone installation completed but command not found. Please check your PATH or reopen terminal."
    fi
  else
    log "rclone is already installed ($(rclone version | head -1))"
  fi
  
  # Get list of sites
  local sites
  mapfile -t sites < <(list_sites || true)
  
  if [[ "${#sites[@]}" -eq 0 ]]; then
    die "No OMD sites found in $SITES_BASE"
  fi
  
  log "Discovered sites: ${sites[*]}"
  
  # Configure rclone for each site
  for site in "${sites[@]}"; do
    local rclone_config="/opt/omd/sites/${site}/.config/rclone/rclone.conf"
    local config_dir="$(dirname "$rclone_config")"
    
    # Create rclone config directory if missing
    if [[ ! -d "$config_dir" ]]; then
      log "Creating rclone config directory for site ${site}"
      mkdir -p "$config_dir"
      chown "${site}:${site}" "$config_dir"
      chmod 700 "$config_dir"
    fi
    
    # Create empty config if missing
    if [[ ! -f "$rclone_config" ]]; then
      log "Creating empty rclone config for site ${site}"
      touch "$rclone_config"
      chown "${site}:${site}" "$rclone_config"
      chmod 600 "$rclone_config"
    fi
    
    # Fix permissions if needed
    if [[ -f "$rclone_config" ]]; then
      chown "${site}:${site}" "$rclone_config" 2>/dev/null || true
      chmod 600 "$rclone_config" 2>/dev/null || true
    fi
    
    # Also ensure parent directory has correct ownership
    chown -R "${site}:${site}" "$config_dir" 2>/dev/null || true
    
    log ""
    log "Configuring rclone remote for site: ${site}"
    log "Config file: $rclone_config"
    
    # Ask for remote configuration (only once, use for all sites)
    if [[ -z "${CONFIGURED_REMOTE_NAME:-}" ]]; then
      CONFIGURED_REMOTE_NAME="$(prompt_default "Enter rclone remote name" "do")"
      CONFIGURED_BUCKET="$(prompt_default "Enter bucket name" "testmonbck")"
      CONFIGURED_REMOTE="${CONFIGURED_REMOTE_NAME}:${CONFIGURED_BUCKET}"
    fi
    
    ensure_remote_configured "$rclone_config" "$CONFIGURED_REMOTE"
    
    # Fix permissions again after rclone config create (which runs as root)
    chown -R "${site}:${site}" "$config_dir" 2>/dev/null || true
    chmod 700 "$config_dir" 2>/dev/null || true
    chmod 600 "$rclone_config" 2>/dev/null || true
    
    log "✓ Rclone configured for site ${site}"
  done
  
  log ""
  log "Installing systemd units and wrapper..."
  
  write_wrapper
  write_systemd_units
  systemctl daemon-reload
  
  # Create backup directory if it doesn't exist
  if [[ ! -d "/var/backups/checkmk" ]]; then
    log "Creating backup directory: /var/backups/checkmk"
    mkdir -p /var/backups/checkmk
    chmod 755 /var/backups/checkmk
  fi
  
  log "Installed:"
  log "  - $WRAPPER_PATH"
  log "  - ${SYSTEMD_DIR}/checkmk-cloud-backup-push@.service"
  log "  - ${SYSTEMD_DIR}/checkmk-cloud-backup-push@.path (auto-monitor)"
  log "  - ${SYSTEMD_DIR}/checkmk-cloud-backup-push@.timer (scheduled)"
  log "  - /var/backups/checkmk (backup directory)"
  log ""
  
  # Ask for retention settings
  log "Backup retention settings (number of backups to keep):"
  local retention_local retention_remote
  retention_local="$(prompt_default "Local retention (number of backups, recommended: 2 for dual-slot)" "2")"
  retention_remote="$(prompt_default "Remote retention (number of backups, recommended: 1 for single full)" "1")"
  local remote_prefix
  remote_prefix="$(prompt_default "Remote folder name (cartella nel bucket)" "checkmk-backups")"
  log "Local retention: ${retention_local} backup(s)"
  log "Remote retention: ${retention_remote} backup(s)"
  log ""
  
  # Auto-enable monitoring for all discovered sites
  local sites
  mapfile -t sites < <(list_sites || true)
  
  if [[ "${#sites[@]}" -gt 0 ]]; then
    log "Auto-enabling backup monitoring for discovered sites:"
    for site in "${sites[@]}"; do
      write_defaults_file "$site" "${CONFIGURED_REMOTE:-do:testmonbck}" "$retention_local" "$retention_remote" "$remote_prefix"
      
      # Set correct ownership for the site user
      if id "$site" &>/dev/null; then
        chown -R "${site}:${site}" /var/backups/checkmk 2>/dev/null || true
      fi
      
      systemctl enable --now "checkmk-cloud-backup-push@${site}.timer" 2>/dev/null || true
      log "  ✓ ${site} - monitoring /var/backups/checkmk (checking every minute)"
    done
    log ""
    log "Backup monitoring is now active. Script checks every minute for new backups."
    log "When a complete backup is found, it will be pushed after 2-minute stability check."
  else
    log "No OMD sites found. You can manually enable monitoring later with:"
    log "  systemctl enable --now checkmk-cloud-backup-push@<site>.timer"
  fi
  
  log ""
  log "Manual commands:"
  log "  Push now:    $SCRIPT_NAME run <site>"
  log "  Remove:      $SCRIPT_NAME remove <site>"
}

run_site() {
  need_root
  local site="${1:-}"
  [[ -n "$site" ]] || site="$(pick_site_interactive)"
  [[ -d "${SITES_BASE}/${site}" ]] || die "Site not found: ${site}"

  write_defaults_file "$site"
  
  # Set correct ownership for the site user
  if id "$site" &>/dev/null; then
    chown -R "${site}:${site}" /var/backups/checkmk 2>/dev/null || true
  fi

  log "Starting push service for site=${site}"
  systemctl start "checkmk-cloud-backup-push@${site}.service"
  
  log "Enabling active monitoring (timer every minute) for site=${site}"
  systemctl enable --now "checkmk-cloud-backup-push@${site}.timer"
  
  log "Done. Active monitoring enabled - checking every minute for new backups"
  log "Check logs:"
  log "  journalctl -u checkmk-cloud-backup-push@${site}.service --no-pager -n 200"
  log "  /var/log/checkmk-cloud-backup/push-${site}.log"
  log ""
  log "Path monitoring status:"
  systemctl status "checkmk-cloud-backup-push@${site}.path" --no-pager -l || true
}

remove_site() {
  need_root
  local site="${1:-}"
  [[ -n "$site" ]] || site="$(pick_site_interactive)"

  # Stop/disable path and timer if present
  systemctl disable --now "checkmk-cloud-backup-push@${site}.path" >/dev/null 2>&1 || true
  systemctl disable --now "checkmk-cloud-backup-push@${site}.timer" >/dev/null 2>&1 || true
  systemctl stop "checkmk-cloud-backup-push@${site}.service" >/dev/null 2>&1 || true

  rm -f "/etc/default/checkmk-cloud-backup-push-${site}"
  log "Removed defaults: /etc/default/checkmk-cloud-backup-push-${site}"

  log "Units remain installed (shared templates). If you want full uninstall, remove:"
  log "  ${SYSTEMD_DIR}/checkmk-cloud-backup-push@.service"
  log "  ${SYSTEMD_DIR}/checkmk-cloud-backup-push@.path"
  log "  ${SYSTEMD_DIR}/checkmk-cloud-backup-push@.timer"
  log "  ${WRAPPER_PATH}"
  log "then: systemctl daemon-reload"
}

usage() {
  cat <<EOF
Usage:
  $SCRIPT_NAME setup
  $SCRIPT_NAME run <site>
  $SCRIPT_NAME remove <site>

Examples:
  # Initial setup (install templates)
  $SCRIPT_NAME setup

  # Manual push of newest backup
  $SCRIPT_NAME run monitoring

  # Auto-monitor mode: push when new backup detected (5min after completion)
  systemctl enable --now checkmk-cloud-backup-push@monitoring.path

  # Scheduled mode: push daily at 02:30
  systemctl enable --now checkmk-cloud-backup-push@monitoring.timer

Configuration:
  /etc/default/checkmk-cloud-backup-push-<site>
EOF
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    setup) setup ;;
    run) shift; run_site "${1:-}" ;;
    remove) shift; remove_site "${1:-}" ;;
    -h|--help|help|"") usage ;;
    *) die "Unknown command: $cmd" ;;
  esac
}

main "$@"
