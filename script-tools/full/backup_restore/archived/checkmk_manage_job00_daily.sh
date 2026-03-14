#!/bin/bash
# checkmk_manage_job00_daily.sh
# Gestisce backup giornaliero compresso CheckMK (job00-complete)
# - Comprime da 362M a 1.2M usando tar --delete
# - Upload a cloud DigitalOcean Spaces
# - Retention: 90 backup (locale + cloud)
#
# Uso: ./checkmk_manage_job00_daily.sh

set -euo pipefail

# Configurazione
BACKUP_DIR="/var/backups/checkmk"
SITE="monitoring"
BACKUP_PATTERN="*job00-complete*"
RETENTION_LOCAL=90
RETENTION_CLOUD=90
TMP_DIR="/opt/checkmk-backup/tmp"
RCLONE_REMOTE="do:testmonbck"
RCLONE_PATH="checkmk-backups/job00-daily"

# Logging
LOG_FILE="/var/log/checkmk-backup-job00.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ ERROR: $*" | tee -a "$LOG_FILE" >&2
    exit 1
}

# Verifica dipendenze
command -v rclone >/dev/null 2>&1 || error "rclone not found"
command -v tar >/dev/null 2>&1 || error "tar not found"

log "============================================"
log "CheckMK Job00 Daily Backup Management"
log "============================================"

# Step 1: Trova backup job00-complete SENZA timestamp (ancora da processare)
log "📂 Searching for unprocessed job00-complete backup..."
BACKUP=$(find "$BACKUP_DIR" -maxdepth 1 -type d -name "*job00-complete" -not -name "*-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-*" | head -1)

if [[ -z "$BACKUP" ]]; then
    log "⚠️  No job00-complete backup found, exiting"
    exit 0
fi

BACKUP_NAME=$(basename "$BACKUP")
PARENT_DIR=$(dirname "$BACKUP")
SITE_TAR="$BACKUP/site-$SITE.tar.gz"

log "✅ Found: $BACKUP_NAME"

# Verifica se già compresso (ha timestamp)
if [[ "$BACKUP_NAME" =~ -[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{2}h[0-9]{2}$ ]]; then
    log "✅ Backup already processed (has timestamp), skipping compression"
    ALREADY_PROCESSED=true
else
    log "📦 Starting compression..."
    ALREADY_PROCESSED=false
    
    # Step 2: Comprimi backup usando tar --delete
    mkdir -p "$TMP_DIR"
    
    WORK_TAR="$TMP_DIR/site-$SITE.tar"
    WORK_TARGZ="$TMP_DIR/site-$SITE.tar.gz"
    
    cp "$SITE_TAR" "$WORK_TARGZ"
    
    # Decomprimi (non estrarre)
    log "  🔓 Decompressing..."
    gunzip -f "$WORK_TARGZ"
    
    # Lista directory da rimuovere (441M -> 1.2M)
    REMOVE_PATHS=(
        "monitoring/var/nagios"
        "monitoring/checkmk-tools"
        "monitoring/monitoring"
        "monitoring/var/check_mk/crashes"
        "monitoring/var/check_mk/rest_api"
        "monitoring/var/check_mk/precompiled_checks"
        "monitoring/var/check_mk/logwatch"
        "monitoring/var/check_mk/wato/snapshots"
        "monitoring/var/check_mk/wato/log"
        "monitoring/var/check_mk/inventory_archive"
        "monitoring/var/check_mk/background_jobs"
        "monitoring/var/tmp"
        "monitoring/tmp"
    )
    
    # Rimuovi directory dal tar (in-place)
    log "  ❌ Removing heavy components..."
    for path in "${REMOVE_PATHS[@]}"; do
        tar --delete -f "$WORK_TAR" "$path" 2>/dev/null || true
    done
    
    # Ricomprimi
    log "  🔐 Recompressing..."
    gzip -f "$WORK_TAR"
    
    # Calcola riduzione
    ORIGINAL_SIZE=$(du -h "$SITE_TAR" | cut -f1)
    COMPRESSED_SIZE=$(du -h "$WORK_TARGZ" | cut -f1)
    COMPRESSED_BYTES=$(du -b "$WORK_TARGZ" | cut -f1)
    ORIGINAL_BYTES=$(stat -c %s "$SITE_TAR")
    REDUCTION=$(( 100 - (COMPRESSED_BYTES * 100 / ORIGINAL_BYTES) ))
    
    log "  ✅ Compressed: $ORIGINAL_SIZE -> $COMPRESSED_SIZE (${REDUCTION}% reduction)"
    
    # Sostituisci file originale
    mv "$WORK_TARGZ" "$SITE_TAR"
    chown monitoring:monitoring "$SITE_TAR" 2>/dev/null || chown $SITE:$SITE "$SITE_TAR"
    chmod 600 "$SITE_TAR"
    
    # Rinomina con timestamp del backup (non ora corrente)
    BACKUP_MTIME=$(stat -c %Y "$BACKUP")
    TIMESTAMP=$(date -d @$BACKUP_MTIME +%Y-%m-%d-%Hh%M)
    NEW_NAME="${BACKUP_NAME}-${TIMESTAMP}"
    NEW_PATH="$BACKUP_DIR/$NEW_NAME"
    
    mv "$BACKUP" "$NEW_PATH"
    BACKUP="$NEW_PATH"
    BACKUP_NAME="$NEW_NAME"
    
    log "  ✅ Renamed to: $BACKUP_NAME"
fi

# Step 3: Upload a cloud
log "☁️  Uploading to cloud..."
if su - "$SITE" -c "rclone copy '$BACKUP' '$RCLONE_REMOTE/$RCLONE_PATH/$BACKUP_NAME/' --progress --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf" >> "$LOG_FILE" 2>&1; then
    log "✅ Upload completed"
else
    error "Upload failed"
fi

# Step 4: Retention locale (mantieni ultimi 90)
log "🗂️  Applying local retention (keep last $RETENTION_LOCAL)..."
BACKUPS_LOCAL=($(find "$BACKUP_DIR" -maxdepth 1 -type d -name "*job00-complete*" | sort -r))
if [[ ${#BACKUPS_LOCAL[@]} -gt $RETENTION_LOCAL ]]; then
    for ((i=$RETENTION_LOCAL; i<${#BACKUPS_LOCAL[@]}; i++)); do
        OLD_BACKUP="${BACKUPS_LOCAL[$i]}"
        log "  🗑️  Removing old backup: $(basename "$OLD_BACKUP")"
        rm -rf "$OLD_BACKUP"
    done
    log "✅ Local retention applied: removed $((${#BACKUPS_LOCAL[@]} - RETENTION_LOCAL)) old backups"
else
    log "✅ Local retention OK: ${#BACKUPS_LOCAL[@]} backups (max $RETENTION_LOCAL)"
fi

# Step 5: Retention cloud (mantieni ultimi 90)
log "☁️  Applying cloud retention (keep last $RETENTION_CLOUD)..."
BACKUPS_CLOUD=($(su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH/' --dirs-only --config=\$HOME/.config/rclone/rclone.conf" | sort -r))
if [[ ${#BACKUPS_CLOUD[@]} -gt $RETENTION_CLOUD ]]; then
    for ((i=$RETENTION_CLOUD; i<${#BACKUPS_CLOUD[@]}; i++)); do
        OLD_BACKUP_CLOUD="${BACKUPS_CLOUD[$i]}"
        log "  🗑️  Removing old cloud backup: $OLD_BACKUP_CLOUD"
        su - "$SITE" -c "rclone purge '$RCLONE_REMOTE/$RCLONE_PATH/$OLD_BACKUP_CLOUD' --config=\$HOME/.config/rclone/rclone.conf" >> "$LOG_FILE" 2>&1
    done
    log "✅ Cloud retention applied: removed $((${#BACKUPS_CLOUD[@]} - RETENTION_CLOUD)) old backups"
else
    log "✅ Cloud retention OK: ${#BACKUPS_CLOUD[@]} backups (max $RETENTION_CLOUD)"
fi

log "============================================"
log "✅ Job00 Daily Backup Management Completed"
log "============================================"
log "Backup: $BACKUP_NAME"
log "Local backups: ${#BACKUPS_LOCAL[@]}/$RETENTION_LOCAL"
log "Cloud backups: ${#BACKUPS_CLOUD[@]}/$RETENTION_CLOUD"
log "============================================"

exit 0
