#!/bin/bash
# ydea-mirror-functions.sh - Funzioni per consultare mirror Ydea
# Source questo file in ydea_realip

YDEA_MIRROR="/opt/omd/sites/monitoring/var/ydea/mirror.json"

# Cerca ticket nel mirror per IP e servizio
search_mirror_ticket() {
  local search_ip="$1"
  local search_service="$2"
  
  if [[ ! -f "$YDEA_MIRROR" ]]; then
    return 1
  fi
  
  # Cerca ticket che matchano IP e contengono il nome servizio nel titolo
  jq -r --arg ip "$search_ip" --arg service "$search_service" '
    .tickets[] | 
    select(
      (.title // .titolo // "" | ascii_downcase | contains($service | ascii_downcase)) and
      (.description // .descrizione // "" | contains($ip))
    ) | 
    {
      id: (.ticket_id // .id),
      title: (.title // .titolo),
      status: (.stato // .status),
      created: (.created_at // .dataCreazione),
      codice: (.codice // "")
    }
  ' "$YDEA_MIRROR" 2>/dev/null
}

# Verifica se esiste ticket aperto per servizio
has_open_ticket_in_mirror() {
  local search_ip="$1"
  local search_service="$2"
  
  local result
  result=$(search_mirror_ticket "$search_ip" "$search_service")
  
  if [[ -z "$result" ]]; then
    return 1  # Nessun ticket trovato
  fi
  
  # Verifica se almeno uno è aperto
  local open_count
  open_count=$(echo "$result" | jq -s '[.[] | select(.status | ascii_downcase | contains("aperto") or contains("open") or contains("lavorazione"))] | length')
  
  if [[ "$open_count" -gt 0 ]]; then
    return 0  # Ticket aperto trovato
  else
    return 1  # Solo ticket chiusi
  fi
}

# Ottieni ID ticket aperto dal mirror
get_open_ticket_id_from_mirror() {
  local search_ip="$1"
  local search_service="$2"
  
  local result
  result=$(search_mirror_ticket "$search_ip" "$search_service")
  
  echo "$result" | jq -s -r '[.[] | select(.status | ascii_downcase | contains("aperto") or contains("open") or contains("lavorazione"))] | .[0].id // empty'
}

# Statistiche mirror
get_mirror_stats() {
  if [[ ! -f "$YDEA_MIRROR" ]]; then
    echo "Mirror non disponibile"
    return 1
  fi
  
  jq -r '
    "Ultimo sync: \(.sync_date // "mai")",
    "Totale ticket: \(.total_count // 0)",
    "Età dati: \((now - (.last_sync // 0)) / 60 | floor) minuti"
  ' "$YDEA_MIRROR"
}
