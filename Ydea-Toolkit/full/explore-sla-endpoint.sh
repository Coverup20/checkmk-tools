#!/bin/bash
# explore-sla-endpoint.sh - Esplora possibili endpoint/campi SLA in YDEA API

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

echo "════════════════════════════════════════════════════════════════════"
echo " ESPLORAZIONE ENDPOINT SLA - YDEA API"
echo "════════════════════════════════════════════════════════════════════"
echo ""

ensure_token

# Test 1: Cerca endpoint /sla
echo "TEST 1: GET /sla (lista SLA disponibili)"
echo "────────────────────────────────────────────────────────────────────"
RESPONSE=$(ydea_api GET "/sla?limit=10" || echo '{"error": "endpoint non trovato"}')
echo "$RESPONSE" | jq '.' 2>/dev/null || echo "$RESPONSE"
echo ""
echo ""

# Test 2: Cerca nella struttura anagrafica
echo "TEST 2: GET /anagrafiche/2339268 (cerca SLA di default)"
echo "────────────────────────────────────────────────────────────────────"
RESPONSE=$(ydea_api GET "/anagrafiche/2339268" || echo '{"error": "endpoint non trovato"}')
echo "$RESPONSE" | jq '{id, ragioneSociale, sla_default: .sla, sla_id, contratti: .contratti}' 2>/dev/null || echo "$RESPONSE"
echo ""
echo "Campi contenenti 'sla' (case-insensitive):"
echo "$RESPONSE" | jq 'keys | map(select(test("sla"; "i")))' 2>/dev/null || echo "Nessun campo trovato"
echo ""
echo ""

# Test 3: Cerca nella struttura contratti
echo "TEST 3: GET /contratti/180437 (cerca SLA nel contratto)"
echo "────────────────────────────────────────────────────────────────────"
RESPONSE=$(ydea_api GET "/contratti/180437" || echo '{"error": "endpoint non trovato"}')
echo "$RESPONSE" | jq '{id, nome, sla, sla_id, anagrafica_id}' 2>/dev/null || echo "$RESPONSE"
echo ""
echo "Campi contenenti 'sla' (case-insensitive):"
echo "$RESPONSE" | jq 'keys | map(select(test("sla"; "i")))' 2>/dev/null || echo "Nessun campo trovato"
echo ""
echo ""

# Test 4: Prova UPDATE ticket con SLA
TICKET_ID="1630352"  # Ticket TEST 2 creato in precedenza
echo "TEST 4: PATCH /ticket/${TICKET_ID} (tenta di aggiungere SLA a ticket esistente)"
echo "────────────────────────────────────────────────────────────────────"

UPDATE_BODY=$(jq -n --argjson sla_id 147 '{sla_id: $sla_id}')
echo "Body: $UPDATE_BODY"
echo ""

RESPONSE=$(ydea_api PATCH "/ticket/${TICKET_ID}" "$UPDATE_BODY" || echo '{"error": "update fallito"}')
echo "$RESPONSE" | jq '.' 2>/dev/null || echo "$RESPONSE"
echo ""

# Verifica se SLA è stata aggiunta
echo "Verifica ticket dopo PATCH:"
DETAIL=$(ydea_api GET "/ticket/${TICKET_ID}" || ydea_api GET "/tickets?id=${TICKET_ID}")
echo "$DETAIL" | jq '{id, codice, sla_id, sla}' 2>/dev/null || echo "Ticket non trovato con endpoint GET"
echo ""
echo ""

# Test 5: Prova con campo diverso
echo "TEST 5: Prova campo 'slaId' (camelCase) invece di 'sla_id'"
echo "────────────────────────────────────────────────────────────────────"

TICKET_BODY=$(jq -n \
  --arg titolo "[TEST] Ticket con slaId camelCase - $(date '+%Y-%m-%d %H:%M:%S')" \
  --arg descrizione "Test campo slaId al posto di sla_id" \
  --argjson anagrafica 2339268 \
  --argjson priorita 30 \
  --arg fonte "Partner portal" \
  --arg tipo "Consulenza tecnica specialistica" \
  --argjson slaId 147 \
  '{
    titolo: $titolo,
    descrizione: $descrizione,
    anagrafica_id: $anagrafica,
    priorita_id: $priorita,
    fonte: $fonte,
    tipo: $tipo,
    slaId: $slaId
  }')

echo "Body: $TICKET_BODY"
echo ""

RESPONSE=$(ydea_api POST "/ticket" "$TICKET_BODY")
TICKET_ID_NEW=$(echo "$RESPONSE" | jq -r '.id // .ticket_id // .data.id // empty')

if [[ -n "$TICKET_ID_NEW" && "$TICKET_ID_NEW" != "null" ]]; then
  echo " Ticket creato: ID=$TICKET_ID_NEW"
  
  # Recupera e verifica SLA
  sleep 1
  echo "Verifica SLA..."
  DETAIL=$(ydea_api GET "/tickets?id=${TICKET_ID_NEW}&limit=1" | jq '.objs[0] // .data[0] // .')
  echo "$DETAIL" | jq '{id, codice, sla_id, sla}' 2>/dev/null
else
  echo " Creazione fallita"
  echo "$RESPONSE" | jq '.'
fi

echo ""
echo ""

# Test 6: Cerca nella documentazione/schema API
echo "TEST 6: GET /api-docs o /schema (se disponibile)"
echo "────────────────────────────────────────────────────────────────────"

for endpoint in "/api-docs" "/schema" "/openapi" "/swagger"; do
  echo "Tentativo: GET $endpoint"
  RESPONSE=$(ydea_api GET "$endpoint" 2>/dev/null || echo '{"error": "not found"}')
  
  if echo "$RESPONSE" | jq -e '.error' >/dev/null 2>&1; then
    echo "    Non disponibile"
  else
    echo "    TROVATO!"
    echo "$RESPONSE" | jq '.' | head -50
    break
  fi
done

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " Esplorazione completata!"
echo ""
echo " CONCLUSIONI:"
echo "   1. Verifica manualmente i ticket su https://my.ydea.cloud"
echo "   2. Se SLA appare su UI ma non via API, potrebbe essere:"
echo "      - Campo custom attribute"
echo "      - Logica lato server post-creazione"
echo "      - API v3 con endpoint diverso"
echo ""
echo " SUGGERIMENTO: Contatta YDEA per documentazione API SLA"
echo "════════════════════════════════════════════════════════════════════"
