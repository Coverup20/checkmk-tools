#!/usr/bin/env bash
# ydea-toolkit.sh — Toolkit completo per Ydea API v2
# Include login, gestione token e funzioni helper per ticket
set -euo pipefail

# ===== Config =====
: "${YDEA_BASE_URL:=https://my.ydea.cloud/app_api_v2}"
: "${YDEA_LOGIN_PATH:=/login}"
: "${YDEA_ID:=}"
: "${YDEA_API_KEY:=}"
: "${YDEA_TOKEN_FILE:=${HOME}/.ydea_token.json}"
: "${YDEA_EXPIRY_SKEW:=60}"
: "${YDEA_DEBUG:=0}"
: "${YDEA_LOG_FILE:=/tmp/ydea-toolkit.log}"
: "${YDEA_LOG_MAX_SIZE:=10485760}"  # 10MB
: "${YDEA_LOG_LEVEL:=INFO}"  # DEBUG, INFO, WARN, ERROR

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
  
  # ID utente per campo creatoda (richiesto da API)
  local user_id="${YDEA_USER_ID:-4675}"
  
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

# ===== CLI =====
show_usage() {
  cat >&2 <<'USAGE'
🛠️  Ydea Toolkit - Gestione API v2

SETUP:
  export YDEA_ID="tuo_id"              # Da: Impostazioni → La mia azienda → API
  export YDEA_API_KEY="tua_chiave_api"
  export YDEA_DEBUG=1                  # (opzionale) per debug verboso
  export YDEA_LOG_FILE=/path/log.log   # (default: /tmp/ydea-toolkit.log)

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
    
  Log e Debug:
    logs [lines]                       Mostra ultimi N log (default: 50)
    clearlog                           Pulisci file di log
    
  Altro:
    categories                         Lista categorie
    users [limit]                      Lista utenti

ESEMPI:

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

  # Visualizza log
  ./ydea-toolkit.sh logs 100

  # Chiamata API custom
  ./ydea-toolkit.sh api GET /tickets/12345/history | jq .

VARIABILI AMBIENTE:
  YDEA_BASE_URL      (default: https://my.ydea.cloud/app_api_v2)
  YDEA_TOKEN_FILE    (default: ~/.ydea_token.json)
  YDEA_LOG_FILE      (default: /tmp/ydea-toolkit.log)
  YDEA_LOG_MAX_SIZE  (default: 10485760 = 10MB)
  YDEA_EXPIRY_SKEW   (default: 60 secondi)
  YDEA_DEBUG         (default: 0, imposta 1 per debug)

LOG:
  Tutte le operazioni vengono registrate in: $YDEA_LOG_FILE
  Include: timestamp, livello (INFO/WARN/ERROR), PID, chiamate API con response code

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
  
  # Ticket operations
  list)        shift; list_tickets "$@" ;;
  get)         shift; get_ticket "$@" ;;
  create)      shift; create_ticket "$@" ;;
  update)      shift; update_ticket "$@" ;;
  close)       shift; close_ticket "$@" ;;
  comment)     shift; add_comment "$@" ;;
  search)      shift; search_tickets "$@" ;;
  
  # Log operations
  logs)        shift; show_logs "$@" ;;
  clearlog)    clear_log ;;
  
  # Other
  categories)  list_categories ;;
  users)       shift; list_users "$@" ;;
  
  -h|--help|help) show_usage; exit 0 ;;
  *)           show_usage; exit 1 ;;
esac
