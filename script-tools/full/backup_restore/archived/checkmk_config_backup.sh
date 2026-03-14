#!/bin/bash
set -euo pipefail

### CONFIGURAZIONE ###
# Auto-detect site se non specificato
if [[ -z "${1:-}" ]]; then
  # Rileva site disponibili
  if ! command -v omd >/dev/null 2>&1; then
    echo "ERRORE: comando 'omd' non trovato. CheckMK non installato?"
    exit 1
  fi
  
  # Ottieni prima riga che non è l'header (skippa linea con "SITE")
  SITE=$(omd sites 2>/dev/null | grep -v "^SITE" | head -1 | awk '{print $1}')
  
  if [[ -z "$SITE" ]]; then
    echo "ERRORE: Nessun site CheckMK trovato"
    echo ""
    echo "Lista site installati:"
    omd sites 2>/dev/null || echo "(comando omd sites fallito)"
    echo ""
    echo "Crea un site con: omd create <nome_site>"
    exit 1
  fi
  
  # Conta quanti site ci sono (escluso header)
  SITE_COUNT=$(omd sites 2>/dev/null | grep -v "^SITE" | wc -l)
  
  if [[ $SITE_COUNT -eq 1 ]]; then
    echo "[AUTO-DETECT] Rilevato site: $SITE"
  else
    echo "[AUTO-DETECT] Trovati $SITE_COUNT site, uso: $SITE"
    echo "Per usare altro site: $0 <site_name>"
  fi
else
  SITE="$1"
fi

SITE_BASE="/opt/omd/sites/$SITE"

BACKUP_BASE="/opt/checkmk-backup"
TMP_DIR="$BACKUP_BASE/tmp"
LOG_FILE="$BACKUP_BASE/backup-dr.log"

RCLONE_REMOTE="${RCLONE_REMOTE:-do:testmonbck}"
RCLONE_PATH="${RCLONE_PATH:-checkmk-backups/monitoring}"

RETENTION_DAYS="${RETENTION_DAYS:-30}"
INCLUDE_RRD="${INCLUDE_RRD:-false}"  # Set to 'true' per includere dati storici (molto pesante!)

DATE="$(date +%F_%H-%M-%S)"
ARCHIVE="checkmk-DR-${SITE}-${DATE}.tgz"
METADATA="checkmk-DR-${SITE}-${DATE}.metadata.txt"

### LOGGING ###
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

### CREAZIONE DIRECTORY ###
mkdir -p "$BACKUP_BASE" "$TMP_DIR"

### PRECHECK ###
log "=== INIZIO BACKUP DR per site $SITE ==="

if [[ ! -d "$SITE_BASE" ]]; then
  log "ERRORE: site $SITE non trovato in $SITE_BASE"
  exit 1
fi

command -v rclone >/dev/null || {
  log "ERRORE: rclone non installato"
  exit 1
}

# Verifica configurazione rclone
log "[INFO] Verifica configurazione rclone..."
if ! su - "$SITE" -c "rclone listremotes 2>/dev/null" | grep -q "^${RCLONE_REMOTE%%:*}:"; then
  log "ERRORE: Remote rclone '$RCLONE_REMOTE' non configurato per utente $SITE"
  log ""
  log "Configura rclone con:"
  log "  su - $SITE"
  log "  rclone config"
  log ""
  log "Oppure esporta remote esistente:"
  log "  export RCLONE_REMOTE=nome_remote:bucket"
  log ""
  log "Remote disponibili per utente $SITE:"
  su - "$SITE" -c "rclone listremotes 2>/dev/null" || log "  (nessuno configurato)"
  exit 1
fi
log "[OK] Remote rclone configurato: $RCLONE_REMOTE"

### RACCOLTA METADATI ###
log "[INFO] Raccolta metadati sistema"

cat > "$TMP_DIR/$METADATA" <<EOF
=== CHECKMK DISASTER RECOVERY BACKUP ===
Data backup: $(date)
Hostname: $(hostname -f)
Site: $SITE
CheckMK Version: $(cat "$SITE_BASE/version" 2>/dev/null || echo "N/A")
CheckMK Edition: $(grep -oP 'CMK_VERSION="\K[^"]+' "$SITE_BASE/.version" 2>/dev/null || echo "N/A")
OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)
Kernel: $(uname -r)
OMD Version: $(omd version 2>/dev/null || echo "N/A")
Python Version: $(su - "$SITE" -c "python3 --version" 2>/dev/null || echo "N/A")

=== SPAZIO DISCO ===
$(df -h "$SITE_BASE" | tail -1)

=== DIMENSIONI COMPONENTI ===
Site directory: $(du -sh "$SITE_BASE" 2>/dev/null | cut -f1)
Config (etc/): $(du -sh "$SITE_BASE/etc" 2>/dev/null | cut -f1)
Local extensions: $(du -sh "$SITE_BASE/local" 2>/dev/null | cut -f1)
Var data: $(du -sh "$SITE_BASE/var/check_mk" 2>/dev/null | cut -f1)

=== HOSTS MONITORATI ===
Host count: $(su - "$SITE" -c "cmk --list-hosts 2>/dev/null | wc -l" || echo "N/A")

=== SERVIZI ATTIVI ===
$(su - "$SITE" -c "omd status" 2>/dev/null || echo "N/A")
EOF

log "[OK] Metadati raccolti"

### BACKUP COMPLETO DR ###
log "[INFO] Creazione backup DR completo"

# Lista componenti da backuppare
BACKUP_ITEMS=(
  "etc/check_mk"                      # Configurazione hosts, regole, utenti
  "etc/omd"                           # Configurazione OMD/Apache
  "etc/apache"                        # Configurazione web server
  "etc/ssl"                           # Certificati SSL (se presenti)
  "etc/htpasswd"                      # Password utenti web
  "etc/auth.secret"                   # Chiave autenticazione
  "etc/auth.serials"                  # Seriali autenticazione
  "etc/environment"                   # Variabili ambiente site
  "var/check_mk/web"                  # Viste personalizzate utenti
  "var/check_mk/wato"                 # Snapshot configurazioni WATO
  "var/check_mk/agents"               # Agent bakery (agenti preconfezionati)
  "var/check_mk/packages"             # Pacchetti MKP installati
  "var/check_mk/inventory_archive"    # Archivio inventory HW/SW
  "local/share/check_mk/notifications" # Script notifica custom
  "local/lib/check_mk/notifications"  # Script notifica custom (alternativa)
  "local/share/check_mk/checks"      # Check plugin custom
  "local/share/check_mk/web/plugins" # Plugin web custom
  "local"                             # Altre estensioni e plugin custom
  "version"                           # Versione CheckMK installata
  ".version"                          # File versione dettagliato
)

# Aggiungi RRD solo se richiesto (backup molto pesante!)
if [[ "$INCLUDE_RRD" == "true" ]]; then
  log "[WARNING] Backup RRD abilitato - il backup sarà molto grande!"
  BACKUP_ITEMS+=("var/check_mk/rrd")  # Dati storici grafici
  BACKUP_ITEMS+=("var/pnp4nagios/perfdata") # Performance data (se presente)
fi

# Costruisci comando tar con solo elementi esistenti
TAR_ITEMS=()
for item in "${BACKUP_ITEMS[@]}"; do
  if [[ -e "$SITE_BASE/$item" ]]; then
    TAR_ITEMS+=("$item")
    log "  + Includo: $item"
  else
    log "  - Skip (non presente): $item"
  fi
done

# Crea archivio
tar czf "$TMP_DIR/$ARCHIVE" \
  -C "$SITE_BASE" \
  "${TAR_ITEMS[@]}" 2>&1 | tee -a "$LOG_FILE"

# Verifica integrità archivio
if tar tzf "$TMP_DIR/$ARCHIVE" >/dev/null 2>&1; then
  log "[OK] Archivio creato e verificato: $ARCHIVE"
else
  log "ERRORE: Archivio corrotto"
  exit 1
fi

# Calcola checksum
CHECKSUM=$(sha256sum "$TMP_DIR/$ARCHIVE" | awk '{print $1}')
log "[INFO] SHA256: $CHECKSUM"
echo -e "\n=== CHECKSUM ===\nSHA256: $CHECKSUM" >> "$TMP_DIR/$METADATA"

### BACKUP MKP (ESTENSIONI) ###
# Nota: già incluso in var/check_mk/packages ma creiamo lista esplicita
if [[ -d "$SITE_BASE/var/check_mk/packages" ]]; then
  MKP_COUNT=$(find "$SITE_BASE/var/check_mk/packages" -name "*.mkp" 2>/dev/null | wc -l)
  if [[ $MKP_COUNT -gt 0 ]]; then
    log "[INFO] Trovate $MKP_COUNT estensioni MKP installate"
    su - "$SITE" -c "mkp list" 2>/dev/null | tee -a "$LOG_FILE" || true
  fi
fi

### SALVATAGGIO CONFIGURAZIONE RESTORE ###
log "[INFO] Creo script istruzioni per restore"

cat > "$TMP_DIR/RESTORE_INSTRUCTIONS.txt" <<'RESTORE_EOF'
=== ISTRUZIONI DISASTER RECOVERY RESTORE ===

PREREQUISITI:
1. CheckMK stesso version installato come nell'originale
2. OMD site con stesso nome creato: omd create <SITE_NAME>
3. Site fermato: omd stop <SITE_NAME>

PROCEDURA RESTORE:

# 1. Ferma il site
omd stop <SITE_NAME>

# 2. Backup configurazione attuale (precauzione)
mv /opt/omd/sites/<SITE_NAME>/etc /opt/omd/sites/<SITE_NAME>/etc.OLD

# 3. Estrai backup DR
tar xzf checkmk-DR-<SITE_NAME>-<DATE>.tgz -C /opt/omd/sites/<SITE_NAME>/

# 4. Ripristina ownership corretti
chown -R <SITE_NAME>:<SITE_NAME> /opt/omd/sites/<SITE_NAME>

# 5. Verifica checksum (da file .metadata.txt)
sha256sum -c <<< "<CHECKSUM>  checkmk-DR-<SITE_NAME>-<DATE>.tgz"

# 6. Riavvia site
omd start <SITE_NAME>

# 7. Verifica servizi
omd status <SITE_NAME>

# 8. Ricompila configurazione monitoring
su - <SITE_NAME>
cmk -R
cmk -O

# 9. Test web interface
curl -k https://localhost/<SITE_NAME>/

# 10. REINSTALLA YDEA-TOOLKIT E CRONJOBS
# Gli script di notifica sono già ripristinati in local/, ma serve reinstallare:
# - Cronjobs (cleanup, auto-upgrade, monitoring)
# - Configurazione /opt/ydea-toolkit
# - File cache e log

# Reinstalla integrazione Ydea (include cronjobs health monitor)
export CHECKMK_SITE=<SITE_NAME>
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/Ydea-Toolkit/full/install-ydea-checkmk-integration.sh | bash

# Reinstalla cronjob cleanup CheckMK
(crontab -l 2>/dev/null; echo "# Cleanup Nagios & PNP4Nagios - ogni giorno alle 03:00"; echo "0 3 * * * curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash >> /var/log/cleanup-checkmk.log 2>&1") | crontab -

# Reinstalla cronjob auto-upgrade CheckMK (opzionale)
(crontab -l 2>/dev/null; echo "# Auto-upgrade CheckMK - domenica alle 02:00"; echo "0 2 * * 0 curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/upgrade_maintenance/upgrade-checkmk.sh | bash >> /var/log/checkmk-upgrade.log 2>&1") | crontab -

TROUBLESHOOTING:
- Permission errors: verificare owner con 'ls -la'
- Service non partono: controllare 'omd status' e log in var/log/
- Versione mismatch: installare stessa versione da file .metadata.txt
- Agent bakery: rigenerare agenti con 'cmk --bake-agents'
- Notifiche Ydea non funzionano: verificare credenziali in /opt/ydea-toolkit/.env

NOTE:
- I dati storici RRD NON sono inclusi per default (troppo grandi)
- Per backup completo con RRD: export INCLUDE_RRD=true prima del backup
- Le estensioni MKP potrebbero richiedere ricompilazione post-restore
- I cronjobs NON sono inclusi nel backup (gestiti via GitHub repository)
- Configurare credenziali Ydea in /opt/ydea-toolkit/.env dopo il restore
RESTORE_EOF

log "[OK] Istruzioni restore create"

### UPLOAD VIA RCLONE ###
log "[INFO] Upload su storage remoto: $RCLONE_REMOTE/$RCLONE_PATH"

su - "$SITE" -c "rclone copy '$TMP_DIR/$ARCHIVE' \
  '$RCLONE_REMOTE/$RCLONE_PATH' \
  --config='/opt/omd/sites/$SITE/.config/rclone/rclone.conf' \
  --checksum \
  --immutable \
  --transfers 2 \
  --s3-no-check-bucket \
  --log-level INFO" 2>&1 | tee -a "$LOG_FILE"

su - "$SITE" -c "rclone copy '$TMP_DIR/$METADATA' \
  '$RCLONE_REMOTE/$RCLONE_PATH' \
  --config='/opt/omd/sites/$SITE/.config/rclone/rclone.conf' \
  --checksum \
  --s3-no-check-bucket \
  --immutable" 2>&1 | tee -a "$LOG_FILE"

# Upload istruzioni restore
su - "$SITE" -c "rclone copy '$TMP_DIR/RESTORE_INSTRUCTIONS.txt' \
  '$RCLONE_REMOTE/$RCLONE_PATH' \
  --config='/opt/omd/sites/$SITE/.config/rclone/rclone.conf' \
  --checksum \
  --s3-no-check-bucket \
  --immutable" 2>&1 | tee -a "$LOG_FILE"

log "[OK] Upload completato"

### VERIFICA REMOTA ###
log "[INFO] Verifica presenza file remoto"
if su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH/$ARCHIVE'" >/dev/null 2>&1; then
  REMOTE_SIZE=$(su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH/$ARCHIVE' --format s")
  LOCAL_SIZE=$(stat -c%s "$TMP_DIR/$ARCHIVE")
  if [[ "$REMOTE_SIZE" -eq "$LOCAL_SIZE" ]]; then
    log "[OK] Verifica dimensione: OK (${LOCAL_SIZE} bytes)"
  else
    log "WARNING: Dimensione locale ($LOCAL_SIZE) != remota ($REMOTE_SIZE)"
  fi
else
  log "ERRORE: File non trovato su storage remoto"
  exit 1
fi

### RETENTION ###
log "[INFO] Applico retention ($RETENTION_DAYS giorni)"

# Calcola data limite
CUTOFF_DATE=$(date -d "$RETENTION_DAYS days ago" +%Y-%m-%d)

su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH' --format 'tp'" | while IFS=$'\t' read -r mtime path; do
  FILE_DATE=$(date -d "$mtime" +%Y-%m-%d 2>/dev/null || echo "9999-99-99")
  if [[ "$FILE_DATE" < "$CUTOFF_DATE" ]]; then
    log "  - Rimuovo file obsoleto: $path (data: $FILE_DATE)"
    su - "$SITE" -c "rclone delete '$RCLONE_REMOTE/$RCLONE_PATH/$path'" 2>&1 | tee -a "$LOG_FILE"
  fi
done

### CLEANUP LOCALE ###
rm -f "$TMP_DIR/$ARCHIVE" "$TMP_DIR/$METADATA" "$TMP_DIR/RESTORE_INSTRUCTIONS.txt"

log "=== BACKUP DR COMPLETATO CON SUCCESSO ==="
log "Archivio: $ARCHIVE"
log "Dimensione: $(numfmt --to=iec-i --suffix=B $LOCAL_SIZE 2>/dev/null || echo "$LOCAL_SIZE bytes")"
log "Checksum: $CHECKSUM"
log "Destinazione: $RCLONE_REMOTE/$RCLONE_PATH"
log "Include RRD: $INCLUDE_RRD"
log "Retention: $RETENTION_DAYS giorni"
log ""
log "Per restore: scaricare $ARCHIVE e seguire RESTORE_INSTRUCTIONS.txt"

exit 0
