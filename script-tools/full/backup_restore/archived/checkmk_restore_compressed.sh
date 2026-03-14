#!/bin/bash
# checkmk_restore_compressed.sh
# Script per ripristino backup CheckMK compressi
# Gestisce automaticamente creazione directory e ownership post-restore
#
# Uso: ./checkmk_restore_compressed.sh <path_to_backup.tar.gz> [site_name]
#
# Esempio:
#   ./checkmk_restore_compressed.sh /var/backups/checkmk/restore-test/site-monitoring.tar.gz
#   ./checkmk_restore_compressed.sh /var/backups/checkmk/restore-test/site-monitoring.tar.gz monitoring

set -euo pipefail

# Funzione logging
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ ERROR: $*" >&2
    exit 1
}

# Verifica parametri
if [[ $# -lt 1 ]]; then
    error "Usage: $0 <backup_file.tar.gz> [site_name]"
fi

BACKUP_FILE="$1"
SITE_NAME="${2:-}"

# Verifica backup esiste
[[ ! -f "$BACKUP_FILE" ]] && error "Backup file not found: $BACKUP_FILE"

# Estrai nome site dal backup se non specificato
if [[ -z "$SITE_NAME" ]]; then
    SITE_NAME=$(tar tzf "$BACKUP_FILE" 2>/dev/null | head -1 | cut -d'/' -f1 || true)
    log "Site name detected: $SITE_NAME"
fi

SITE_DIR="/opt/omd/sites/$SITE_NAME"

log "============================================"
log "CheckMK Compressed Backup Restore"
log "============================================"
log "Backup file: $BACKUP_FILE"
log "Site name:   $SITE_NAME"
log "Site dir:    $SITE_DIR"
log "============================================"

# Step 1: Rimuovi site esistente se presente
if omd sites | grep -q "^$SITE_NAME "; then
    log "⚠️  Site '$SITE_NAME' exists, removing..."
    omd stop "$SITE_NAME" 2>/dev/null || true
    omd rm --kill "$SITE_NAME" || error "Failed to remove existing site"
    log "✅ Site removed"
fi

# Step 2: Restore backup
log "📦 Restoring backup..."
if ! omd restore "$BACKUP_FILE"; then
    error "omd restore failed"
fi
log "✅ Backup restored successfully"

# Step 3: Crea directory mancanti
log "📁 Creating missing directories..."

# Directory critiche che potrebbero mancare dopo restore compresso
REQUIRED_DIRS=(
    "$SITE_DIR/var/nagios"
    "$SITE_DIR/var/nagios/rrd"
    "$SITE_DIR/var/log/apache"
    "$SITE_DIR/var/log/nagios"
    "$SITE_DIR/var/log/agent-receiver"
    "$SITE_DIR/var/check_mk/crashes"
    "$SITE_DIR/var/check_mk/inventory_archive"
    "$SITE_DIR/var/check_mk/logwatch"
    "$SITE_DIR/var/check_mk/wato/snapshots"
    "$SITE_DIR/var/tmp"
    "$SITE_DIR/tmp"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [[ ! -d "$dir" ]]; then
        log "  Creating: $dir"
        mkdir -p "$dir"
    fi
done

log "✅ Directories created"

# Step 4: Correggi ownership ricorsivo
log "🔧 Fixing ownership and permissions..."

# Ownership ricorsivo su var/log
chown -R "$SITE_NAME:$SITE_NAME" "$SITE_DIR/var/log"

# Ownership su var/nagios
chown -R "$SITE_NAME:$SITE_NAME" "$SITE_DIR/var/nagios"

# Ownership su var/check_mk
chown -R "$SITE_NAME:$SITE_NAME" "$SITE_DIR/var/check_mk"

# Ownership su tmp
chown -R "$SITE_NAME:$SITE_NAME" "$SITE_DIR/var/tmp" "$SITE_DIR/tmp"

# Permessi directory log sensibili
chmod 750 "$SITE_DIR/var/log/apache"
chmod 755 "$SITE_DIR/var/log/nagios"
chmod 755 "$SITE_DIR/var/nagios"

log "✅ Ownership and permissions fixed"

# Step 5: Avvia site
log "🚀 Starting site '$SITE_NAME'..."
if ! omd start "$SITE_NAME"; then
    error "Failed to start site. Check logs in $SITE_DIR/var/log/"
fi

log "✅ Site started successfully"

# Step 6: Verifica status
log ""
log "============================================"
log "Site Status:"
log "============================================"
omd status "$SITE_NAME"

log ""
log "============================================"
log "✅ RESTORE COMPLETED SUCCESSFULLY"
log "============================================"
log "Site '$SITE_NAME' is ready at: http://$(hostname)/$SITE_NAME/"
log ""
log "Next steps:"
log "  - Verify services are running: omd status $SITE_NAME"
log "  - Check logs if needed: tail -f $SITE_DIR/var/log/*.log"
log "  - Access web interface and verify configuration"
log "============================================"

exit 0
