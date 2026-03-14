#!/bin/bash
set -euo pipefail

### SCRIPT BACKUP ULTRA-MINIMALE CHECKMK ###
# Include SOLO configurazione essenziale hosts/rules
# Escluso: web users, notifications, views personalizzate
# Dimensione attesa: < 500 KB

### CONFIGURAZIONE ###
if [[ -z "${1:-}" ]]; then
  if ! command -v omd >/dev/null 2>&1; then
    echo "ERRORE: comando 'omd' non trovato. CheckMK non installato?"
    exit 1
  fi
  
  SITE=$(omd sites 2>/dev/null | grep -v "^SITE" | head -1 | awk '{print $1}')
  
  if [[ -z "$SITE" ]]; then
    echo "ERRORE: Nessun site CheckMK trovato"
    exit 1
  fi
  
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
LOG_FILE="$BACKUP_BASE/backup-ultra-minimal.log"

RCLONE_REMOTE="${RCLONE_REMOTE:-do:testmonbck}"
RCLONE_PATH="${RCLONE_PATH:-checkmk-backups/monitoring-minimal}"

RETENTION_DAYS="${RETENTION_DAYS:-90}"

DATE="$(date +%F_%H-%M-%S)"
ARCHIVE="checkmk-ULTRA-MINIMAL-${SITE}-${DATE}.tgz"
METADATA="checkmk-ULTRA-MINIMAL-${SITE}-${DATE}.metadata.txt"

### LOGGING ###
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

### CREAZIONE DIRECTORY ###
mkdir -p "$BACKUP_BASE" "$TMP_DIR"

### PRECHECK ###
log "=== INIZIO BACKUP ULTRA-MINIMALE per site $SITE ==="
log "[INFO] Backup configurazione completa: hosts, dashboard, notifiche, ydea-toolkit"

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
  exit 1
fi
log "[OK] Remote rclone configurato: $RCLONE_REMOTE"

### RACCOLTA METADATI ###
log "[INFO] Raccolta metadati sistema"

cat > "$TMP_DIR/$METADATA" <<EOF
=== CHECKMK BACKUP ULTRA-MINIMALE ===
Data backup: $(date)
Hostname: $(hostname -f)
Site: $SITE
CheckMK Version: $(cat "$SITE_BASE/version" 2>/dev/null || echo "N/A")
CheckMK Edition: $(grep -oP 'CMK_VERSION="\K[^"]+' "$SITE_BASE/.version" 2>/dev/null || echo "N/A")
OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)
Kernel: $(uname -r)

=== HOSTS MONITORATI ===
Host count: $(su - "$SITE" -c "cmk --list-hosts 2>/dev/null | wc -l" || echo "N/A")

=== BACKUP STRATEGY ===
Tipo: ULTRA-MINIMALE (config attiva completa, no snapshot storici)
Include: omd/sites/$SITE/etc/check_mk/conf.d/, multisite.d/, wato/, notifications/, ydea-toolkit/
Escluso: snapshot WATO storici, utenti web, RRD, inventory, agent bakery, cache
Dimensione attesa: < 500 KB

=== COSA INCLUSO ===
✅ Hosts e regole monitoring
✅ Dashboard personalizzate
✅ Bookmark utenti
✅ Configurazioni WATO attive
✅ Setup notifiche base
✅ Script notifiche custom (mail_realip, telegram, ydea)
✅ Configurazione Ydea-Toolkit (.env, .env.ag, .env.la, premium-mon-config.json)

=== COSA MANCA (DA RICREARE POST-RESTORE) ===
- Snapshot WATO storici (rollback configurazioni passate)
- Utenti web (creare manualmente o da LDAP)
- Grafici storici RRD
- Agent Bakery
- Storico inventory HW/SW
- Plugin MKP custom
- Configurazioni Apache/SSL custom
EOF

log "[OK] Metadati raccolti"

### BACKUP ULTRA-MINIMALE - CONFIG COMPLETA ###
log "[INFO] Creazione backup ULTRA-MINIMALE (config completa)"

# Lista ULTRA-RIDOTTA - solo configurazione hosts ATTIVA
BACKUP_ITEMS=(
  "etc/check_mk/conf.d"               # ✅ CRITICO: File main.mk, wato_rules.mk (hosts/rules)
  "etc/check_mk/multisite.d"          # ✅ Configurazione multisite base
  "etc/check_mk/backup.mk"            # ✅ Configurazione backup UI (360 bytes)
  "local/share/check_mk/notifications" # ✅ Script notifiche custom (mail_realip, telegram, ydea)
  "var/check_mk/wato"                 # ✅ Dashboard, bookmark, config WATO
  "var/check_mk/web"                  # ✅ Dashboard utenti, viste personalizzate
  "version"                           # ✅ Versione CheckMK installata
  "../../../ydea-toolkit"              # ✅ Configurazione Ydea API (path relativo da $SITE_BASE)
)

# ESCLUDI file pesanti da WATO (solo snapshot .tar e log)
EXCLUDE_PATTERNS=(
  "var/check_mk/wato/snapshots/*.tar"        # Snapshot WATO storici (1.5MB)
  "var/check_mk/wato/snapshots/workdir"      # Directory temporanea
  "var/check_mk/wato/log/*.log"              # Log audit (1.3MB)
  "var/check_mk/wato/*/replication_changes*" # File replicazione distribuita
  "var/check_mk/wato/*/activation_state*"    # File stato attivazione temporanei
  "../../../ydea-toolkit/cache/*"            # Cache Ydea (path relativo)
)

# ESCLUSO INTENZIONALMENTE:
# ❌ etc/htpasswd - utenti web (da ricreare)
# ❌ etc/auth.* - autenticazione (da ricreare)
# ❌ etc/apache - config web server (defaults vanno bene)
# ❌ etc/ssl - certificati SSL (da rigenerare)
# ❌ etc/omd - config OMD (defaults vanno bene)
# ❌ var/check_mk/rrd - dati storici grafici
# ❌ var/check_mk/inventory_archive - archivio inventory HW/SW
# ❌ var/check_mk/agents - agent bakery

log "[INFO] Creazione archivio compresso..."

# Crea lista file da includere
INCLUDE_ARGS=()
for item in "${BACKUP_ITEMS[@]}"; do
  # Risolvi path assoluto per verifica (gestisce ../../../ydea-toolkit)
  FULL_PATH="$(cd "$SITE_BASE" && readlink -f "$item" 2>/dev/null || echo "$SITE_BASE/$item")"
  if [[ -e "$FULL_PATH" ]]; then
    INCLUDE_ARGS+=("$item")
    log "  ✅ Include: $item ($(du -sh "$FULL_PATH" 2>/dev/null | cut -f1))"
  else
    log "  ⏭️  Skip: $item (non esiste)"
  fi
done

if [[ ${#INCLUDE_ARGS[@]} -eq 0 ]]; then
  log "ERRORE: Nessun file da backuppare trovato!"
  exit 1
fi

# Mostra esclusioni
log "[INFO] Esclusioni attive:"
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
  log "  ❌ Exclude: $pattern"
done

# Crea archivio da $SITE_BASE
cd "$SITE_BASE"

# Costruisci argomenti esclusione
EXCLUDE_ARGS=()
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
  EXCLUDE_ARGS+=(--exclude="$pattern")
done

log "[DEBUG] Comando tar: tar czf <archive> ${EXCLUDE_ARGS[*]} ${INCLUDE_ARGS[*]}"

if tar czf "$TMP_DIR/$ARCHIVE" "${EXCLUDE_ARGS[@]}" "${INCLUDE_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"; then
  ARCHIVE_SIZE=$(du -h "$TMP_DIR/$ARCHIVE" | cut -f1)
  ARCHIVE_SIZE_BYTES=$(stat -c%s "$TMP_DIR/$ARCHIVE")
  log "[OK] Archivio creato: $ARCHIVE ($ARCHIVE_SIZE)"
  
  # Warning se troppo grande
  if [[ $ARCHIVE_SIZE_BYTES -gt 1048576 ]]; then  # > 1 MB
    log "[WARNING] Archivio più grande del previsto (atteso < 500KB)"
  fi
else
  log "ERRORE: Creazione archivio fallita"
  exit 1
fi

# Calcola SHA256
log "[INFO] Calcolo checksum SHA256..."
CHECKSUM=$(sha256sum "$TMP_DIR/$ARCHIVE" | awk '{print $1}')
log "[OK] SHA256: $CHECKSUM"

# Aggiungi checksum ai metadati
cat >> "$TMP_DIR/$METADATA" <<EOF

=== VERIFICA INTEGRITÀ ===
SHA256: $CHECKSUM
Dimensione: $ARCHIVE_SIZE ($ARCHIVE_SIZE_BYTES bytes)
EOF

### UPLOAD SU STORAGE REMOTO ###
log "[INFO] Upload su storage remoto $RCLONE_REMOTE/$RCLONE_PATH"

# Upload come utente site (ha configurazione rclone)
if su - "$SITE" -c "rclone copy '$TMP_DIR/$ARCHIVE' '$RCLONE_REMOTE/$RCLONE_PATH/' --progress --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf 2>&1" | tee -a "$LOG_FILE"; then
  log "[OK] Upload archivio completato"
else
  log "ERRORE: Upload archivio fallito"
  exit 1
fi

if su - "$SITE" -c "rclone copy '$TMP_DIR/$METADATA' '$RCLONE_REMOTE/$RCLONE_PATH/' --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf 2>&1" | tee -a "$LOG_FILE"; then
  log "[OK] Upload metadati completato"
else
  log "WARNING: Upload metadati fallito (non critico)"
fi

### CLEANUP LOCALE ###
log "[INFO] Cleanup file temporanei locali"
rm -f "$TMP_DIR/$ARCHIVE" "$TMP_DIR/$METADATA"
log "[OK] File temporanei rimossi"

### RETENTION REMOTA ###
log "[INFO] Applicazione retention remota ($RETENTION_DAYS giorni)"

# Lista backup ultra-minimal remoti
REMOTE_BACKUPS=$(su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH/' --format 'tp' --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf 2>/dev/null" | grep "checkmk-ULTRA-MINIMAL.*\.tgz$" || true)

if [[ -z "$REMOTE_BACKUPS" ]]; then
  log "[INFO] Nessun backup remoto da verificare per retention"
else
  CUTOFF_DATE=$(date -d "$RETENTION_DAYS days ago" +%s)
  
  while IFS=$'\t' read -r mtime filename; do
    # Parsing data modificazione (formato: 2026-01-26 11:26:56)
    FILE_DATE=$(date -d "$mtime" +%s 2>/dev/null || echo "0")
    
    if [[ $FILE_DATE -lt $CUTOFF_DATE ]] && [[ $FILE_DATE -gt 0 ]]; then
      AGE_DAYS=$(( ($(date +%s) - FILE_DATE) / 86400 ))
      log "  🗑️  Cancello backup vecchio ($AGE_DAYS giorni): $filename"
      
      su - "$SITE" -c "rclone delete '$RCLONE_REMOTE/$RCLONE_PATH/$filename' --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf" 2>&1 | tee -a "$LOG_FILE"
      
      # Cancella anche metadata associato
      METADATA_FILE="${filename%.tgz}.metadata.txt"
      su - "$SITE" -c "rclone delete '$RCLONE_REMOTE/$RCLONE_PATH/$METADATA_FILE' --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf 2>/dev/null" || true
    fi
  done <<< "$REMOTE_BACKUPS"
fi

### RIEPILOGO FINALE ###
log "=== BACKUP ULTRA-MINIMALE COMPLETATO CON SUCCESSO ==="
log "Archivio: $ARCHIVE"
log "Dimensione: $ARCHIVE_SIZE ($ARCHIVE_SIZE_BYTES bytes)"
log "Checksum: $CHECKSUM"
log "Destinazione: $RCLONE_REMOTE/$RCLONE_PATH/"
log "Retention: $RETENTION_DAYS giorni"
log ""
log "✅ NOTA: Questo backup include configurazione completa:"
log "    ✓ Hosts/rules, ✓ Dashboard, ✓ Notifiche custom, ✓ Ydea-toolkit"
log "    ❌ Da ricreare: utenti web, certificati SSL"

# Crea file RESTORE_INSTRUCTIONS se non esiste
RESTORE_INSTRUCTIONS="$TMP_DIR/RESTORE_INSTRUCTIONS_ULTRA_MINIMAL.txt"
cat > "$RESTORE_INSTRUCTIONS" <<'EOINSTRUCTIONS'
=== ISTRUZIONI RESTORE DA BACKUP ULTRA-MINIMALE ===

ATTENZIONE: Questo backup contiene SOLO hosts e regole di monitoring.
NON include: utenti web, notifiche, viste personalizzate, certificati SSL.

PROCEDURA RESTORE:

1. Installa CheckMK stessa versione del backup:
   omd version
   # Se serve altra versione: omd update <site> <versione>

2. Ferma site:
   omd stop <site>

3. Scarica backup da storage remoto:
   su - <site>
   rclone copy do:testmonbck/checkmk-backups/monitoring-minimal/<backup.tgz> /tmp/

4. Estrai configurazione in $SITE_BASE (ydea-toolkit incluso via path relativo):
   cd /opt/omd/sites/<site>
   tar xzf /tmp/<backup.tgz>
   chown -R <site>:<site> /opt/omd/sites/<site>
   chown -R root:root /opt/ydea-toolkit

5. Riavvia site:
   omd start <site>

6. CONFIGURA SOLO:
   - Password cmkadmin: cmk-passwd cmkadmin
   - Utenti web (se necessario)
   - Certificati SSL custom (se necessario)

7. Verifica configurazione:
   cmk --list-hosts
   cmk -U    # update config
   cmk -R    # reload Apache

COSA RIPRISTINATO AUTOMATICAMENTE:
✅ Hosts/rules monitoring
✅ Dashboard personalizzate
✅ Bookmark utenti
✅ Script notifiche custom (mail_realip, telegram, ydea)
✅ Configurazione Ydea (.env, .env.ag, .env.la)
✅ Setup backup UI

RESTORE VELOCE (test):
  omd stop <site> && \
  cd /opt/omd/sites/<site> && \
  tar xzf /tmp/<backup.tgz> && \
  chown -R <site>:<site> /opt/omd/sites/<site> && \
  chown -R root:root /opt/ydea-toolkit && \
  omd start <site> && \
  cmk -R

TROUBLESHOOTING:
- Errori permessi: chown -R <site>:<site> /opt/omd/sites/<site>
- Errori config: cmk -U --debug
- Site non parte: journalctl -u omd@<site> -f

EOINSTRUCTIONS

# Upload istruzioni restore
if su - "$SITE" -c "rclone copyto '$RESTORE_INSTRUCTIONS' '$RCLONE_REMOTE/$RCLONE_PATH/RESTORE_INSTRUCTIONS_ULTRA_MINIMAL.txt' --s3-no-check-bucket --config=\$HOME/.config/rclone/rclone.conf 2>/dev/null"; then
  log "[OK] Istruzioni restore caricate su storage remoto"
else
  log "[WARNING] Upload istruzioni restore fallito (non critico)"
fi

rm -f "$RESTORE_INSTRUCTIONS"

log "=== FINE SCRIPT ==="
exit 0
