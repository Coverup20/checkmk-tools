#!/bin/bash
set -euo pipefail

### SCRIPT INTERATTIVO RESTORE DISASTER RECOVERY ###

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

RCLONE_REMOTE="${RCLONE_REMOTE:-do:testmonbck}"
BACKUP_BASE="/opt/checkmk-backup"

### FUNZIONI UTILITY ###
log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
error() { echo -e "${RED}❌ $*${NC}" >&2; }
title() { echo -e "\n${CYAN}╔═══════════════════════════════════════════════════════════════╗${NC}"; echo -e "${CYAN}║ $*${NC}"; echo -e "${CYAN}╚═══════════════════════════════════════════════════════════════╝${NC}\n"; }

confirm() {
  local prompt="$1"
  local default="${2:-n}"
  local reply
  
  if [[ "$default" == "y" ]]; then
    read -p "$prompt [Y/n] " -r reply
    reply="${reply:-y}"
  else
    read -p "$prompt [y/N] " -r reply
    reply="${reply:-n}"
  fi
  
  [[ "$reply" =~ ^[Yy]$ ]]
}

pause() {
  echo ""
  read -p "Premi INVIO per continuare..." -r
}

### CHECK ROOT ###
if [[ $EUID -ne 0 ]]; then
  error "Questo script deve essere eseguito come root"
  echo "  Usa: sudo $0"
  exit 1
fi

### BANNER ###
clear
title "🔄 CHECKMK DISASTER RECOVERY - RESTORE INTERATTIVO"

echo -e "${YELLOW}ATTENZIONE:${NC}"
echo "Questo script ripristinerà la configurazione CheckMK da backup."
echo "Il sito verrà fermato durante l'operazione."
echo ""

if ! confirm "Vuoi continuare?" "n"; then
  error "Operazione annullata dall'utente"
  exit 0
fi

### VERIFICA/INSTALLA RCLONE ###
title "📦 Verifica rclone"

if ! command -v rclone >/dev/null; then
  warn "rclone non installato"
  if confirm "Vuoi installarlo ora?" "y"; then
    log "Installo rclone..."
    if curl -fsSL https://rclone.org/install.sh | bash; then
      success "rclone installato"
    else
      error "Installazione rclone fallita"
      exit 1
    fi
  else
    error "rclone necessario per il restore"
    exit 1
  fi
else
  success "rclone già installato"
fi

### SELEZIONE SITE ###
title "🏢 Selezione Site CheckMK"

log "Sites disponibili sul sistema:"
omd sites | tail -n +2 || true
echo ""

read -p "Nome del site da ripristinare: " SITE_INPUT
SITE="${SITE_INPUT:-monitoring}"
SITE_BASE="/opt/omd/sites/$SITE"

if [[ ! -d "$SITE_BASE" ]]; then
  warn "Site '$SITE' non trovato in $SITE_BASE"
  echo ""
  
  if confirm "Vuoi creare il site '$SITE' ora?" "y"; then
    log "Creo site '$SITE'..."
    if omd create "$SITE"; then
      success "Site '$SITE' creato"
      SITE_BASE="/opt/omd/sites/$SITE"
    else
      error "Creazione site fallita"
      exit 1
    fi
  else
    error "Site necessario per il restore"
    echo ""
    echo "Crea manualmente con:"
    echo "  omd create $SITE"
    exit 1
  fi
else
  success "Site '$SITE' trovato"
fi

# Usa directory temporanea del site user (ha già i permessi)
TMP_DIR="/opt/omd/sites/$SITE/tmp/dr-restore"
su - "$SITE" -c "mkdir -p '$TMP_DIR'"

# Costruisci path rclone basato sul site
RCLONE_PATH="checkmk-backups/$SITE"
RCLONE_PATH_MINIMAL="checkmk-backups/$SITE-minimal"
RCLONE_CONF="/opt/omd/sites/$SITE/.config/rclone/rclone.conf"

if [[ ! -f "$RCLONE_CONF" ]]; then
  warn "Configurazione rclone non trovata per site '$SITE'"
  echo "  Path cercato: $RCLONE_CONF"
  echo ""
  
  if confirm "Vuoi configurare rclone ora per DigitalOcean Spaces?" "y"; then
    title "⚙️  Configurazione rclone per DigitalOcean Spaces"
    
    # Crea directory config se non esiste
    su - "$SITE" -c "mkdir -p ~/.config/rclone"
    
    echo "Inserisci le credenziali DigitalOcean Spaces:"
    echo ""
    read -p "Access Key ID: " ACCESS_KEY
    read -sp "Secret Access Key: " SECRET_KEY
    echo ""
    read -p "Region [ams3]: " REGION
    REGION="${REGION:-ams3}"
    read -p "Endpoint [${REGION}.digitaloceanspaces.com]: " ENDPOINT
    ENDPOINT="${ENDPOINT:-${REGION}.digitaloceanspaces.com}"
    
    # Estrai nome remote da RCLONE_REMOTE (es: do:testmonbck -> do)
    REMOTE_NAME="${RCLONE_REMOTE%%:*}"
    
    log "Creo configurazione rclone remote '$REMOTE_NAME'..."
    
    # Crea configurazione rclone
    su - "$SITE" -c "rclone config create '$REMOTE_NAME' s3 \
      provider='DigitalOcean' \
      env_auth='false' \
      access_key_id='$ACCESS_KEY' \
      secret_access_key='$SECRET_KEY' \
      region='$REGION' \
      endpoint='$ENDPOINT' \
      acl='private'"
    
    if [[ $? -eq 0 ]]; then
      success "Configurazione rclone creata"
    else
      error "Configurazione rclone fallita"
      exit 1
    fi
  else
    error "Configurazione rclone necessaria per il restore"
    echo ""
    echo "Configura manualmente con:"
    echo "  su - $SITE"
    echo "  rclone config"
    exit 1
  fi
fi

### VERIFICA CONNESSIONE STORAGE ###
title "📡 Verifica Connessione Storage Remoto"

log "Verifica connessione storage remoto..."
if ! su - "$SITE" -c "rclone lsd '$RCLONE_REMOTE/' --config='$RCLONE_CONF' --s3-no-check-bucket --max-depth 1" >/dev/null 2>&1; then
  error "Impossibile connettersi a $RCLONE_REMOTE"
  echo ""
  echo "Verifica che:"
  echo "  1. La configurazione rclone sia corretta: su - $SITE -c 'rclone config'"
  echo "  2. Le credenziali siano valide"
  exit 1
fi
success "Connessione OK"

### LISTA BACKUP DISPONIBILI ###
title "📦 Backup Disponibili"

log "Recupero lista backup da storage remoto..."

# Lista tutti i file .tgz da entrambi i path
BACKUP_FILES_STANDARD=$(su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH' --config='$RCLONE_CONF' --s3-no-check-bucket --files-only 2>/dev/null" | grep "\.tgz$" || true)
BACKUP_FILES_MINIMAL=$(su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH_MINIMAL' --config='$RCLONE_CONF' --s3-no-check-bucket --files-only 2>/dev/null" | grep "\.tgz$" || true)

# Combina e ordina per data (più recenti prima)
BACKUP_FILES=$(printf "%s\n%s" "$BACKUP_FILES_STANDARD" "$BACKUP_FILES_MINIMAL" | grep -v '^$' | sort -r)

if [[ -z "$BACKUP_FILES" ]]; then
  error "Nessun file .tgz trovato"
  echo ""
  log "DEBUG: Contenuto cartella remota:"
  su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$RCLONE_PATH' --config='$RCLONE_CONF' --s3-no-check-bucket --files-only" | head -20 || echo "  (errore listing)"
  exit 1
fi

echo ""
echo "Backup disponibili:"
echo ""
i=1
declare -A BACKUP_MAP
while IFS= read -r filename; do
  BACKUP_MAP[$i]="$filename"
  # Estrai data dal nome file: checkmk-DR-monitoring-2026-01-23_17-00-37.tgz
  BACKUP_DATE=$(echo "$filename" | grep -oP '\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}' | sed 's/_/ /; s/-/\//g' || echo "N/A")
  printf "%2d) %s  [%s]\n" "$i" "$filename" "$BACKUP_DATE"
  ((i++))
done <<< "$BACKUP_FILES"

echo ""
read -p "Seleziona numero backup (1-$((i-1))) o 'q' per uscire: " selection

if [[ "$selection" == "q" ]]; then
  error "Operazione annullata"
  exit 0
fi

if [[ ! "$selection" =~ ^[0-9]+$ ]] || [[ "$selection" -lt 1 ]] || [[ "$selection" -ge "$i" ]]; then
  error "Selezione non valida"
  exit 1
fi

BACKUP_FILE="${BACKUP_MAP[$selection]}"

# Determina da quale path scaricare
if echo "$BACKUP_FILES_MINIMAL" | grep -q "^$BACKUP_FILE$"; then
  SELECTED_PATH="$RCLONE_PATH_MINIMAL"
else
  SELECTED_PATH="$RCLONE_PATH"
fi

success "Selezionato: $BACKUP_FILE (da $SELECTED_PATH)"

### SCARICA METADATA ###
title "📋 Informazioni Backup"

METADATA_FILE="${BACKUP_FILE%.tgz}.metadata.txt"
mkdir -p "$TMP_DIR"

if su - "$SITE" -c "rclone lsf '$RCLONE_REMOTE/$SELECTED_PATH/$METADATA_FILE' --config='$RCLONE_CONF' --s3-no-check-bucket" >/dev/null 2>&1; then
  log "Scarico metadati..."
  su - "$SITE" -c "rclone copyto '$RCLONE_REMOTE/$SELECTED_PATH/$METADATA_FILE' '$TMP_DIR/$METADATA_FILE' --config='$RCLONE_CONF' --s3-no-check-bucket -q"
  
  if [[ -f "$TMP_DIR/$METADATA_FILE" ]]; then
    echo ""
    cat "$TMP_DIR/$METADATA_FILE"
    echo ""
  fi
else
  warn "File metadati non trovato (backup vecchio?)"
fi

pause

### CONFERMA FINALE ###
title "⚠️  CONFERMA RIPRISTINO"

echo -e "${RED}ATTENZIONE:${NC}"
echo "Stai per ripristinare:"
echo "  - Site: $SITE"
echo "  - Backup: $BACKUP_FILE"
echo ""
echo "Operazioni che verranno eseguite:"
echo "  1. Fermo site CheckMK"
echo "  2. Backup configurazione attuale (precauzione)"
echo "  3. Estrazione backup DR"
echo "  4. Ripristino permessi"
echo "  5. Riavvio site"
echo ""

if ! confirm "Sei SICURO di voler procedere?" "n"; then
  error "Operazione annullata"
  exit 0
fi

### DOWNLOAD BACKUP ###
title "⬇️  Download Backup"

log "Scarico $BACKUP_FILE da storage remoto..."
su - "$SITE" -c "rclone copy '$RCLONE_REMOTE/$SELECTED_PATH' '$TMP_DIR/' \
  --config='$RCLONE_CONF' \
  --s3-no-check-bucket \
  --include '$BACKUP_FILE' \
  --progress"

if [[ ! -f "$TMP_DIR/$BACKUP_FILE" ]]; then
  error "Download fallito!"
  exit 1
fi

BACKUP_SIZE=$(du -h "$TMP_DIR/$BACKUP_FILE" | cut -f1)
success "Download completato ($BACKUP_SIZE)"

# Verifica integrità
log "Verifica integrità archivio..."
if ! tar tzf "$TMP_DIR/$BACKUP_FILE" >/dev/null 2>&1; then
  error "Archivio corrotto!"
  exit 1
fi
success "Archivio integro"

### FERMA SITE ###
title "🛑 Fermo Site CheckMK"

log "Fermo site '$SITE'..."
if omd stop "$SITE" 2>&1 | tee /tmp/omd_stop.log; then
  success "Site fermato"
else
  warn "Alcuni servizi potrebbero non essere stati fermati correttamente"
  cat /tmp/omd_stop.log
  if ! confirm "Vuoi continuare comunque?"; then
    error "Operazione annullata"
    exit 1
  fi
fi

### BACKUP CONFIGURAZIONE ATTUALE ###
title "💾 Backup Configurazione Attuale"

BACKUP_OLD="$BACKUP_BASE/pre-restore-backup-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_OLD"

log "Salvo configurazione attuale in $BACKUP_OLD..."
tar czf "$BACKUP_OLD/etc-backup.tgz" -C "$SITE_BASE" etc 2>/dev/null || true
tar czf "$BACKUP_OLD/local-backup.tgz" -C "$SITE_BASE" local 2>/dev/null || true
tar czf "$BACKUP_OLD/ydea-toolkit-backup.tgz" -C /opt ydea-toolkit 2>/dev/null || true

success "Backup di sicurezza creato"
echo "  In caso di problemi: $BACKUP_OLD"

### ESTRAZIONE BACKUP ###
title "📂 Ripristino Configurazione"

log "Estraggo backup in $SITE_BASE (include ydea-toolkit via path relativo)..."
if tar xzf "$TMP_DIR/$BACKUP_FILE" -C "$SITE_BASE" 2>&1 | tee /tmp/tar_extract.log; then
  success "Estrazione completata"
else
  error "Errore durante l'estrazione!"
  cat /tmp/tar_extract.log
  echo ""
  error "ROLLBACK: Ripristino backup precedente..."
  tar xzf "$BACKUP_OLD/etc-backup.tgz" -C "$SITE_BASE" 2>/dev/null || true
  tar xzf "$BACKUP_OLD/local-backup.tgz" -C "$SITE_BASE" 2>/dev/null || true
  exit 1
fi

# Sposta ydea-toolkit nella posizione corretta se estratto in $SITE_BASE
if [[ -d "$SITE_BASE/ydea-toolkit" ]]; then
  log "Sposto ydea-toolkit da $SITE_BASE/ydea-toolkit a /opt/ydea-toolkit..."
  if [[ -d /opt/ydea-toolkit ]]; then
    warn "Directory /opt/ydea-toolkit esiste già, la sovrascrivo"
    rm -rf /opt/ydea-toolkit
  fi
  mv "$SITE_BASE/ydea-toolkit" /opt/ydea-toolkit
  success "ydea-toolkit spostato in /opt/"
fi

### RIPRISTINO PERMESSI ###
title "🔐 Ripristino Permessi"

log "Ripristino ownership per user '$SITE'..."
chown -R "$SITE:$SITE" "$SITE_BASE"
log "Ripristino ownership per ydea-toolkit..."
chown -R root:root /opt/ydea-toolkit 2>/dev/null || true
chmod 644 /opt/ydea-toolkit/.env* 2>/dev/null || true
success "Permessi ripristinati"

### RIAVVIO SITE ###
title "▶️  Riavvio Site CheckMK"

log "Riavvio site '$SITE'..."
if omd start "$SITE" 2>&1 | tee /tmp/omd_start.log; then
  success "Site riavviato"
else
  error "Errore durante il riavvio!"
  cat /tmp/omd_start.log
  echo ""
  warn "Verifica log manualmente:"
  echo "  omd status $SITE"
  echo "  tail -f /opt/omd/sites/$SITE/var/log/*.log"
fi

echo ""
log "Stato servizi:"
omd status "$SITE"

### VERIFICA SERVIZI ###
title "✅ Verifica Servizi"

log "Attendo avvio servizi..."
sleep 5

FAILED=0
while IFS= read -r line; do
  if echo "$line" | grep -q "stopped" || echo "$line" | grep -q "STOPPED"; then
    warn "$line"
    ((FAILED++))
  fi
done < <(omd status "$SITE" 2>&1)

if [[ $FAILED -gt 0 ]]; then
  warn "$FAILED servizio/i non avviato/i"
  echo ""
  echo "Verifica manualmente con:"
  echo "  omd status $SITE"
  echo "  omd start $SITE"
else
  success "Tutti i servizi sono attivi"
fi

### RICOMPILA CONFIGURAZIONE ###
title "🔄 Ricompilazione Configurazione"

if confirm "Vuoi ricompilare la configurazione monitoring?"; then
  log "Ricompilo configurazione..."
  su - "$SITE" -c "cmk -R" 2>&1 | head -20
  su - "$SITE" -c "cmk -O" 2>&1 | head -20
  success "Configurazione ricompilata"
fi

### COMPONENTI ESTERNI ###
title "⚙️  Configurazione Componenti Esterni"

echo "✅ Ydea-Toolkit ripristinato da backup (/opt/ydea-toolkit/)"
echo "✅ Script notifiche custom ripristinati"
echo ""
log "Verifica configurazione Ydea..."
if [[ -f /opt/ydea-toolkit/.env ]]; then
  success "File .env trovato"
  echo "  YDEA_ID: $(grep YDEA_ID /opt/ydea-toolkit/.env | cut -d'=' -f2 | tr -d '"')"
else
  warn "File .env non trovato, verifica manualmente"
fi

echo ""
if confirm "Vuoi reinstallare cronjob cleanup CheckMK?"; then
  (crontab -l 2>/dev/null; echo "# Cleanup Nagios & PNP4Nagios"; echo "0 3 * * * curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash >> /var/log/cleanup-checkmk.log 2>&1") | crontab -
  success "Cronjob cleanup installato"
fi

### CLEANUP ###
rm -f "$TMP_DIR/$BACKUP_FILE" "$TMP_DIR/$METADATA_FILE"

### CONFIGURAZIONE PASSWORD CMKADMIN ###
title "🔑 Configurazione Password cmkadmin"

echo "Vuoi impostare una nuova password per l'utente 'cmkadmin'?"
echo ""
if confirm "Impostare nuova password per cmkadmin?" "y"; then
  echo ""
  log "Inserisci la nuova password per 'cmkadmin':"
  
  # Usa cmk-passwd per impostare la password
  if su - "$SITE" -c "cmk-passwd cmkadmin" 2>&1; then
    success "Password cmkadmin impostata correttamente"
  else
    warn "Errore nell'impostazione della password"
    echo "Puoi impostarla manualmente con:"
    echo "  su - $SITE"
    echo "  cmk-passwd cmkadmin"
  fi
else
  warn "Password cmkadmin non modificata"
  echo "Ricorda di cambiarla manualmente per sicurezza:"
  echo "  su - $SITE"
  echo "  cmk-passwd cmkadmin"
fi

### RIEPILOGO FINALE ###
title "🎉 RESTORE COMPLETATO!"

success "Ripristino eseguito con successo"
echo ""
echo "📊 Riepilogo:"
echo "  - Site: $SITE"
echo "  - Backup: $BACKUP_FILE"
echo "  - Backup precedente salvato in: $BACKUP_OLD"
echo ""
echo "🔍 Prossimi passi:"
echo ""
echo "1. Verifica web interface:"
echo "   https://$(hostname)/$SITE/"
echo ""
echo "2. Controlla log:"
echo "   tail -f /opt/omd/sites/$SITE/var/log/cmc.log"
echo "   tail -f /opt/omd/sites/$SITE/var/log/web.log"
echo ""
echo "3. Verifica hosts:"
echo "   su - $SITE"
echo "   cmk --list-hosts"
echo ""
echo "4. Configura credenziali Ydea (se necessario):"
echo "   nano /opt/ydea-toolkit/.env"
echo ""
echo -e "${GREEN}✅ Restore completato!${NC}"
echo ""

exit 0
