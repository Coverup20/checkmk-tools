#!/usr/bin/env bash
# ydea-toolkit.sh — Toolkit completo per Ydea API v2
# Include login, gestione token e funzioni helper per ticket
set -euo pipefail

# ===== Caricamento configurazione da .env =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
  # shellcheck disable=SC1090,SC1091
  source "$SCRIPT_DIR/.env"
elif [[ -f "/opt/ydea-toolkit/.env" ]]; then
  # shellcheck disable=SC1091
  source "/opt/ydea-toolkit/.env"
fi

# ===== Config =====
: "${YDEA_BASE_URL:=https://my.ydea.cloud/app_api_v2}"
: "${YDEA_LOGIN_PATH:=/login}"

# Credenziali Login API
: "${YDEA_ID:=}"
: "${YDEA_API_KEY:=}"

# ID Utente per operazioni
: "${YDEA_USER_ID_CREATE_TICKET:=4675}"      # ID utente per creazione ticket
: "${YDEA_USER_ID_CREATE_NOTE:=4675}"        # ID utente per creazione note/commenti privati

: "${YDEA_TOKEN_FILE:=${HOME}/.ydea_token.json}"
: "${YDEA_EXPIRY_SKEW:=60}"
: "${YDEA_DEBUG:=0}"
: "${YDEA_LOG_FILE:=/var/log/ydea-toolkit.log}"
: "${YDEA_LOG_MAX_SIZE:=10485760}"  # 10MB
: "${YDEA_LOG_LEVEL:=INFO}"  # DEBUG, INFO, WARN, ERROR
: "${YDEA_TRACKING_FILE:=/var/log/ydea-tickets-tracking.json}"
: "${YDEA_TRACKING_RETENTION_DAYS:=365}"  # Mantieni ticket risolti per N giorni (1 anno)

CURL_OPTS=(
  --fail-with-body
  --show-error
  --silent
  --connect-timeout 10
  --max-time 30
)

# ===== Logging System =====
log_rotate() {
  if [[ -f "$YDEA_LOG_FILE" ]]; then
    local size
    size=$(stat -f%z "$YDEA_LOG_FILE" 2>/dev/null || stat -c%s "$YDEA_LOG_FILE" 2>/dev/null || echo 0)
    if [[ "$size" -gt "$YDEA_LOG_MAX_SIZE" ]]; then
      mv "$YDEA_LOG_FILE" "${YDEA_LOG_FILE}.1" 2>/dev/null || true
      [[ -f "${YDEA_LOG_FILE}.1" ]] && gzip "${YDEA_LOG_FILE}.1" 2>/dev/null || true
    fi
  fi
}

log_write() {
  local level="$1"; shift
  local message="$*"
  local timestamp
  timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
  
  # Log rotation check
  log_rotate
  
  # Write to log file
  echo "[$timestamp] [$level] [PID:$$] $message" >> "$YDEA_LOG_FILE" 2>/dev/null || true
}

log_debug() { 
  [[ "${YDEA_DEBUG}" == "1" ]] && echo "🔍 $*" >&2 || true
  log_write "DEBUG" "$*"
}

log_info() { 
  echo "ℹ️  $*" >&2
  log_write "INFO" "$*"
}

log_success() { 
  echo "✅ $*" >&2
  log_write "INFO" "SUCCESS: $*"
}

log_warn() {
  echo "⚠️  $*" >&2
  log_write "WARN" "$*"
}

log_error() { 
  echo "❌ $*" >&2
  log_write "ERROR" "$*"
}

log_api_call() {
  local method="$1"
  local url="$2"
  local status="${3:-}"
  log_write "API" "$method $url → HTTP $status"
}

# Compatibility aliases (manteniamo retrocompatibilità)
need() { command -v "$1" >/dev/null 2>&1 || { log_error "Manca '$1' nel PATH"; exit 127; }; }
debug() { log_debug "$@"; }
info() { log_info "$@"; }
success() { log_success "$@"; }
error() { log_error "$@"; }

# ===== Persistenza Token =====
save_token() {
  local token="$1"
  local now exp
  now="$(date -u +%s)"
  exp="$(( now + 3600 ))"
  jq -n --arg token "$token" --arg now "$now" --arg exp "$exp" \
     '{token:$token, scheme:"Bearer", obtained_at: ($now|tonumber), expires_at: ($exp|tonumber)}' \
     > "$YDEA_TOKEN_FILE"
  log_debug "Token salvato in $YDEA_TOKEN_FILE (scade: $(date -d "@$exp" 2>/dev/null || date -r "$exp"))"
  log_write "AUTH" "Token ottenuto e salvato, scadenza: $(date -d "@$exp" 2>/dev/null || date -r "$exp")"
}

load_token() { [[ -f "$YDEA_TOKEN_FILE" ]] && jq -r '.token // empty' "$YDEA_TOKEN_FILE"; }
expires_at() { [[ -f "$YDEA_TOKEN_FILE" ]] && jq -r '.expires_at // 0' "$YDEA_TOKEN_FILE"; }

token_is_fresh() {
  [[ -f "$YDEA_TOKEN_FILE" ]] || return 1
  local now exp skew
  now="$(date -u +%s)"
  exp="$(expires_at)"
  skew="${YDEA_EXPIRY_SKEW}"
  if [[ "$now" -lt $(( exp - skew )) ]]; then
    log_debug "Token valido (scade tra $(( exp - now )) secondi)"
    return 0
  else
    log_debug "Token scaduto o in scadenza"
    return 1
  fi
}

# ===== Login =====
ydea_login() {
  need curl; need jq
  log_info "Tentativo login a Ydea Cloud..."
  
  [[ -n "${YDEA_ID}" && -n "${YDEA_API_KEY}" ]] || {
    log_error "YDEA_ID e YDEA_API_KEY non impostati"
    echo "Esempio:" >&2
    echo "  export YDEA_ID='tuo_id'" >&2
    echo "  export YDEA_API_KEY='tua_chiave'" >&2
    exit 2
  }
  
  local url="${YDEA_BASE_URL%/}${YDEA_LOGIN_PATH}"
  local body
  body="$(jq -n --arg i "$YDEA_ID" --arg k "$YDEA_API_KEY" '{id:$i, api_key:$k}')"

  log_debug "POST $url"
  local resp
  resp="$(curl "${CURL_OPTS[@]}" -X POST \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "$body" \
    "$url" 2>&1)" || {
    log_error "Login fallito: curl error $?"
    log_write "API" "POST $url → FAILED"
    echo "$resp" | jq . 2>/dev/null || echo "$resp"
    exit 1
  }
  
  log_api_call "POST" "$url" "200"

  local token
  token="$(printf '%s' "$resp" | jq -r '.token // .access_token // .jwt // .id_token // empty')"

  if [[ -z "$token" || "$token" == "null" ]]; then
    log_error "Login fallito: risposta senza token"
    echo "$resp" | jq . 2>/dev/null || echo "$resp"
    exit 1
  fi
  
  save_token "$token"
  log_success "Login effettuato (token valido ~1h)"
}

ensure_token() {
  if token_is_fresh; then
    log_debug "Token ancora valido"
  else
    log_info "Token scaduto o mancante, effettuo il login..."
    ydea_login
  fi
}

# ===== Chiamate API Generiche =====
ydea_api() {
  need curl; need jq
  local method="${1:-}"; shift || true
  local path="${1:-}"; shift || true
  [[ -n "$method" && -n "$path" ]] || { 
    log_error "Uso: ydea_api <GET|POST|PUT|PATCH|DELETE> </path> [json_body]"
    return 2
  }

  ensure_token
  local token url
  token="$(load_token)"
  url="${YDEA_BASE_URL%/}/${path#/}"

  log_debug "$method $url"
  
  # Log request body se presente
  if [[ "$#" -gt 0 ]]; then
    log_write "REQUEST" "$method $url | Body: ${1:0:200}..."
  fi

  local resp http_body http_code
  
  # Funzione helper per fare la chiamata
  make_request() {
    if [[ "$#" -gt 0 ]]; then
      curl "${CURL_OPTS[@]}" -w '\n%{http_code}' -X "$method" \
        -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${token}" \
        -d "$1" \
        "$url" 2>&1
    else
      curl "${CURL_OPTS[@]}" -w '\n%{http_code}' -X "$method" \
        -H "Accept: application/json" \
        -H "Authorization: Bearer ${token}" \
        "$url" 2>&1
    fi
  }

  # Prima richiesta
  if ! resp="$(make_request "$@")"; then
    log_error "API call fallita: $method $url"
    log_api_call "$method" "$url" "ERROR"
    return 1
  fi

  http_body="$(printf '%s' "$resp" | sed '$d')"
  http_code="$(printf '%s' "$resp" | tail -n1)"
  
  log_api_call "$method" "$url" "$http_code"

  # Se 401, refresh token e retry
  if [[ "$http_code" == "401" ]]; then
    log_warn "Token scaduto (401), rinnovo e riprovo..."
    ydea_login
    token="$(load_token)"
    
    resp="$(make_request "$@")"
    http_body="$(printf '%s' "$resp" | sed '$d')"
    http_code="$(printf '%s' "$resp" | tail -n1)"
    log_api_call "$method" "$url" "$http_code (retry dopo refresh token)"
  fi

  log_debug "HTTP $http_code"
  
  # Log response (primi 500 caratteri)
  if [[ "${YDEA_DEBUG}" == "1" ]]; then
    log_write "RESPONSE" "$method $url → $http_code | Body: ${http_body:0:500}..."
  fi
  
  printf '%s' "$http_body"
  [[ "$http_code" =~ ^2[0-9][0-9]$ ]]
}

# ===== FUNZIONI HELPER PER TICKET =====

# Lista tutti i ticket con filtri opzionali
list_tickets() {
  local limit="${1:-50}"
  local status="${2:-}"
  local path="/tickets?limit=$limit"
  [[ -n "$status" ]] && path="${path}&status=$status"
  
  log_info "Recupero ticket (limit: $limit${status:+, status: $status})..."
  ydea_api GET "$path"
}

# Dettagli di un singolo ticket
get_ticket() {
  local ticket_id="$1"
  [[ -n "$ticket_id" ]] || { log_error "Ticket ID richiesto"; return 2; }
  
  log_info "Recupero ticket #$ticket_id..."
  ydea_api GET "/tickets/$ticket_id"
}

# Crea un nuovo ticket
create_ticket() {
  local title="$1"
  local description="$2"
  local priority="${3:-normal}"
  local category_id="${4:-}"
  
  [[ -z "$title" ]] && { log_error "Specifica almeno il titolo"; return 1; }
  
  # Mappa priorità testuale a numeri (1=bassa, 2=normale, 3=alta, 4=urgente, 5=critica)
  local priority_num=2
  case "${priority,,}" in
    low|bassa)        priority_num=1 ;;
    normal|normale)   priority_num=2 ;;
    high|alta)        priority_num=3 ;;
    urgent|urgente)   priority_num=4 ;;
    critical|critica) priority_num=5 ;;
  esac
  
  # Valori predefiniti da variabili ambiente o fallback
  local azienda="${YDEA_AZIENDA:-2339268}"
  local contatto="${YDEA_CONTATTO:-773763}"
  local tipo="${YDEA_TIPO:-Nethserver}"
  
  local body
  body=$(jq -n \
    --arg title "$title" \
    --arg desc "${description:-}" \
    --argjson prio "$priority_num" \
    --argjson azienda "$azienda" \
    --argjson contatto "$contatto" \
    --argjson anagrafica "$azienda" \
    --arg fonte "Partner portal" \
    --arg tipo "$tipo" \
    --arg addebito "F" \
    --arg cat "$category_id" \
    '{
      titolo: $title,
      testo: $desc,
      priorita: $prio,
      azienda: $azienda,
      contatto: $contatto,
      anagrafica_id: $anagrafica,
      fonte: $fonte,
      tipo: $tipo,
      condizioneAddebito: $addebito
    } + (if $cat != "" then {categoria: $cat} else {} end)'
  )
  
  log_info "Creazione ticket: $title (priorità: $priority)"
  ydea_api POST "/ticket" "$body"
}

# Aggiorna un ticket
update_ticket() {
  local ticket_id="$1"
  local json_updates="$2"
  
  [[ -z "$ticket_id" || -z "$json_updates" ]] && { log_error "Specifica ticket_id e json_updates"; return 1; }
  
  log_info "Aggiornamento ticket #$ticket_id..."
  ydea_api PATCH "/tickets/$ticket_id" "$json_updates"
}

# Chiudi un ticket
close_ticket() {
  local ticket_id="$1"
  local note="${2:-Ticket chiuso}"
  
  [[ -z "$ticket_id" ]] && { log_error "Specifica ticket_id"; return 1; }
  
  local body
  body=$(jq -n --arg note "$note" '{status: "closed", closing_note: $note}')
  
  log_info "Chiusura ticket #$ticket_id..."
  ydea_api PATCH "/tickets/$ticket_id" "$body"
}

# Aggiungi commento a un ticket
add_comment() {
  local ticket_id="$1"
  local comment="$2"
  local is_public="${3:-false}"
  
  [[ -z "$ticket_id" || -z "$comment" ]] && {
    log_error "Uso: add_comment <ticket_id> '<commento>' [pubblico:true|false]"
    return 1
  }
  
  # ID utente per campo creatoda (usa variabile personalizzabile)
  local user_id="${YDEA_USER_ID_CREATE_NOTE:-4675}"
  
  local body
  body=$(jq -n \
    --argjson tid "$ticket_id" \
    --arg desc "$comment" \
    --argjson pub "$is_public" \
    --argjson uid "$user_id" \
    '{ticket_id: $tid, atk: {descrizione: $desc, pubblico: $pub, creatoda: $uid}}')
  
  log_info "Aggiunta commento a ticket #$ticket_id (pubblico: $is_public)..."
  ydea_api POST "/ticket/atk" "$body"
}

# Cerca ticket per testo
search_tickets() {
  local query="$1"
  local limit="${2:-20}"
  
  [[ -z "$query" ]] && { log_error "Specifica una query di ricerca"; return 1; }
  
  log_info "Ricerca ticket: '$query'..."
  ydea_api GET "/tickets?search=$(printf %s "$query" | jq -sRr @uri)&limit=$limit"
}

# Lista categorie disponibili
list_categories() {
  log_info "Recupero categorie..."
  ydea_api GET "/categories"
}

# Lista utenti
list_users() {
  local limit="${1:-50}"
  log_info "Recupero utenti (limit: $limit)..."
  ydea_api GET "/users?limit=$limit"
}

# ===== Tracking Ticket System =====

# Inizializza il file di tracking se non esiste
init_tracking_file() {
  if [[ ! -f "$YDEA_TRACKING_FILE" ]]; then
    echo '{"tickets":[],"last_update":""}' > "$YDEA_TRACKING_FILE"
    log_debug "File tracking inizializzato: $YDEA_TRACKING_FILE"
  fi
}

# Aggiungi ticket al tracking
track_ticket() {
  local ticket_id="$1"
  local codice="${2:-}"
  local host="${3:-}"
  local service="${4:-}"
  local description="${5:-}"
  
  init_tracking_file
  
  local now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  
  # Recupera dettagli ticket da API
  local ticket_data
  ticket_data=$(ydea_api GET "/tickets/$ticket_id" 2>/dev/null || echo "{}")
  
  local stato=$(echo "$ticket_data" | jq -r '.stato // "Sconosciuto"')
  local titolo=$(echo "$ticket_data" | jq -r '.titolo // ""')
  
  # Aggiungi al tracking
  local new_entry
  new_entry=$(jq -n \
    --arg tid "$ticket_id" \
    --arg code "$codice" \
    --arg host "$host" \
    --arg svc "$service" \
    --arg desc "$description" \
    --arg title "$titolo" \
    --arg stato "$stato" \
    --arg created "$now" \
    '{
      ticket_id: ($tid|tonumber),
      codice: $code,
      host: $host,
      service: $svc,
      description: $desc,
      titolo: $title,
      stato: $stato,
      created_at: $created,
      last_update: $created,
      resolved_at: null,
      checks_count: 1
    }')
  
  # Verifica se già tracciato
  local exists
  exists=$(jq --arg tid "$ticket_id" '.tickets[] | select(.ticket_id == ($tid|tonumber)) | .ticket_id' "$YDEA_TRACKING_FILE" 2>/dev/null || echo "")
  
  if [[ -n "$exists" ]]; then
    log_warn "Ticket #$ticket_id già tracciato, aggiorno contatore"
    jq --arg tid "$ticket_id" --arg now "$now" \
      '.tickets |= map(if .ticket_id == ($tid|tonumber) then .checks_count += 1 | .last_update = $now else . end) | .last_update = $now' \
      "$YDEA_TRACKING_FILE" > "${YDEA_TRACKING_FILE}.tmp" && mv "${YDEA_TRACKING_FILE}.tmp" "$YDEA_TRACKING_FILE"
  else
    log_info "Aggiunto ticket #$ticket_id al tracking"
    jq --argjson entry "$new_entry" --arg now "$now" \
      '.tickets += [$entry] | .last_update = $now' \
      "$YDEA_TRACKING_FILE" > "${YDEA_TRACKING_FILE}.tmp" && mv "${YDEA_TRACKING_FILE}.tmp" "$YDEA_TRACKING_FILE"
  fi
  
  log_success "Ticket #$ticket_id ($codice) tracciato - Host: $host, Service: $service"
}

# Aggiorna stato ticket tracciati
update_tracked_tickets() {
  init_tracking_file
  
  local count=0
  local updated=0
  local resolved=0
  local now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  
  log_info "Aggiornamento stati ticket tracciati..."
  
  # Leggi tutti i ticket non risolti
  local tickets
  tickets=$(jq -r '.tickets[] | select(.resolved_at == null) | .ticket_id' "$YDEA_TRACKING_FILE" 2>/dev/null || echo "")
  
  if [[ -z "$tickets" ]]; then
    log_info "Nessun ticket da aggiornare"
    return 0
  fi
  
  while IFS= read -r ticket_id; do
    [[ -z "$ticket_id" ]] && continue
    count=$((count + 1))
    
    log_debug "Controllo ticket #$ticket_id..."
    
    # Recupera stato corrente
    local ticket_data
    ticket_data=$(ydea_api GET "/tickets/$ticket_id" 2>/dev/null || echo "{}")
    
    if [[ "$ticket_data" == "{}" ]]; then
      log_warn "Ticket #$ticket_id non trovato, potrebbe essere stato eliminato"
      continue
    fi
    
    local stato=$(echo "$ticket_data" | jq -r '.stato // "Sconosciuto"')
    
    # Controlla se risolto
    if [[ "$stato" =~ ^(Effettuato|Chiuso|Completato|Risolto)$ ]]; then
      log_success "✅ Ticket #$ticket_id RISOLTO (stato: $stato)"
      jq --arg tid "$ticket_id" --arg stato "$stato" --arg now "$now" \
        '.tickets |= map(if .ticket_id == ($tid|tonumber) then .stato = $stato | .resolved_at = $now | .last_update = $now else . end) | .last_update = $now' \
        "$YDEA_TRACKING_FILE" > "${YDEA_TRACKING_FILE}.tmp" && mv "${YDEA_TRACKING_FILE}.tmp" "$YDEA_TRACKING_FILE"
      resolved=$((resolved + 1))
    else
      # Solo aggiorna stato
      jq --arg tid "$ticket_id" --arg stato "$stato" --arg now "$now" \
        '.tickets |= map(if .ticket_id == ($tid|tonumber) then .stato = $stato | .last_update = $now | .checks_count += 1 else . end) | .last_update = $now' \
        "$YDEA_TRACKING_FILE" > "${YDEA_TRACKING_FILE}.tmp" && mv "${YDEA_TRACKING_FILE}.tmp" "$YDEA_TRACKING_FILE"
      updated=$((updated + 1))
    fi
  done <<< "$tickets"
  
  log_info "Aggiornamento completato: $count ticket controllati, $updated aggiornati, $resolved risolti"
}

# Pulisci ticket risolti vecchi
cleanup_resolved_tickets() {
  init_tracking_file
  
  local retention_seconds=$((YDEA_TRACKING_RETENTION_DAYS * 86400))
  local now_epoch=$(date -u +%s)
  local cutoff_epoch=$((now_epoch - retention_seconds))
  local cutoff_date=$(date -u -d "@$cutoff_epoch" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -r "$cutoff_epoch" +"%Y-%m-%dT%H:%M:%SZ")
  
  log_info "Pulizia ticket risolti più vecchi di $YDEA_TRACKING_RETENTION_DAYS giorni (prima di $cutoff_date)..."
  
  local before_count
  before_count=$(jq '.tickets | length' "$YDEA_TRACKING_FILE")
  
  jq --arg cutoff "$cutoff_date" \
    '.tickets |= map(select(.resolved_at == null or .resolved_at > $cutoff))' \
    "$YDEA_TRACKING_FILE" > "${YDEA_TRACKING_FILE}.tmp" && mv "${YDEA_TRACKING_FILE}.tmp" "$YDEA_TRACKING_FILE"
  
  local after_count
  after_count=$(jq '.tickets | length' "$YDEA_TRACKING_FILE")
  local removed=$((before_count - after_count))
  
  if [[ $removed -gt 0 ]]; then
    log_success "Rimossi $removed ticket risolti vecchi"
  else
    log_info "Nessun ticket da rimuovere"
  fi
}

# Mostra statistiche ticket tracciati
show_tracking_stats() {
  init_tracking_file
  
  local total open resolved
  total=$(jq '.tickets | length' "$YDEA_TRACKING_FILE")
  open=$(jq '[.tickets[] | select(.resolved_at == null)] | length' "$YDEA_TRACKING_FILE")
  resolved=$(jq '[.tickets[] | select(.resolved_at != null)] | length' "$YDEA_TRACKING_FILE")
  
  echo "📊 Statistiche Ticket Tracking"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "Totale ticket tracciati: $total"
  echo "  ├─ Aperti: $open"
  echo "  └─ Risolti: $resolved"
  echo ""
  
  if [[ $open -gt 0 ]]; then
    echo "🔴 Ticket Aperti:"
    jq -r '.tickets[] | select(.resolved_at == null) | "  [#\(.ticket_id)] \(.codice) - \(.host)/\(.service) - Stato: \(.stato) - Creato: \(.created_at)"' "$YDEA_TRACKING_FILE"
    echo ""
  fi
  
  if [[ $resolved -gt 0 ]]; then
    echo "✅ Ultimi 5 Ticket Risolti:"
    jq -r '.tickets[] | select(.resolved_at != null) | "\(.resolved_at) | #\(.ticket_id) | \(.codice) | \(.host)/\(.service)"' "$YDEA_TRACKING_FILE" | sort -r | head -5 | while IFS='|' read -r date tid code host; do
      echo "  [$date] $tid $code - $host"
    done
    echo ""
  fi
  
  # Tempo medio di risoluzione
  local avg_resolution
  avg_resolution=$(jq -r '[.tickets[] | select(.resolved_at != null) | 
    (((.resolved_at | fromdateiso8601) - (.created_at | fromdateiso8601)) / 3600)] | 
    if length > 0 then (add / length | floor) else 0 end' "$YDEA_TRACKING_FILE" 2>/dev/null || echo "0")
  
  if [[ "$avg_resolution" != "0" ]]; then
    echo "⏱️  Tempo medio risoluzione: ~$avg_resolution ore"
  fi
}

# Lista tutti i ticket tracciati
list_tracked_tickets() {
  init_tracking_file
  jq '.' "$YDEA_TRACKING_FILE"
}

# ===== Configurazione Interattiva =====
interactive_config() {
  local env_file="${TOOLKIT_DIR:-.}/.env"
  
  echo "🔧 Configurazione Interattiva Ydea Toolkit"
  echo "=========================================="
  echo ""
  
  # Leggi valori attuali se esistono
  local current_id=""
  local current_key=""
  local current_ticket_id=""
  local current_note_id=""
  
  if [[ -f "$env_file" ]]; then
    source "$env_file" 2>/dev/null || true
    current_id="${YDEA_ID:-}"
    current_key="${YDEA_API_KEY:-}"
    current_ticket_id="${YDEA_USER_ID_CREATE_TICKET:-4675}"
    current_note_id="${YDEA_USER_ID_CREATE_NOTE:-4675}"
  fi
  
  echo "📋 CREDENZIALI API (obbligatorie)"
  echo "   Ottienile da: https://my.ydea.cloud → Impostazioni → La mia azienda → API"
  echo ""
  
  # YDEA_ID
  if [[ -n "$current_id" ]]; then
    read -p "YDEA_ID [$current_id]: " new_id
    new_id="${new_id:-$current_id}"
  else
    read -p "YDEA_ID: " new_id
    while [[ -z "$new_id" ]]; do
      echo "❌ YDEA_ID è obbligatorio!"
      read -p "YDEA_ID: " new_id
    done
  fi
  
  # YDEA_API_KEY
  if [[ -n "$current_key" ]]; then
    read -p "YDEA_API_KEY [***nascosta***] (invio per mantenere): " new_key
    new_key="${new_key:-$current_key}"
  else
    read -p "YDEA_API_KEY: " new_key
    while [[ -z "$new_key" ]]; do
      echo "❌ YDEA_API_KEY è obbligatoria!"
      read -p "YDEA_API_KEY: " new_key
    done
  fi
  
  echo ""
  echo "👤 ID UTENTE PER OPERAZIONI (opzionali)"
  echo "   Usa gli ID degli utenti Ydea per attribuire creazioni"
  echo ""
  
  # YDEA_USER_ID_CREATE_TICKET
  read -p "ID utente creazione ticket [$current_ticket_id]: " new_ticket_id
  new_ticket_id="${new_ticket_id:-$current_ticket_id}"
  
  # YDEA_USER_ID_CREATE_NOTE
  read -p "ID utente creazione note/commenti [$current_note_id]: " new_note_id
  new_note_id="${new_note_id:-$current_note_id}"
  
  echo ""
  echo "📝 GESTIONE LOG E TRACKING (opzionali)"
  echo "   Configurazione avanzata per logging e monitoraggio"
  echo ""
  
  # Log file location
  local current_log_file="${YDEA_LOG_FILE:-/var/log/ydea-toolkit.log}"
  read -p "Percorso file log [$current_log_file]: " new_log_file
  new_log_file="${new_log_file:-$current_log_file}"
  
  # Log max size (in MB)
  local current_log_size_mb=$((${YDEA_LOG_MAX_SIZE:-10485760} / 1048576))
  read -p "Dimensione massima log in MB [$current_log_size_mb]: " new_log_size_mb
  new_log_size_mb="${new_log_size_mb:-$current_log_size_mb}"
  local new_log_size=$((new_log_size_mb * 1048576))
  
  # Log level
  local current_log_level="${YDEA_LOG_LEVEL:-INFO}"
  read -p "Livello log (DEBUG/INFO/WARN/ERROR) [$current_log_level]: " new_log_level
  new_log_level="${new_log_level:-$current_log_level}"
  new_log_level=$(echo "$new_log_level" | tr '[:lower:]' '[:upper:]')
  
  # Tracking file
  local current_tracking_file="${YDEA_TRACKING_FILE:-/var/log/ydea-tickets-tracking.json}"
  read -p "Percorso file tracking ticket [$current_tracking_file]: " new_tracking_file
  new_tracking_file="${new_tracking_file:-$current_tracking_file}"
  
  # Retention days
  local current_retention="${YDEA_TRACKING_RETENTION_DAYS:-365}"
  read -p "Giorni mantenimento ticket risolti [$current_retention]: " new_retention
  new_retention="${new_retention:-$current_retention}"
  
  echo ""
  echo "💾 Salvataggio configurazione in: $env_file"
  
  # Crea backup se esiste
  if [[ -f "$env_file" ]]; then
    cp "$env_file" "${env_file}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "   (backup creato: ${env_file}.backup.$(date +%Y%m%d_%H%M%S))"
  fi
  
  # Scrivi nuovo .env
  cat > "$env_file" <<EOF
# ===== YDEA TOOLKIT CONFIGURATION =====
# Generato il: $(date '+%Y-%m-%d %H:%M:%S')

# Credenziali API (OBBLIGATORIE)
export YDEA_ID="$new_id"
export YDEA_API_KEY="$new_key"

# ID Utente per operazioni (opzionali)
export YDEA_USER_ID_CREATE_TICKET=$new_ticket_id
export YDEA_USER_ID_CREATE_NOTE=$new_note_id

# ===== GESTIONE LOG E TRACKING =====
export YDEA_LOG_FILE="$new_log_file"
export YDEA_LOG_MAX_SIZE=$new_log_size
export YDEA_LOG_LEVEL="$new_log_level"
export YDEA_TRACKING_FILE="$new_tracking_file"
export YDEA_TRACKING_RETENTION_DAYS=$new_retention

# ===== CONFIGURAZIONI AVANZATE =====
# Decommentare e modificare se necessario

# export YDEA_BASE_URL="https://my.ydea.cloud/app_api_v2"
# export YDEA_TOKEN_FILE="\${HOME}/.ydea_token.json"
# export YDEA_DEBUG=0
EOF
  
  chmod 600 "$env_file"
  
  echo ""
  echo "✅ Configurazione salvata con successo!"
  echo ""
  echo "📝 Riepilogo:"
  echo "   YDEA_ID: $new_id"
  echo "   YDEA_API_KEY: ${new_key:0:10}***"
  echo "   ID creazione ticket: $new_ticket_id"
  echo "   ID creazione note: $new_note_id"
  echo ""
  echo "📊 Configurazione Log & Tracking:"
  echo "   File log: $new_log_file"
  echo "   Dimensione max: ${new_log_size_mb}MB"
  echo "   Livello log: $new_log_level"
  echo "   File tracking: $new_tracking_file"
  echo "   Retention giorni: $new_retention"
  echo ""
  echo "🧪 Test configurazione:"
  echo "   source $env_file"
  echo "   $0 login"
  echo ""
}

# ===== CLI =====
show_usage() {
  cat >&2 <<'USAGE'
🛠️  Ydea Toolkit - Gestione API v2

SETUP:
  export YDEA_ID="tuo_id"              # Da: Impostazioni → La mia azienda → API
  export YDEA_API_KEY="tua_chiave_api"
  
  # ID Utente per operazioni (opzionali)
  export YDEA_USER_ID_CREATE_TICKET=4675    # ID per creazione ticket
  export YDEA_USER_ID_CREATE_NOTE=4675      # ID per creazione note/commenti
  
  export YDEA_DEBUG=1                  # (opzionale) per debug verboso
  export YDEA_LOG_FILE=/path/log.log   # (default: /var/log/ydea-toolkit.log)

COMANDI:

  Autenticazione:
    login                              Effettua login e salva token

  API Generiche:
    api <METHOD> </path> [json_body]   Chiamata API generica
    
  Ticket - Lista e Ricerca:
    list [limit] [status]              Lista ticket (default: 50)
    search <query> [limit]             Cerca ticket per testo
    get <ticket_id>                    Dettagli ticket specifico
    
  Ticket - Creazione e Modifica:
    create <title> [description] [priority] [category_id]
    update <ticket_id> '<json>'        Aggiorna ticket (formato JSON)
    close <ticket_id> [nota]           Chiudi ticket
    comment <ticket_id> '<testo>'      Aggiungi commento
  
  Tracking Ticket (Monitoraggio Stati):
    track <ticket_id> <codice> <host> <service> [desc]
                                       Aggiungi ticket al tracking automatico
    update-tracking                    Aggiorna stati di tutti i ticket tracciati
    cleanup-tracking                   Rimuovi ticket risolti vecchi
    list-tracking                      Mostra JSON completo ticket tracciati
    stats                              Statistiche ticket (aperti/risolti/tempi)
    
  Log e Debug:
    logs [lines]                       Mostra ultimi N log (default: 50)
    clearlog                           Pulisci file di log
  
  Configurazione:
    config                             Configurazione interattiva (ID, API key, user ID)
    
  Altro:
    categories                         Lista categorie
    users [limit]                      Lista utenti

ESEMPI:

  # Configurazione iniziale interattiva
  ./ydea-toolkit.sh config
  
  # Login iniziale
  ./ydea-toolkit.sh login

  # Lista ultimi 10 ticket aperti
  ./ydea-toolkit.sh list 10 open | jq .

  # Crea nuovo ticket
  ./ydea-toolkit.sh create "Server down" "Il server web non risponde" high

  # Cerca ticket
  ./ydea-toolkit.sh search "errore database" | jq '.data[] | {id, title, status}'

  # Aggiungi commento
  ./ydea-toolkit.sh comment 12345 "Problema risolto riavviando il servizio"

  # Chiudi ticket
  ./ydea-toolkit.sh close 12345 "Risolto con riavvio"

  # Tracking ticket da CheckMK
  ./ydea-toolkit.sh track 12345 "TK25/003376" "server-web" "Apache Status" "Alert da CheckMK"
  
  # Visualizza statistiche tracking
  ./ydea-toolkit.sh stats
  
  # Aggiorna tutti i ticket tracciati
  ./ydea-toolkit.sh update-tracking
  
  # Visualizza log
  ./ydea-toolkit.sh logs 100

  # Chiamata API custom
  ./ydea-toolkit.sh api GET /tickets/12345/history | jq .

VARIABILI AMBIENTE:
  # Credenziali API (OBBLIGATORIE)
  YDEA_ID                    ID account API Ydea
  YDEA_API_KEY               Chiave API Ydea
  
  # ID Utente per operazioni (opzionali)
  YDEA_USER_ID_CREATE_TICKET (default: 4675) ID per creazione ticket
  YDEA_USER_ID_CREATE_NOTE   (default: 4675) ID per creazione note/commenti
  
  # Configurazioni generali
  YDEA_BASE_URL              (default: https://my.ydea.cloud/app_api_v2)
  YDEA_TOKEN_FILE            (default: ~/.ydea_token.json)
  YDEA_LOG_FILE              (default: /var/log/ydea-toolkit.log)
  YDEA_LOG_MAX_SIZE          (default: 10485760 = 10MB)
  YDEA_TRACKING_FILE         (default: /var/log/ydea-tickets-tracking.json)
  YDEA_TRACKING_RETENTION_DAYS (default: 365 giorni)
  YDEA_EXPIRY_SKEW           (default: 60 secondi)
  YDEA_DEBUG                 (default: 0, imposta 1 per debug)

LOG:
  Tutte le operazioni vengono registrate in: $YDEA_LOG_FILE
  Include: timestamp, livello (INFO/WARN/ERROR), PID, chiamate API con response code

TRACKING:
  I ticket possono essere tracciati automaticamente per monitorare il loro stato.
  File tracking: $YDEA_TRACKING_FILE
  - Mantiene storico ticket creati da monitoring
  - Aggiorna automaticamente gli stati
  - Rimuove ticket risolti dopo $YDEA_TRACKING_RETENTION_DAYS giorni
  - Fornisce statistiche e tempi di risoluzione

USAGE
}

# Log viewer
show_logs() {
  local lines="${1:-50}"
  if [[ -f "$YDEA_LOG_FILE" ]]; then
    tail -n "$lines" "$YDEA_LOG_FILE"
  else
    echo "File di log non trovato: $YDEA_LOG_FILE" >&2
    return 1
  fi
}

# Clear log
clear_log() {
  if [[ -f "$YDEA_LOG_FILE" ]]; then
    : > "$YDEA_LOG_FILE"
    log_info "File di log pulito: $YDEA_LOG_FILE"
  else
    log_warn "File di log non esistente: $YDEA_LOG_FILE"
  fi
}

case "${1:-}" in
  login)       ydea_login ;;
  api)         shift; ydea_api "$@" ;;
  
  # Configuration
  config)      interactive_config ;;
  
  # Ticket operations
  list)        shift; list_tickets "$@" ;;
  get)         shift; get_ticket "$@" ;;
  create)      shift; create_ticket "$@" ;;
  update)      shift; update_ticket "$@" ;;
  close)       shift; close_ticket "$@" ;;
  comment)     shift; add_comment "$@" ;;
  search)      shift; search_tickets "$@" ;;
  
  # Tracking operations
  track)              shift; track_ticket "$@" ;;
  update-tracking)    update_tracked_tickets ;;
  cleanup-tracking)   cleanup_resolved_tickets ;;
  list-tracking)      list_tracked_tickets ;;
  stats)              show_tracking_stats ;;
  
  # Log operations
  logs)        shift; show_logs "$@" ;;
  clearlog)    clear_log ;;
  
  # Other
  categories)  list_categories ;;
  users)       shift; list_users "$@" ;;
  
  -h|--help|help) show_usage; exit 0 ;;
  *)           show_usage; exit 1 ;;
esac
