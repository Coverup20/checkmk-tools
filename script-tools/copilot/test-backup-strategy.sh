#!/usr/bin/env bash
set -euo pipefail

# test-backup-strategy.sh
# Test script per verificare la nuova strategia di retention
# Esegui sul server VPS per validare prima del deploy

log() { echo "[$(date '+%F %T')] $*"; }
err() { echo "[$(date '+%F %T')] ERROR: $*" >&2; }

BACKUP_DIR="${BACKUP_DIR:-/var/backups/checkmk}"
SITE="${SITE:-monitoring}"

log "=========================================="
log "TEST BACKUP STRATEGY - DRY RUN"
log "=========================================="
log ""
log "Backup directory: $BACKUP_DIR"
log "CheckMK site: $SITE"
log ""

# Check if backup directory exists
if [[ ! -d "$BACKUP_DIR" ]]; then
  err "Backup directory not found: $BACKUP_DIR"
  exit 1
fi

log "STEP 1: Lista backup esistenti"
log "=========================================="

# List all backups with timestamps
mapfile -t all_backups < <(
  { 
    find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type f \
      \( -name '*.tar.gz' -o -name '*.tgz' -o -name '*.tar' -o -name '*.mkbackup' -o -name '*.zip' \) \
      -printf '%T@ %TF %TT %p\n' 2>/dev/null
    find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d \
      -name 'Check_MK-*' -printf '%T@ %TF %TT %p\n' 2>/dev/null
  } | sort -nr
)

if [[ ${#all_backups[@]} -eq 0 ]]; then
  log "Nessun backup trovato in $BACKUP_DIR"
  exit 0
fi

log "Trovati ${#all_backups[@]} backup(s):"
log ""

total_size=0
for backup_info in "${all_backups[@]}"; do
  timestamp=$(echo "$backup_info" | awk '{print $2, $3}')
  backup_path=$(echo "$backup_info" | awk '{print $4}')
  backup_name=$(basename "$backup_path")
  
  # Calculate size
  if [[ -d "$backup_path" ]]; then
    size=$(du -sh "$backup_path" 2>/dev/null | awk '{print $1}')
    size_bytes=$(du -sb "$backup_path" 2>/dev/null | awk '{print $1}')
  else
    size=$(du -sh "$backup_path" 2>/dev/null | awk '{print $1}')
    size_bytes=$(stat -c %s "$backup_path" 2>/dev/null || echo "0")
  fi
  
  total_size=$((total_size + size_bytes))
  
  echo "  $timestamp | $size | $backup_name"
done

log ""
log "Spazio totale occupato: $(numfmt --to=iec-i --suffix=B $total_size 2>/dev/null || echo "${total_size} bytes")"
log ""

# Simulate RETENTION_DAYS_LOCAL=2 (dual-slot)
log "STEP 2: Simulazione RETENTION_DAYS_LOCAL=2 (dual-slot)"
log "=========================================="

RETENTION_LOCAL=2
kept_local=0
deleted_local=0
saved_space_local=0

log "Logica: mantieni solo i $RETENTION_LOCAL backup più recenti"
log ""

for backup_info in "${all_backups[@]}"; do
  kept_local=$((kept_local + 1))
  backup_path=$(echo "$backup_info" | awk '{print $4}')
  backup_name=$(basename "$backup_path")
  
  if [[ -d "$backup_path" ]]; then
    size_bytes=$(du -sb "$backup_path" 2>/dev/null | awk '{print $1}')
  else
    size_bytes=$(stat -c %s "$backup_path" 2>/dev/null || echo "0")
  fi
  
  if [[ $kept_local -gt $RETENTION_LOCAL ]]; then
    log "  ❌ DA ELIMINARE: $backup_name ($(numfmt --to=iec-i --suffix=B $size_bytes 2>/dev/null || echo "${size_bytes} bytes"))"
    deleted_local=$((deleted_local + 1))
    saved_space_local=$((saved_space_local + size_bytes))
  else
    log "  ✅ DA MANTENERE: $backup_name ($(numfmt --to=iec-i --suffix=B $size_bytes 2>/dev/null || echo "${size_bytes} bytes"))"
  fi
done

log ""
log "Risultato locale:"
log "  - Backup mantenuti: $RETENTION_LOCAL"
log "  - Backup eliminati: $deleted_local"
log "  - Spazio recuperato: $(numfmt --to=iec-i --suffix=B $saved_space_local 2>/dev/null || echo "${saved_space_local} bytes")"
log "  - Spazio rimanente: $(numfmt --to=iec-i --suffix=B $((total_size - saved_space_local)) 2>/dev/null || echo "$((total_size - saved_space_local)) bytes")"
log ""

# Check rclone configuration
log "STEP 3: Verifica configurazione rclone"
log "=========================================="

RCLONE_CONF="/opt/omd/sites/${SITE}/.config/rclone/rclone.conf"

if [[ -f "$RCLONE_CONF" ]]; then
  log "✅ Configurazione rclone trovata: $RCLONE_CONF"
  
  # Check if remote is configured
  if RCLONE_CONFIG="$RCLONE_CONF" rclone listremotes 2>/dev/null | grep -q '.'; then
    log "✅ Remote configurati:"
    RCLONE_CONFIG="$RCLONE_CONF" rclone listremotes 2>/dev/null | while read -r remote; do
      echo "     - $remote"
    done
  else
    log "⚠️  Nessun remote configurato"
  fi
else
  log "❌ Configurazione rclone non trovata: $RCLONE_CONF"
  log "   Esegui: ./checkmk_rclone_space_dyn.sh setup"
fi

log ""

# Check if script is installed
log "STEP 4: Verifica installazione script"
log "=========================================="

if [[ -f "/usr/local/sbin/checkmk_cloud_backup_push_run.sh" ]]; then
  log "✅ Wrapper script installato"
else
  log "❌ Wrapper script non trovato"
  log "   Esegui: ./checkmk_rclone_space_dyn.sh setup"
fi

if [[ -f "/etc/systemd/system/checkmk-cloud-backup-push@.service" ]]; then
  log "✅ Systemd service installato"
else
  log "❌ Systemd service non trovato"
  log "   Esegui: ./checkmk_rclone_space_dyn.sh setup"
fi

if [[ -f "/etc/default/checkmk-cloud-backup-push-${SITE}" ]]; then
  log "✅ File defaults trovato: /etc/default/checkmk-cloud-backup-push-${SITE}"
  log ""
  log "   Contenuto attuale:"
  grep -E '^(REMOTE|RETENTION)' "/etc/default/checkmk-cloud-backup-push-${SITE}" 2>/dev/null | sed 's/^/     /'
else
  log "⚠️  File defaults non trovato"
fi

log ""
log "=========================================="
log "TEST COMPLETATO"
log "=========================================="
log ""
log "📋 PROSSIMI PASSI:"
log ""
log "1. Se lo script non è installato:"
log "   sudo ./checkmk_rclone_space_dyn.sh setup"
log ""
log "2. Per aggiornare retention su installazione esistente:"
log "   sudo nano /etc/default/checkmk-cloud-backup-push-${SITE}"
log "   Modifica: RETENTION_DAYS_LOCAL=2"
log "   Modifica: RETENTION_DAYS_REMOTE=1"
log ""
log "3. Per testare manualmente:"
log "   sudo systemctl start checkmk-cloud-backup-push@${SITE}.service"
log "   sudo journalctl -u checkmk-cloud-backup-push@${SITE}.service -f"
log ""
log "4. Per abilitare backup automatico ogni minuto:"
log "   sudo systemctl enable --now checkmk-cloud-backup-push@${SITE}.timer"
log ""
log "⚠️  NOTA: La retention locale cancellerà $(( ${#all_backups[@]} - RETENTION_LOCAL )) backup"
log ""
