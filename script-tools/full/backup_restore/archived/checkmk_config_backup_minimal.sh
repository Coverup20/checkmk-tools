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
LOG_FILE="$BACKUP_BASE/backup-minimal.log"

RCLONE_REMOTE="${RCLONE_REMOTE:-do:testmonbck}"
RCLONE_PATH="${RCLONE_PATH:-checkmk-backups/monitoring-minimal}"

RETENTION_DAYS="${RETENTION_DAYS:-30}"

DATE="$(date +%F_%H-%M-%S)"
ARCHIVE="checkmk-MINIMAL-${SITE}-${DATE}.tgz"
METADATA="checkmk-MINIMAL-${SITE}-${DATE}.metadata.txt"

### LOGGING ###
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

### CREAZIONE DIRECTORY ###
mkdir -p "$BACKUP_BASE" "$TMP_DIR"

### PRECHECK ###
log "=== INIZIO BACKUP MINIMALE per site $SITE ==="
log "[INFO] Backup SOLO configurazione essenziale (no dati storici)"

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
=== CHECKMK BACKUP MINIMALE (SOLO CONFIG) ===
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

=== DIMENSIONI PRE-BACKUP ===
Config (etc/): $(du -sh "$SITE_BASE/etc" 2>/dev/null | cut -f1)
WATO snapshots: $(du -sh "$SITE_BASE/var/check_mk/wato" 2>/dev/null | cut -f1)
Web views: $(du -sh "$SITE_BASE/var/check_mk/web" 2>/dev/null | cut -f1)
Ydea notifications: $(du -sh "$SITE_BASE/local/share/check_mk/notifications" 2>/dev/null | cut -f1 || echo "N/A")

=== HOSTS MONITORATI ===
Host count: $(su - "$SITE" -c "cmk --list-hosts 2>/dev/null | wc -l" || echo "N/A")

=== BACKUP STRATEGY ===
Tipo: MINIMALE (solo configurazione)
Include: etc/, var/check_mk/{wato,web}, local/notifications, version
Escluso: RRD data, inventory archive, agent bakery, MKP packages
Dimensione attesa: 2-5 MB

=== COSA MANCA (DA RICREARE POST-RESTORE) ===
- Grafici storici RRD (ripartono da zero)
- Agent Bakery (cliccare "Bake agents" in CheckMK web)
- Storico inventory HW/SW (si ripopola automaticamente)
- Plugin MKP custom (reinstallare manualmente se necessari)
EOF

log "[OK] Metadati raccolti"

### BACKUP MINIMALE - SOLO CONFIGURAZIONE CRITICA ###
log "[INFO] Creazione backup MINIMALE (solo config essenziale)"

# Lista RIDOTTA - solo configurazione critica
BACKUP_ITEMS=(
  "etc/check_mk"                      # ✅ CRITICO: Configurazione hosts, regole, utenti
  "etc/omd"                           # ✅ CRITICO: Configurazione OMD/Apache
  "etc/apache"                        # ✅ Config web server
  "etc/ssl"                           # ✅ Certificati SSL (se presenti)
  "etc/htpasswd"                      # ✅ Password utenti web
  "etc/auth.secret"                   # ✅ Chiave autenticazione
  "etc/auth.serials"                  # ✅ Seriali autenticazione
  "etc/environment"                   # ✅ Variabili ambiente site
  "var/check_mk/web"                  # ✅ Viste personalizzate utenti
  "var/check_mk/wato"                 # ✅ CRITICO: Snapshot configurazioni WATO
  "local/share/check_mk/notifications" # ✅ CRITICO: Script notifica Ydea custom
  "local/lib/check_mk/notifications"  # ✅ Script notifica custom (alternativa)
  "version"                           # ✅ Versione CheckMK installata
  ".version"                          # ✅ File versione dettagliato
)

# ESCLUSO INTENZIONALMENTE (troppo pesante o ricreabile):
# ❌ var/check_mk/rrd - dati storici grafici (~300-400MB)
# ❌ var/check_mk/inventory_archive - archivio inventory HW/SW (~50-100MB)
# ❌ var/check_mk/agents - agent bakery preconfezionati (~20-50MB)
# ❌ var/check_mk/packages - pacchetti MKP installati (~10-20MB)
# ❌ var/pnp4nagios/perfdata - performance data
# ❌ local/share/check_mk/checks - check plugin custom (reinstallabili)
# ❌ local/share/check_mk/web/plugins - plugin web custom (reinstallabili)

# Costruisci comando tar con solo elementi esistenti
TAR_ITEMS=()
for item in "${BACKUP_ITEMS[@]}"; do
  if [[ -e "$SITE_BASE/$item" ]]; then
    TAR_ITEMS+=("$item")
    SIZE=$(du -sh "$SITE_BASE/$item" 2>/dev/null | cut -f1 || echo "N/A")
    log "  ✅ Includo: $item ($SIZE)"
  else
    log "  ⏭️  Skip (non presente): $item"
  fi
done

# Escludi cartelle specifiche pesanti dentro local/notifications
EXCLUDE_PATTERNS=(
  "local/share/check_mk/notifications/backup-giornaliero"
  "local/share/check_mk/notifications/__pycache__"
)

log ""
log "[INFO] Escludo cartelle pesanti/inutili:"
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
  if [[ -e "$SITE_BASE/$pattern" ]]; then
    EXCLUDE_SIZE=$(du -sh "$SITE_BASE/$pattern" 2>/dev/null | cut -f1 || echo "N/A")
    log "  ❌ Escludo: $pattern ($EXCLUDE_SIZE)"
  fi
done

# Mostra cosa viene ESCLUSO
log ""
log "[INFO] ESCLUSO dal backup (ricreabili o troppo pesanti):"
log "  ❌ var/check_mk/rrd - grafici storici (si perdono)"
log "  ❌ var/check_mk/inventory_archive - storico HW"
log "  ❌ var/check_mk/agents - agent bakery (rigenerare)"
log "  ❌ var/check_mk/packages - MKP packages (reinstallare)"
log "  ❌ local/share/check_mk/checks - plugin custom (da GitHub)"
log ""

# Crea archivio MINIMALE con esclusioni
log "[INFO] Compressione archivio..."

# Costruisci parametri --exclude per tar
EXCLUDE_ARGS=()
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
  EXCLUDE_ARGS+=(--exclude="$pattern")
done

tar czf "$TMP_DIR/$ARCHIVE" \
  -C "$SITE_BASE" \
  "${EXCLUDE_ARGS[@]}" \
  "${TAR_ITEMS[@]}" 2>&1 | tee -a "$LOG_FILE"

# Verifica integrità archivio
if tar tzf "$TMP_DIR/$ARCHIVE" >/dev/null 2>&1; then
  log "[OK] Archivio creato e verificato: $ARCHIVE"
else
  log "ERRORE: Archivio corrotto"
  exit 1
fi

# Calcola checksum e dimensione
CHECKSUM=$(sha256sum "$TMP_DIR/$ARCHIVE" | awk '{print $1}')
ARCHIVE_SIZE=$(stat -c%s "$TMP_DIR/$ARCHIVE")
ARCHIVE_SIZE_MB=$(echo "scale=2; $ARCHIVE_SIZE / 1048576" | bc)

log "[OK] Dimensione archivio: ${ARCHIVE_SIZE_MB} MB (vs ~433 MB del backup completo)"
log "[INFO] SHA256: $CHECKSUM"

echo -e "\n=== CHECKSUM ===" >> "$TMP_DIR/$METADATA"
echo "SHA256: $CHECKSUM" >> "$TMP_DIR/$METADATA"
echo "Dimensione: ${ARCHIVE_SIZE_MB} MB" >> "$TMP_DIR/$METADATA"

### SALVATAGGIO CONFIGURAZIONE RESTORE ###
log "[INFO] Creo script istruzioni per restore"

cat > "$TMP_DIR/RESTORE_INSTRUCTIONS.txt" <<'RESTORE_EOF'
=== ISTRUZIONI RESTORE BACKUP MINIMALE ===

⚠️ IMPORTANTE: Questo è un backup MINIMALE contenente SOLO la configurazione.
    Mancano: grafici storici, agent bakery, inventory archive, plugin custom.

PREREQUISITI:
1. CheckMK STESSA VERSION installato (vedi .metadata.txt)
2. OMD site con STESSO NOME creato: omd create <SITE_NAME>
3. Site fermato: omd stop <SITE_NAME>

PROCEDURA RESTORE:

# 1. Ferma il site
omd stop <SITE_NAME>

# 2. Backup configurazione attuale (precauzione)
mv /opt/omd/sites/<SITE_NAME>/etc /opt/omd/sites/<SITE_NAME>/etc.BACKUP_$(date +%Y%m%d)

# 3. Estrai backup MINIMALE
tar xzf checkmk-MINIMAL-<SITE_NAME>-<DATE>.tgz -C /opt/omd/sites/<SITE_NAME>/

# 4. Ripristina ownership corretti
chown -R <SITE_NAME>:<SITE_NAME> /opt/omd/sites/<SITE_NAME>

# 5. Verifica checksum (da file .metadata.txt)
sha256sum -c <<< "<CHECKSUM>  checkmk-MINIMAL-<SITE_NAME>-<DATE>.tgz"

# 6. Riavvia site
omd start <SITE_NAME>

# 7. Verifica servizi
omd status <SITE_NAME>

# 8. Ricompila configurazione monitoring
su - <SITE_NAME>
cmk -R
cmk -O

# 9. IMPORTANTE: Rigenera Agent Bakery
#    Web UI → Setup → Agents → Windows, Linux, Solaris → "Bake agents"
#    Oppure CLI:
su - <SITE_NAME>
cmk --bake-agents

# 10. Reinstalla integrazione Ydea (include cronjobs)
export CHECKMK_SITE=<SITE_NAME>
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/Ydea-Toolkit/full/install-ydea-checkmk-integration.sh | bash

# 11. Reinstalla cronjob cleanup CheckMK
(crontab -l 2>/dev/null; echo "# Cleanup Nagios & PNP4Nagios - ogni giorno alle 03:00"; echo "0 3 * * * curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash >> /var/log/cleanup-checkmk.log 2>&1") | crontab -

# 12. Test web interface
curl -k https://localhost/<SITE_NAME>/

# 13. Verifica notifiche Ydea
#     Configurare credenziali: /opt/ydea-toolkit/.env

COSA ASPETTARSI POST-RESTORE:
✅ Hosts configurati: OK
✅ Regole monitoring: OK
✅ Utenti e permessi: OK
✅ Configurazione WATO: OK
✅ Notifiche Ydea: OK (dopo reinstall integration)
❌ Grafici storici: VUOTI (ripartono da zero)
❌ Agent Bakery: Da rigenerare (step 9)
❌ Inventory storico: Si ripopola gradualmente
❌ Plugin MKP custom: Reinstallare manualmente se necessari

TROUBLESHOOTING:
- Permission errors: verificare owner con 'ls -la'
- Service non partono: controllare 'omd status' e log in var/log/
- Versione mismatch: installare stessa versione da .metadata.txt
- Notifiche Ydea: verificare /opt/ydea-toolkit/.env
- Grafici vuoti: NORMALE, si ripopolano automaticamente
- Agent bakery vuoto: seguire step 9 per rigenerare

NOTE:
- Backup ottimizzato per disaster recovery configuration-only
- Dimensione: 2-5 MB vs 433 MB del backup completo
- Tempo restore: ~5 minuti + 2 minuti per bake agents
- Dati storici RRD: non recuperabili (iniziano da zero post-restore)
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
  # SKIP file con MINIMAL nel nome (non applica retention)
  if [[ "$path" =~ MINIMAL ]]; then
    log "  ⏭️  Skip retention: $path (contiene MINIMAL)"
    continue
  fi
  
  FILE_DATE=$(date -d "$mtime" +%Y-%m-%d 2>/dev/null || echo "9999-99-99")
  if [[ "$FILE_DATE" < "$CUTOFF_DATE" ]]; then
    log "  - Rimuovo file obsoleto: $path (data: $FILE_DATE)"
    su - "$SITE" -c "rclone delete '$RCLONE_REMOTE/$RCLONE_PATH/$path'" 2>&1 | tee -a "$LOG_FILE"
  fi
done

### CLEANUP LOCALE ###
rm -f "$TMP_DIR/$ARCHIVE" "$TMP_DIR/$METADATA" "$TMP_DIR/RESTORE_INSTRUCTIONS.txt"

### STATISTICHE FINALI ###
log ""
log "════════════════════════════════════════════════════════════════"
log "   BACKUP MINIMALE COMPLETATO CON SUCCESSO"
log "════════════════════════════════════════════════════════════════"
log ""
log "📦 Archivio: $ARCHIVE"
log "📊 Dimensione: ${ARCHIVE_SIZE_MB} MB (risparmio: ~$(echo "433 - $ARCHIVE_SIZE_MB" | bc) MB)"
log "🔒 SHA256: $CHECKSUM"
log "☁️  Destinazione: $RCLONE_REMOTE/$RCLONE_PATH"
log "⏱️  Retention: $RETENTION_DAYS giorni"
log ""
log "✅ INCLUSO NEL BACKUP:"
log "   • etc/check_mk - hosts, regole, utenti"
log "   • var/check_mk/wato - snapshot WATO"
log "   • var/check_mk/web - viste personalizzate"
log "   • local/notifications - integrazione Ydea"
log ""
log "❌ ESCLUSO (ricreabile):"
log "   • var/check_mk/rrd - grafici storici"
log "   • var/check_mk/agents - agent bakery"
log "   • var/check_mk/inventory_archive - storico inventory"
log "   • var/check_mk/packages - MKP packages"
log ""
log "📖 Per restore: scaricare $ARCHIVE e seguire RESTORE_INSTRUCTIONS.txt"
log ""
log "════════════════════════════════════════════════════════════════"

exit 0
