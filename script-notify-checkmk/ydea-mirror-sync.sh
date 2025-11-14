#!/bin/bash
# ydea-mirror-sync.sh - Sincronizza mirror locale con tutti i ticket Ydea
# Esegui ogni 5 minuti con cron

set -euo pipefail

# === CONFIGURAZIONE ===
YDEA_TOOLKIT="/opt/ydea-toolkit/ydea-toolkit.sh"
MIRROR_DIR="/opt/omd/sites/monitoring/var/ydea"
MIRROR_FILE="$MIRROR_DIR/mirror.json"
MIRROR_LOCK="$MIRROR_DIR/mirror.lock"
SYNC_LOG="$MIRROR_DIR/sync.log"
ARCHIVE_DIR="$MIRROR_DIR/archive"

# Limite ticket per chiamata (default 100)
FETCH_LIMIT=100

# === FUNZIONI ===
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$SYNC_LOG"
}

# Inizializza directory
init_dirs() {
  mkdir -p "$MIRROR_DIR" "$ARCHIVE_DIR"
  touch "$SYNC_LOG"
  
  # Crea mirror vuoto se non esiste
  if [[ ! -f "$MIRROR_FILE" ]]; then
    echo '{"tickets": [], "last_sync": 0, "total_count": 0}' > "$MIRROR_FILE"
    chmod 666 "$MIRROR_FILE"
  fi
}

# Scarica tutti i ticket da Ydea
fetch_all_tickets() {
  local all_tickets="[]"
  local page=1
  local has_more=true
  
  log "Inizio fetch ticket da Ydea..."
  
  while [[ "$has_more" == "true" ]]; do
    log "Fetch pagina $page (limit: $FETCH_LIMIT)..."
    
    # Usa ydea-toolkit per ottenere lista ticket
    local result
    result=$("$YDEA_TOOLKIT" list "$FETCH_LIMIT" 2>&1) || {
      log "ERRORE: Impossibile recuperare ticket (pagina $page): $result"
      return 1
    }
    
    # Estrai JSON dalla risposta (ultima riga JSON valida)
    local json_line
    json_line=$(echo "$result" | grep -E '^\{.*\}$' | tail -n1)
    
    if [[ -z "$json_line" ]]; then
      log "WARN: Nessun JSON valido nella risposta (pagina $page)"
      break
    fi
    
    # Estrai array ticket dalla risposta
    local page_tickets
    page_tickets=$(echo "$json_line" | jq -c '.data // .tickets // []' 2>/dev/null)
    
    if [[ -z "$page_tickets" || "$page_tickets" == "[]" ]]; then
      log "Fine paginazione (nessun ticket in pagina $page)"
      break
    fi
    
    # Conta ticket in questa pagina
    local page_count
    page_count=$(echo "$page_tickets" | jq 'length')
    log "Recuperati $page_count ticket dalla pagina $page"
    
    # Merge con risultati precedenti
    all_tickets=$(echo "$all_tickets" | jq --argjson new "$page_tickets" '. + $new')
    
    # Se meno di FETCH_LIMIT, non ci sono altre pagine
    if [[ "$page_count" -lt "$FETCH_LIMIT" ]]; then
      has_more=false
    else
      ((page++))
    fi
  done
  
  echo "$all_tickets"
}

# Salva mirror con timestamp
save_mirror() {
  local tickets="$1"
  local count
  count=$(echo "$tickets" | jq 'length')
  
  local mirror_data
  mirror_data=$(jq -n \
    --argjson tickets "$tickets" \
    --arg timestamp "$(date -u +%s)" \
    --arg count "$count" \
    '{
      tickets: $tickets,
      last_sync: ($timestamp | tonumber),
      total_count: ($count | tonumber),
      sync_date: (now | strftime("%Y-%m-%d %H:%M:%S"))
    }')
  
  # Atomic write con lock
  (
    flock -x -w 10 200 || {
      log "WARN: Impossibile ottenere lock su mirror, skip"
      return 1
    }
    
    echo "$mirror_data" > "$MIRROR_FILE"
    chmod 666 "$MIRROR_FILE"
    
  ) 200>"$MIRROR_LOCK"
  
  log "Mirror aggiornato: $count ticket salvati"
}

# Archivia snapshot mensile
archive_snapshot() {
  local month
  month=$(date '+%Y-%m')
  local archive_file="$ARCHIVE_DIR/snapshot-$month.json"
  
  # Copia mirror corrente in archivio mensile
  if [[ -f "$MIRROR_FILE" ]]; then
    cp "$MIRROR_FILE" "$archive_file"
    log "Snapshot mensile salvato: $archive_file"
  fi
  
  # Cleanup archivi vecchi (>6 mesi)
  find "$ARCHIVE_DIR" -name "snapshot-*.json" -mtime +180 -delete 2>/dev/null || true
}

# === MAIN ===
main() {
  log "=== Avvio sincronizzazione Ydea mirror ==="
  
  # Inizializza
  init_dirs
  
  # Scarica tutti i ticket
  local tickets
  tickets=$(fetch_all_tickets) || {
    log "ERRORE: Fetch ticket fallito"
    return 1
  }
  
  # Salva mirror
  save_mirror "$tickets" || {
    log "ERRORE: Salvataggio mirror fallito"
    return 1
  }
  
  # Archivia snapshot il primo del mese
  if [[ $(date '+%d') == "01" ]]; then
    archive_snapshot
  fi
  
  log "=== Sincronizzazione completata ==="
}

main "$@"
