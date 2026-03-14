#!/usr/bin/env bash
set -euo pipefail

# update-all-scripts.sh
# Aggiorna SOLO i file gia' presenti sul sistema, copiandoli dal repository.
# Non aggiunge nuovi file: se nel sistema un nome non esiste, non viene creato.
# Output semplice (ASCII-only).

VERSION="1.1.1"

REPO_DIR="${1:-/opt/checkmk-tools}"
BACKUP_DIR="/tmp/scripts-backup-$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${CHECKMK_AUTOHEAL_LOG_FILE:-/var/log/checkmk_server_autoheal.log}"
MAX_LOG_SIZE_BYTES="${CHECKMK_AUTOHEAL_LOG_MAX_BYTES:-10485760}"
UPDATED=0

log_size_bytes() {
    local file="$1"
    stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0
}

rotate_log_file() {
    [[ -f "$LOG_FILE" ]] || return 0

    local current_size
    current_size="$(log_size_bytes "$LOG_FILE")"
    [[ "$current_size" =~ ^[0-9]+$ ]] || current_size=0

    if (( current_size < MAX_LOG_SIZE_BYTES )); then
        return 0
    fi

    local rotated="${LOG_FILE}.1"
    local rotated_gz="${rotated}.gz"

    rm -f "$rotated_gz" 2>/dev/null || true
    mv "$LOG_FILE" "$rotated" 2>/dev/null || true
    gzip -f "$rotated" 2>/dev/null || true
    : > "$LOG_FILE"
    chmod 666 "$LOG_FILE" 2>/dev/null || true
}

write_log_line() {
    local level="$1"
    local message="$2"
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    rotate_log_file
    printf '[%s] [%s] %s\n' "$timestamp" "$level" "$message" >> "$LOG_FILE" 2>/dev/null || true
}

die() {
    echo "[ERR] $*" >&2
    write_log_line "ERROR" "$*"
    exit 1
}

log() {
    echo "[INFO] $*"
    write_log_line "INFO" "$*"
}

warn() {
    echo "[WARN] $*"
    write_log_line "WARN" "$*"
}

file_sha256() {
    local file="$1"
    sha256sum "$file" 2>/dev/null | awk '{print $1}'
}

extract_version() {
    local file="$1"
    local line value
    line="$(grep -E '^[[:space:]]*VERSION[[:space:]]*=' "$file" 2>/dev/null | head -n1 || true)"
    [[ -n "$line" ]] || return 0

    value="${line#*=}"
    value="$(printf '%s' "$value" | sed -E "s/^[[:space:]]+//; s/[[:space:]]+$//")"
    value="${value#\"}"
    value="${value#\'}"
    value="${value%%\"*}"
    value="${value%%\'*}"
    printf '%s' "$value"
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || die "eseguire come root (sudo)"
[[ -d "$REPO_DIR" ]] || die "repository non trovato: $REPO_DIR"
command -v git >/dev/null 2>&1 || die "git non trovato"

mkdir -p "$BACKUP_DIR"
touch "$LOG_FILE" 2>/dev/null || true
chmod 666 "$LOG_FILE" 2>/dev/null || true
log "update-all-scripts.sh v$VERSION"
log "Server autoheal log: $LOG_FILE"
log "Repository: $REPO_DIR"
log "Backup: $BACKUP_DIR"

log "Aggiorno repository (git pull)..."
cd "$REPO_DIR"
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "Modifiche locali rilevate: eseguo git stash"
    git stash push -m "Auto-stash $(date +%Y%m%d-%H%M%S)" >/dev/null 2>&1 || true
fi
git pull --rebase --autostash origin main >/dev/null 2>&1 || git pull origin main >/dev/null 2>&1 || true

resolve_src_dir() {
    local rel="$1"
    if [[ -d "$REPO_DIR/$rel" ]]; then
        printf '%s' "$REPO_DIR/$rel"
        return 0
    fi
    if [[ -d "$REPO_DIR/$rel/full" ]]; then
        printf '%s' "$REPO_DIR/$rel/full"
        return 0
    fi
    return 1
}

update_existing_files() {
    local repo_rel="$1"
    local system_dir="$2"
    local label="$3"
    local src_dir
    local count=0

    if ! src_dir="$(resolve_src_dir "$repo_rel")"; then
        warn "$label: cartella repo non trovata: $repo_rel"
        return 0
    fi
    if [[ ! -d "$system_dir" ]]; then
        warn "$label: cartella sistema non trovata: $system_dir"
        return 0
    fi

    log "$label: aggiorno file esistenti in $system_dir"
    shopt -s nullglob
    for dest in "$system_dir"/*; do
        local name owner mode backup_path src_hash dst_hash src_version dst_version
        local hash_changed version_changed reason
        name="$(basename "$dest")"

        [[ -f "$dest" ]] || continue
        [[ "$name" =~ ^\. ]] && continue
        [[ "$name" =~ \.(md|backup|bak|old|tmp|disabled)$ ]] && continue

        if [[ -f "$src_dir/$name" ]]; then
            src_hash="$(file_sha256 "$src_dir/$name" || true)"
            dst_hash="$(file_sha256 "$dest" || true)"
            src_version="$(extract_version "$src_dir/$name" || true)"
            dst_version="$(extract_version "$dest" || true)"

            hash_changed=0
            version_changed=0
            if [[ "$src_hash" != "$dst_hash" ]]; then
                hash_changed=1
            fi
            if [[ "$src_version" != "$dst_version" ]]; then
                version_changed=1
            fi

            if (( hash_changed == 0 && version_changed == 0 )); then
                continue
            fi

            reason=""
            if (( version_changed == 1 )); then
                reason="version ${dst_version:-n/a} -> ${src_version:-n/a}"
            fi
            if (( hash_changed == 1 )); then
                if [[ -n "$reason" ]]; then
                    reason="$reason, hash changed"
                else
                    reason="hash changed"
                fi
            fi

            owner="$(stat -c '%u:%g' "$dest" 2>/dev/null || echo "0:0")"
            mode="$(stat -c '%a' "$dest" 2>/dev/null || echo "755")"

            backup_path="$BACKUP_DIR/$label"
            mkdir -p "$backup_path"
            cp -a "$dest" "$backup_path/" 2>/dev/null || true

            cp -a "$src_dir/$name" "$dest"
            chown "$owner" "$dest" 2>/dev/null || true
            chmod "$mode" "$dest" 2>/dev/null || true
            log "  updated: $name ($reason)"
            ((count++))
        fi
    done

    if (( count > 0 )); then
        log "$label: aggiornati $count file"
        UPDATED=$((UPDATED + count))
    else
        warn "$label: nessun file da aggiornare"
    fi
}

# Destinazioni tipiche (se non esistono, vengono skippate)
update_existing_files "script-notify-checkmk" "/opt/omd/sites/monitoring/local/share/check_mk/notifications" "notifiche"
update_existing_files "script-check-ns7" "/usr/lib/check_mk_agent/plugins" "ns7-plugins"
update_existing_files "script-check-ns7" "/usr/lib/check_mk_agent/local" "ns7-local"
update_existing_files "script-check-ns8" "/usr/lib/check_mk_agent/plugins" "ns8-plugins"
update_existing_files "script-check-ns8" "/usr/lib/check_mk_agent/local" "ns8-local"
update_existing_files "script-check-ubuntu" "/usr/lib/check_mk_agent/plugins" "ubuntu-plugins"
update_existing_files "script-check-ubuntu" "/usr/lib/check_mk_agent/local" "ubuntu-local"
update_existing_files "script-check-proxmox" "/usr/lib/check_mk_agent/plugins" "proxmox-plugins"
update_existing_files "script-check-proxmox" "/usr/lib/check_mk_agent/local" "proxmox-local"
update_existing_files "script-tools/full" "/opt/omd/sites/monitoring/local/bin" "tools"
update_existing_files "Ydea-Toolkit" "/opt/ydea-toolkit" "ydea-toolkit"

log "Totale file aggiornati: $UPDATED"
log "Backup salvato in: $BACKUP_DIR"
log "Ripristino: cp -a $BACKUP_DIR/* /"
exit 0
