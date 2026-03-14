#!/bin/bash
set -euo pipefail

### SCRIPT COMPRESSIONE BACKUP NATIVI CHECKMK ###
# Prende backup nativi CheckMK e rimuove parti pesanti (RRD, inventory, agents)

BACKUP_DIR="/var/backups/checkmk"
SITE="${1:-monitoring}"
TMP_DIR="/opt/checkmk-backup/tmp"
LOCAL_BACKUP_DIR="/opt/checkmk-backup/compressed"
RCLONE_REMOTE="${RCLONE_REMOTE:-do:testmonbck}"
RCLONE_PATH="${RCLONE_PATH:-checkmk-backups/monitoring-compressed}"

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

### TROVA BACKUP "COMPLETE" (SENZA TIMESTAMP) ###
log "Cerco backup 'complete' in $BACKUP_DIR..."

COMPLETE_BACKUP=$(find "$BACKUP_DIR" -maxdepth 1 -type d -name "*-complete" -not -name "*-complete-*" | head -1)

if [[ -z "$COMPLETE_BACKUP" ]]; then
  warn "Nessun backup 'complete' trovato, cerco backup più recente con timestamp..."
  COMPLETE_BACKUP=$(find "$BACKUP_DIR" -maxdepth 1 -type d -name "Check_MK-*-complete-*" | sort -r | head -1)
  
  if [[ -z "$COMPLETE_BACKUP" ]]; then
    error "Nessun backup CheckMK trovato in $BACKUP_DIR"
    exit 1
  fi
  
  ALREADY_RENAMED=true
else
  ALREADY_RENAMED=false
fi

BACKUP_NAME=$(basename "$COMPLETE_BACKUP")
SITE_TAR="$COMPLETE_BACKUP/site-$SITE.tar.gz"

if [[ ! -f "$SITE_TAR" ]]; then
  error "File $SITE_TAR non trovato!"
  exit 1
fi

# Systemd unit disabilitata - nessun wait necessario
log "✅ Backup trovato, procedo con compressione"

ORIGINAL_SIZE=$(du -h "$SITE_TAR" | cut -f1)
log "✅ Backup trovato: $BACKUP_NAME"
log "   Dimensione originale: $ORIGINAL_SIZE"

### COPIA BACKUP PER MODIFICA IN-PLACE ###
log "Copio backup per modifica in-place..."

# Crea directory temporanea se non esiste
mkdir -p "$TMP_DIR"

WORK_TAR="$TMP_DIR/site-$SITE.tar"
WORK_TARGZ="$TMP_DIR/site-$SITE.tar.gz"

cp "$SITE_TAR" "$WORK_TARGZ"

### DECOMPRIMI (non estrarre) ###
log "Decomprimo tar.gz..."
gunzip -f "$WORK_TARGZ"

### RIMOZIONE PARTI PESANTI con tar --delete ###
log "Rimuovo componenti pesanti con tar --delete (preserva metadati)..."

# Lista directory da rimuovere (path assoluti nel tar: monitoring/...)
REMOVE_PATHS=(
  "monitoring/var/nagios"                          # Dati RRD Nagios (250MB)
  "monitoring/checkmk-tools"                       # Repository git locale (150MB)
  "monitoring/monitoring"                          # File binario non necessario (19MB)
  "monitoring/var/check_mk/crashes"                # Crash reports (13MB)
  "monitoring/var/check_mk/rest_api"               # Cache REST API (3.7MB)
  "monitoring/var/check_mk/precompiled_checks"     # Check precompilati (3.6MB)
  "monitoring/var/check_mk/logwatch"               # Log logwatch (1.9MB)
  "monitoring/var/check_mk/wato/snapshots"         # Snapshot WATO storici
  "monitoring/var/check_mk/wato/log"               # Log audit WATO
  "monitoring/var/check_mk/inventory_archive"      # Archivio inventory
  "monitoring/var/check_mk/background_jobs"        # Job background temporanei
  "monitoring/var/tmp"                             # File temporanei
  "monitoring/tmp"                                 # File temporanei
)

# Rimuovi directory dal tar (in-place)
for path in "${REMOVE_PATHS[@]}"; do
  log "  ❌ Rimuovo: $path"
  tar --delete -f "$WORK_TAR" "$path" 2>/dev/null || true
done

### RICOMPRIMI ###
log "Ricomprimo tar..."
gzip -f "$WORK_TAR"

### SOSTITUISCI FILE ORIGINALE ###
COMPRESSED_SIZE=$(du -h "$WORK_TARGZ" | cut -f1)
COMPRESSED_BYTES=$(du -b "$WORK_TARGZ" | cut -f1)
ORIGINAL_BYTES=$(stat -c %s "$SITE_TAR")

REDUCTION=$(( 100 - (COMPRESSED_BYTES * 100 / ORIGINAL_BYTES) ))
log "📊 Riduzione dimensione: ${REDUCTION}%"

log "Sostituisco file originale con versione compressa..."
mv "$WORK_TARGZ" "$SITE_TAR"
chown monitoring:monitoring "$SITE_TAR" 2>/dev/null || chown $SITE:$SITE "$SITE_TAR"
chmod 600 "$SITE_TAR"
log "✅ File sostituito: $SITE_TAR ($COMPRESSED_SIZE)"

### RINOMINA DIRECTORY CON TIMESTAMP ###
if [[ "$ALREADY_RENAMED" == "false" ]]; then
  TIMESTAMP=$(date +%Y-%m-%d-%Hh%M)
  NEW_NAME="${BACKUP_NAME}-${TIMESTAMP}"
  NEW_PATH="$BACKUP_DIR/$NEW_NAME"
  
  log "Rinomino directory con timestamp: $NEW_NAME"
  mv "$COMPLETE_BACKUP" "$NEW_PATH"
  
  COMPLETE_BACKUP="$NEW_PATH"
  BACKUP_NAME="$NEW_NAME"
  log "✅ Directory rinominata"
fi

### UPLOAD RCLONE ###
log "Upload su $RCLONE_REMOTE/$RCLONE_PATH/$BACKUP_NAME/..."

# Upload intera directory preservando nome
PARENT_DIR=$(dirname "$COMPLETE_BACKUP")
if su - "$SITE" -c "rclone copy '$PARENT_DIR/$BACKUP_NAME' '$RCLONE_REMOTE/$RCLONE_PATH/$BACKUP_NAME/' --progress --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf"; then
  log "✅ Upload completato"
  log "   - mkbackup.info"
  log "   - site-$SITE.tar.gz ($COMPRESSED_SIZE)"
else
  error "Upload fallito!"
  exit 1
fi

### RIEPILOGO ###
echo ""
log "=== RIEPILOGO ==="
log "Backup originale:    $ORIGINAL_SIZE"
log "Backup compresso:    $COMPRESSED_SIZE"
log "Riduzione:           ${REDUCTION}%"
log "Directory locale:    $COMPLETE_BACKUP/"
log "  - mkbackup.info"
log "  - site-$SITE.tar.gz"
log "Cloud:               $RCLONE_REMOTE/$RCLONE_PATH/$BACKUP_NAME/"
echo ""

exit 0
