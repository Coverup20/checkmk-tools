#!/bin/bash
# explore-anagrafica.sh - Esplora i dati dell'anagrafica per trovare la SLA

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

ANAGRAFICA_ID="${1:-2339268}"  # Default: AZIENDA MONITORATA test

echo " Esplorazione anagrafica ID: $ANAGRAFICA_ID..."
echo ""

ensure_token
TOKEN="$(load_token)"

# Prova vari endpoint per l'anagrafica
declare -a ENDPOINTS=(
  "/anagrafica/$ANAGRAFICA_ID"
  "/anagrafiche/$ANAGRAFICA_ID"
  "/clienti/$ANAGRAFICA_ID"
  "/cliente/$ANAGRAFICA_ID"
  "/aziende/$ANAGRAFICA_ID"
  "/azienda/$ANAGRAFICA_ID"
  "/anagrafiche?id=$ANAGRAFICA_ID"
  "/sla?anagrafica_id=$ANAGRAFICA_ID"
  "/contracts?anagrafica_id=$ANAGRAFICA_ID"
  "/contratti?anagrafica_id=$ANAGRAFICA_ID"
)

echo " Tentativo di recupero dati anagrafica..."
echo ""

for ENDPOINT in "${ENDPOINTS[@]}"; do
  echo -n "   GET $ENDPOINT ... "
  
  RESPONSE=$(curl -s -w '\n%{http_code}' \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}${ENDPOINT}" 2>&1 || echo -e "\n000")
  
  HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
  
  if [[ "$HTTP_CODE" == "200" ]]; then
    echo " HTTP $HTTP_CODE - TROVATO!"
    
    HTTP_BODY=$(echo "$RESPONSE" | sed '$d')
    
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo "RISPOSTA DA: $ENDPOINT"
    echo "════════════════════════════════════════════════════════════════════════"
    echo ""
    
    echo "$HTTP_BODY" | jq '.'
    
    echo ""
    
    # Cerca campi contenenti "sla", "premium", "mon"
    echo " Campi contenenti 'SLA', 'Premium' o 'Mon':"
    echo "$HTTP_BODY" | jq 'walk(if type == "object" then with_entries(select(.key | test("sla|premium|mon|contract|contratt"; "i"))) else . end)' 2>/dev/null || echo "   Nessuno trovato"
    
    echo ""
    
    # Salva il risultato
    echo "$HTTP_BODY" | jq '.' > "/tmp/anagrafica-${ANAGRAFICA_ID}.json"
    echo " Salvato in: /tmp/anagrafica-${ANAGRAFICA_ID}.json"
    echo ""
  elif [[ "$HTTP_CODE" == "404" ]]; then
    echo " HTTP $HTTP_CODE - Non trovato"
  elif [[ "$HTTP_CODE" == "401" ]]; then
    echo " HTTP $HTTP_CODE - Non autorizzato"
  elif [[ "$HTTP_CODE" == "403" ]]; then
    echo " HTTP $HTTP_CODE - Accesso negato"
  else
    echo " HTTP $HTTP_CODE"
  fi
done

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "RICERCA NEI TICKET CON QUESTA ANAGRAFICA"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

echo "Cerco ticket con anagrafica_id=$ANAGRAFICA_ID per vedere tutti i campi disponibili..."
echo ""

RESPONSE=$(curl -s \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  "${YDEA_BASE_URL}/tickets?limit=50")

MATCHING_TICKETS=$(echo "$RESPONSE" | jq --arg aid "$ANAGRAFICA_ID" '[.objs[] | select(.anagrafica_id == ($aid|tonumber))]')
COUNT=$(echo "$MATCHING_TICKETS" | jq 'length')

echo "Trovati $COUNT ticket con questa anagrafica"

if [[ "$COUNT" -gt 0 ]]; then
    echo ""
    echo "Primo ticket trovato (per analisi campi):"
    echo "$MATCHING_TICKETS" | jq '.[0]'
    echo ""
    
    echo "Tutte le chiavi disponibili nei ticket di questa anagrafica:"
    echo "$MATCHING_TICKETS" | jq '[.[].keys[]] | unique | sort[]'
    echo ""
    
    # Cerca campi custom o sla
    echo "Valori customAttributes nei ticket di questa anagrafica:"
    echo "$MATCHING_TICKETS" | jq '[.[].customAttributes // {}] | unique'
fi

echo ""
echo " Esplorazione completata!"
