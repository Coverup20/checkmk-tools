#!/usr/bin/env bash
# ydea-ticket-monitor.sh - Monitoraggio automatico stato ticket tracciati
# Aggiorna periodicamente lo stato dei ticket e rimuove quelli risolti vecchi
set -euo pipefail

# ===== CONFIG =====
TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YDEA_TOOLKIT="${TOOLKIT_DIR}/ydea-toolkit.sh"
YDEA_ENV="${TOOLKIT_DIR}/.env"

# Carica variabili ambiente se disponibili
if [[ -f "$YDEA_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$YDEA_ENV"
fi

# Verifica che il toolkit esista
if [[ ! -x "$YDEA_TOOLKIT" ]]; then
  echo "ERRORE: ydea-toolkit.sh non trovato o non eseguibile: $YDEA_TOOLKIT"
  exit 1
fi

# ===== MAIN =====
main() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Avvio monitoraggio ticket tracciati"
  
  # Aggiorna stati ticket
  "$YDEA_TOOLKIT" update-tracking
  
  # Pulisci ticket risolti vecchi (ogni 6 ore, controlla se ultima pulizia > 6h fa)
  local cleanup_marker="/tmp/ydea_last_cleanup"
  local now=$(date +%s)
  local last_cleanup=0
  
  if [[ -f "$cleanup_marker" ]]; then
    last_cleanup=$(cat "$cleanup_marker")
  fi
  
  local hours_since_cleanup=$(( (now - last_cleanup) / 3600 ))
  
  if [[ $hours_since_cleanup -ge 6 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Eseguo pulizia ticket risolti vecchi"
    "$YDEA_TOOLKIT" cleanup-tracking
    echo "$now" > "$cleanup_marker"
  fi
  
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitoraggio completato"
}

# Esegui main
main

exit 0
