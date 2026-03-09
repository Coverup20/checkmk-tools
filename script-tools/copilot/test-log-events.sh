#!/bin/bash
# test-log-events.sh - Script di test per verificare log_ticket_event
# Testa la funzione di logging eventi ticket Ydea

YDEA_TOOLKIT="/opt/ydea-toolkit/rydea-toolkit.sh"

if [[ ! -f "$YDEA_TOOLKIT" ]]; then
  echo "❌ Toolkit non trovato: $YDEA_TOOLKIT"
  exit 1
fi

# Source del toolkit per usare le funzioni
source "$YDEA_TOOLKIT"

echo "=== TEST LOG_TICKET_EVENT ==="
echo ""

# Test 1: Evento CREATO
echo "Test 1: Evento CREATO"
log_ticket_event "CREATO" "1234567" "Test ticket creation event"

# Test 2: Evento AGGIORNATO
echo "Test 2: Evento AGGIORNATO"
log_ticket_event "AGGIORNATO" "1234567" "Test ticket update event with state change"

# Test 3: Evento RISOLTO
echo "Test 3: Evento RISOLTO"
log_ticket_event "RISOLTO" "1234567" "Test ticket resolved event"

# Test 4: Evento ERRORE
echo "Test 4: Evento ERRORE"
log_ticket_event "ERRORE" "1234567" "Test error event with failure details"

echo ""
echo "✓ Test completati"
echo ""
echo "Verifica i log in /var/log/ydea-events.log:"
tail -20 /var/log/ydea-events.log 2>/dev/null || echo "⚠️ Log file non trovato"
