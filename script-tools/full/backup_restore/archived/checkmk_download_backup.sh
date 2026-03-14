#!/bin/bash
set -euo pipefail

### SCRIPT DOWNLOAD BACKUP DA DIGITALOCEAN SPACES ###

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

RCLONE_REMOTE="${RCLONE_REMOTE:-do:testmonbck}"
DOWNLOAD_DIR="/var/backups/checkmk"

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

### CHECK ROOT ###
if [[ $EUID -ne 0 ]]; then
  error "Questo script deve essere eseguito come root"
  echo "  Usa: sudo $0"
  exit 1
fi

### BANNER ###
clear
title "📥 DOWNLOAD BACKUP DA DIGITALOCEAN SPACES"

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
    error "rclone necessario per scaricare i backup"
    exit 1
  fi
else
  success "rclone già installato"
fi

### SELEZIONE DESTINAZIONE DOWNLOAD ###
title "📂 Destinazione Download"

read -p "Directory download [/var/backups/checkmk]: " DOWNLOAD_DIR
DOWNLOAD_DIR="${DOWNLOAD_DIR:-/var/backups/checkmk}"

mkdir -p "$DOWNLOAD_DIR"
log "Directory download: $DOWNLOAD_DIR"

### CONFIGURAZIONE RCLONE ###
title "⚙️  Configurazione rclone"

# Cerca configurazione rclone in ordine di priorità
RCLONE_CONF=""
if [[ -f "/root/.config/rclone/rclone.conf" ]]; then
  RCLONE_CONF="/root/.config/rclone/rclone.conf"
elif [[ -f "/opt/omd/sites/monitoring/.config/rclone/rclone.conf" ]]; then
  RCLONE_CONF="/opt/omd/sites/monitoring/.config/rclone/rclone.conf"
fi

if [[ -z "$RCLONE_CONF" ]] || [[ ! -f "$RCLONE_CONF" ]]; then
  warn "Configurazione rclone non trovata"
  echo "  Cercato in: /root/.config/rclone/rclone.conf"
  echo "              /opt/omd/sites/monitoring/.config/rclone/rclone.conf"
  echo ""
  
  if confirm "Vuoi configurare rclone ora per DigitalOcean Spaces?" "y"; then
    
    # Crea directory config root
    mkdir -p /root/.config/rclone
    RCLONE_CONF="/root/.config/rclone/rclone.conf"
    
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
    rclone config create "$REMOTE_NAME" s3 \
      provider='DigitalOcean' \
      env_auth='false' \
      access_key_id="$ACCESS_KEY" \
      secret_access_key="$SECRET_KEY" \
      region="$REGION" \
      endpoint="$ENDPOINT" \
      acl='private'
    
    if [[ $? -eq 0 ]]; then
      success "Configurazione rclone creata"
    else
      error "Configurazione rclone fallita"
      exit 1
    fi
  else
    error "Configurazione rclone necessaria per scaricare i backup"
    echo ""
    echo "Configura manualmente con: rclone config"
    exit 1
  fi
else
  success "Configurazione rclone trovata: $RCLONE_CONF"
  
  # Test connessione rapida
  log "Test connessione rclone..."
  if ! rclone lsd "$RCLONE_REMOTE" --config="$RCLONE_CONF" --s3-no-check-bucket >/dev/null 2>&1; then
    warn "Configurazione rclone non funzionante"
    
    if confirm "Vuoi riconfigurare rclone?" "y"; then
      # Riconfigura
      echo ""
      echo "Inserisci le credenziali DigitalOcean Spaces:"
      echo ""
      read -p "Access Key ID: " ACCESS_KEY
      read -sp "Secret Access Key: " SECRET_KEY
      echo ""
      read -p "Region [ams3]: " REGION
      REGION="${REGION:-ams3}"
      read -p "Endpoint [${REGION}.digitaloceanspaces.com]: " ENDPOINT
      ENDPOINT="${ENDPOINT:-${REGION}.digitaloceanspaces.com}"
      
      REMOTE_NAME="${RCLONE_REMOTE%%:*}"
      
      log "Ricreo configurazione rclone remote '$REMOTE_NAME'..."
      
      # Cancella e ricrea
      rclone config delete "$REMOTE_NAME" 2>/dev/null || true
      rclone config create "$REMOTE_NAME" s3 \
        provider='DigitalOcean' \
        env_auth='false' \
        access_key_id="$ACCESS_KEY" \
        secret_access_key="$SECRET_KEY" \
        region="$REGION" \
        endpoint="$ENDPOINT" \
        acl='private'
      
      if [[ $? -eq 0 ]]; then
        success "Configurazione rclone ricreata"
      else
        error "Configurazione rclone fallita"
        exit 1
      fi
    else
      error "Configurazione rclone non funzionante"
      echo "Correggi manualmente: nano $RCLONE_CONF"
      exit 1
    fi
  else
    success "Configurazione rclone funzionante"
  fi
fi

### SELEZIONE JOB DA VISUALIZZARE ###
title "🗂️  Selezione Job"

echo "Quale/i job vuoi visualizzare?"
echo ""
echo "  1) 📦 job00-daily  - Backup compressi giornalieri (1.2M, retention 90)"
echo "  2) 📦 job01-weekly - Backup completi settimanali (362M, retention 5)"
echo "  3) 📦 Entrambi     - Mostra tutti i backup disponibili"
echo ""
read -p "Selezione [1-3, default: 3]: " JOB_CHOICE
JOB_CHOICE="${JOB_CHOICE:-3}"

declare -a PATHS_TO_SCAN
case $JOB_CHOICE in
  1)
    PATHS_TO_SCAN=("checkmk-backups/job00-daily")
    log "Visualizzo solo job00-daily"
    ;;
  2)
    PATHS_TO_SCAN=("checkmk-backups/job01-weekly")
    log "Visualizzo solo job01-weekly"
    ;;
  3)
    PATHS_TO_SCAN=("checkmk-backups/job00-daily" "checkmk-backups/job01-weekly")
    log "Visualizzo entrambi i job"
    ;;
  *)
    error "Selezione non valida"
    exit 1
    ;;
esac

### VERIFICA CONNESSIONE E LISTA BACKUP ###
title "📦 Backup Disponibili"

i=1
declare -A ITEM_MAP
declare -A ITEM_TYPE
declare -A ITEM_PATH

for RCLONE_PATH in "${PATHS_TO_SCAN[@]}"; do
  # Estrai nome job per etichetta
  JOB_LABEL=""
  if [[ "$RCLONE_PATH" == *"job00-daily"* ]]; then
    JOB_LABEL="[job00-daily]"
  elif [[ "$RCLONE_PATH" == *"job01-weekly"* ]]; then
    JOB_LABEL="[job01-weekly]"
  fi
  
  log "Scansiono $RCLONE_REMOTE/$RCLONE_PATH..."
  
  # Verifica connessione
  if ! rclone lsd "$RCLONE_REMOTE/$RCLONE_PATH" --config="$RCLONE_CONF" --s3-no-check-bucket >/dev/null 2>&1; then
    warn "Path non accessibile: $RCLONE_PATH (potrebbe non esistere)"
    continue
  fi
  
  # Lista directory (backup nativi CheckMK)
  BACKUP_DIRS=$(rclone lsd "$RCLONE_REMOTE/$RCLONE_PATH" --config="$RCLONE_CONF" --s3-no-check-bucket 2>/dev/null | awk '{print $5}' | sort -r)
  
  # Lista file singoli (backup custom)
  BACKUP_FILES=$(rclone lsf "$RCLONE_REMOTE/$RCLONE_PATH" --config="$RCLONE_CONF" --s3-no-check-bucket --files-only --max-depth 1 2>/dev/null | sort -r)
  
  # Mostra directory (backup nativi)
  while IFS= read -r dirname; do
    [[ -z "$dirname" ]] && continue
    ITEM_MAP[$i]="$dirname"
    ITEM_TYPE[$i]="dir"
    ITEM_PATH[$i]="$RCLONE_PATH"
    printf "%2d) 📁 %-50s %s\n" "$i" "$dirname" "$JOB_LABEL"
    ((i++))
  done <<< "$BACKUP_DIRS"
  
  # Mostra file singoli (backup custom)
  while IFS= read -r filename; do
    [[ -z "$filename" ]] && continue
    ITEM_MAP[$i]="$filename"
    ITEM_TYPE[$i]="file"
    ITEM_PATH[$i]="$RCLONE_PATH"
    FILE_SIZE=$(rclone size "$RCLONE_REMOTE/$RCLONE_PATH/$filename" --json --config="$RCLONE_CONF" --s3-no-check-bucket 2>/dev/null | grep -oP '(?<="bytes":)\d+' || echo "0")
    if [[ "$FILE_SIZE" -gt 0 ]]; then
      FILE_SIZE_HR=$(numfmt --to=iec-i --suffix=B "$FILE_SIZE" 2>/dev/null || echo "$FILE_SIZE bytes")
    else
      FILE_SIZE_HR="N/A"
    fi
    printf "%2d) 📄 %-40s [%s] %s\n" "$i" "$filename" "$FILE_SIZE_HR" "$JOB_LABEL"
    ((i++))
  done <<< "$BACKUP_FILES"
done

if [[ $i -eq 1 ]]; then
  error "Nessun backup trovato nei path selezionati"
  exit 1
fi

success "Trovati $((i-1)) backup"

echo ""
echo "Esempi di selezione:"
echo "  - Singolo:  5"
echo "  - Multipli: 1,3,5"
echo "  - Range:    1-5"
echo "  - Misto:    1,3-7,10"
echo ""
read -p "Seleziona numero/i (1-$((i-1))) o 'q' per uscire: " selection

if [[ "$selection" == "q" ]]; then
  error "Operazione annullata"
  exit 0
fi

# Espandi range e converti in array di numeri
declare -a SELECTED_NUMBERS
IFS=',' read -ra PARTS <<< "$selection"
for part in "${PARTS[@]}"; do
  part=$(echo "$part" | xargs)  # Trim whitespace
  
  if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
    # Range: 3-7
    start="${BASH_REMATCH[1]}"
    end="${BASH_REMATCH[2]}"
    for ((n=start; n<=end; n++)); do
      SELECTED_NUMBERS+=("$n")
    done
  elif [[ "$part" =~ ^[0-9]+$ ]]; then
    # Singolo numero
    SELECTED_NUMBERS+=("$part")
  else
    error "Formato non valido: '$part'"
    exit 1
  fi
done

# Valida tutti i numeri selezionati
for num in "${SELECTED_NUMBERS[@]}"; do
  if [[ "$num" -lt 1 ]] || [[ "$num" -ge "$i" ]]; then
    error "Numero fuori range: $num (validi: 1-$((i-1)))"
    exit 1
  fi
done

# Rimuovi duplicati e ordina
SELECTED_NUMBERS=($(printf '%s\n' "${SELECTED_NUMBERS[@]}" | sort -nu))

echo ""
success "Selezionati ${#SELECTED_NUMBERS[@]} backup:"
for num in "${SELECTED_NUMBERS[@]}"; do
  ITEM="${ITEM_MAP[$num]}"
  TYPE="${ITEM_TYPE[$num]}"
  if [[ "$TYPE" == "dir" ]]; then
    echo "  [$num] 📁 $ITEM/"
  else
    echo "  [$num] 📄 $ITEM"
  fi
done

### CONFERMA DOWNLOAD ###
title "⚠️  Conferma Download"

echo "Stai per scaricare ${#SELECTED_NUMBERS[@]} backup:"
echo ""
for num in "${SELECTED_NUMBERS[@]}"; do
  ITEM="${ITEM_MAP[$num]}"
  TYPE="${ITEM_TYPE[$num]}"
  PATH="${ITEM_PATH[$num]}"
  
  # Estrai nome job per visualizzazione
  JOB_NAME="?"
  if [[ "$PATH" == *"job00-daily"* ]]; then
    JOB_NAME="job00-daily"
  elif [[ "$PATH" == *"job01-weekly"* ]]; then
    JOB_NAME="job01-weekly"
  fi
  
  if [[ "$TYPE" == "dir" ]]; then
    echo "  📁 [$JOB_NAME] $ITEM/ → $DOWNLOAD_DIR/$ITEM/"
  else
    echo "  📄 [$JOB_NAME] $ITEM → $DOWNLOAD_DIR/$ITEM"
  fi
done
echo ""
echo "Da: $RCLONE_REMOTE/..."
echo "A:  $DOWNLOAD_DIR/"
echo ""

if ! confirm "Vuoi procedere?" "y"; then
  error "Operazione annullata"
  exit 0
fi

### DOWNLOAD ###
title "⬇️  Download"

# Crea directory destinazione
mkdir -p "$DOWNLOAD_DIR"

# Array per tracciare successi/fallimenti
declare -a DOWNLOADED_ITEMS
declare -a FAILED_ITEMS

# Download di tutti gli elementi selezionati
for num in "${SELECTED_NUMBERS[@]}"; do
  SELECTED_ITEM="${ITEM_MAP[$num]}"
  SELECTED_TYPE="${ITEM_TYPE[$num]}"
  SELECTED_PATH="${ITEM_PATH[$num]}"
  
  echo ""
  log "[$num/${#SELECTED_NUMBERS[@]}] Processing: $SELECTED_ITEM from $SELECTED_PATH"
  
  if [[ "$SELECTED_TYPE" == "dir" ]]; then
    # Download directory completa
    log "  Scarico directory $SELECTED_ITEM/..."
    if rclone copy "$RCLONE_REMOTE/$SELECTED_PATH/$SELECTED_ITEM" "$DOWNLOAD_DIR/$SELECTED_ITEM" \
      --config="$RCLONE_CONF" \
      --s3-no-check-bucket \
      --progress; then
      
      # Verifica directory
      if [[ -d "$DOWNLOAD_DIR/$SELECTED_ITEM" ]]; then
        DIR_SIZE=$(du -sh "$DOWNLOAD_DIR/$SELECTED_ITEM" 2>/dev/null | cut -f1 || echo "N/A")
        success "  ✅ Directory: $SELECTED_ITEM/ ($DIR_SIZE)"
        DOWNLOADED_ITEMS+=("$SELECTED_ITEM/ ($DIR_SIZE)")
      else
        warn "  ⚠️  Directory non trovata dopo download: $SELECTED_ITEM/"
        FAILED_ITEMS+=("$SELECTED_ITEM/ (directory not found)")
      fi
    else
      error "  ❌ Download fallito: $SELECTED_ITEM/"
      FAILED_ITEMS+=("$SELECTED_ITEM/ (download failed)")
    fi
    
  else
    # Download file singolo
    log "  Scarico file $SELECTED_ITEM..."
    if rclone copy "$RCLONE_REMOTE/$SELECTED_PATH" "$DOWNLOAD_DIR/" \
      --config="$RCLONE_CONF" \
      --s3-no-check-bucket \
      --include "$SELECTED_ITEM" \
      --progress; then
      
      # Verifica file
      DOWNLOADED_FILE="$DOWNLOAD_DIR/$SELECTED_ITEM"
      if [[ -f "$DOWNLOADED_FILE" ]]; then
        FILE_SIZE=$(du -h "$DOWNLOADED_FILE" 2>/dev/null | cut -f1 || echo "N/A")
        success "  ✅ File: $SELECTED_ITEM ($FILE_SIZE)"
        DOWNLOADED_ITEMS+=("$SELECTED_ITEM ($FILE_SIZE)")
      else
        warn "  ⚠️  File non trovato dopo download: $SELECTED_ITEM"
        FAILED_ITEMS+=("$SELECTED_ITEM (file not found)")
      fi
    else
      error "  ❌ Download fallito: $SELECTED_ITEM"
      FAILED_ITEMS+=("$SELECTED_ITEM (download failed)")
    fi
  fi
done

### RIEPILOGO FINALE ###
echo ""
title "📊 Riepilogo Download"

if [[ ${#DOWNLOADED_ITEMS[@]} -gt 0 ]]; then
  success "Download completati: ${#DOWNLOADED_ITEMS[@]}/${#SELECTED_NUMBERS[@]}"
  echo ""
  for item in "${DOWNLOADED_ITEMS[@]}"; do
    echo "  ✅ $item"
  done
fi

if [[ ${#FAILED_ITEMS[@]} -gt 0 ]]; then
  echo ""
  error "Download falliti: ${#FAILED_ITEMS[@]}/${#SELECTED_NUMBERS[@]}"
  echo ""
  for item in "${FAILED_ITEMS[@]}"; do
    echo "  ❌ $item"
  done
fi

echo ""
if [[ ${#FAILED_ITEMS[@]} -eq 0 ]]; then
  success "✅ Operazione completata con successo!"
  echo ""
  echo "Tutti i backup scaricati in: $DOWNLOAD_DIR/"
  exit 0
else
  warn "⚠️  Operazione completata con errori"
  echo ""
  echo "Percorso download: $DOWNLOAD_DIR/"
  exit 1
fi
