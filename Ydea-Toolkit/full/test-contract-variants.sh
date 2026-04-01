#!/bin/bash
# test-contract-variants.sh - Testa varianti campo contratto per SLA

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

CONFIG_FILE="$SCRIPT_DIR/../config/premium-mon-config.json"
ANAGRAFICA_ID=$(jq -r '.anagrafica_id' "$CONFIG_FILE")
PRIORITA_ID=$(jq -r '.priorita_id' "$CONFIG_FILE")

echo "════════════════════════════════════════════════════════════════════"
echo " TEST VARIANTI CAMPO CONTRATTO"
echo "════════════════════════════════════════════════════════════════════"
echo ""

ensure_token

# Contratto di test (configurato su UI con SLA Premium_Mon)
CONTRACT_ID=180437

echo "Contratto test: ID=$CONTRACT_ID"
echo "Anagrafica: ID=$ANAGRAFICA_ID"
echo ""

# Array di varianti da testare
declare -a variants=(
  "contratto_id"
  "contratto"
  "contrattoId"
  "azienda_contratto_id"
  "aziendaContrattoId"
)

for field in "${variants[@]}"; do
  echo "════════════════════════════════════════════════════════════════════"
  echo "TEST: campo '$field'"
  echo "────────────────────────────────────────────────────────────────────"
  
  # Costruisci JSON dinamicamente
  TICKET_BODY=$(jq -n \
    --arg field "$field" \
    --argjson contract "$CONTRACT_ID" \
    --argjson anagrafica "$ANAGRAFICA_ID" \
    --argjson priorita "$PRIORITA_ID" \
    '{
      titolo: ("[TEST] campo " + $field),
      descrizione: "Test variante campo contratto",
      anagrafica_id: $anagrafica,
      priorita_id: $priorita,
      fonte: "Partner portal",
      tipo: "Consulenza tecnica specialistica"
    } + {($field): $contract}')
  
  echo "Body JSON:"
  echo "$TICKET_BODY" | jq '.'
  echo ""
  
  # POST ticket
  RESPONSE=$(ydea_api POST "/ticket" "$TICKET_BODY" 2>&1 || echo '{"error": "API failed"}')
  
  TICKET_ID=$(echo "$RESPONSE" | jq -r '.id // .ticket_id // .data.id // empty' 2>/dev/null || echo "")
  TICKET_CODE=$(echo "$RESPONSE" | jq -r '.codice // .code // .data.codice // empty' 2>/dev/null || echo "")
  
  if [[ -n "$TICKET_ID" && "$TICKET_ID" != "null" && "$TICKET_ID" != "error" ]]; then
    echo " Ticket creato: $TICKET_CODE (ID: $TICKET_ID)"
    
    # Aspetta e verifica SLA
    sleep 2
    
    echo " Verifica SLA su UI: https://my.ydea.cloud/ticket/${TICKET_ID}"
    
    # Prova a recuperare via API (sappiamo che non espone SLA ma proviamo)
    DETAIL=$(ydea_api GET "/tickets?id=${TICKET_ID}&limit=1" 2>/dev/null | jq '.objs[0] // {}' 2>/dev/null || echo '{}')
    
    # Cerca qualsiasi riferimento a SLA o contratto
    HAS_SLA=$(echo "$DETAIL" | jq 'has("sla") or has("sla_id") or has("sla_nome")' 2>/dev/null || echo "false")
    HAS_CONTRACT=$(echo "$DETAIL" | jq 'has("contratto") or has("contratto_id") or has("contrattoId")' 2>/dev/null || echo "false")
    
    if [[ "$HAS_SLA" == "true" ]]; then
      echo "    Campo SLA presente via API!"
      echo "$DETAIL" | jq '{sla, sla_id, sla_nome}' 2>/dev/null
    else
      echo "    Campo SLA NON presente via API (normale)"
    fi
    
    if [[ "$HAS_CONTRACT" == "true" ]]; then
      echo "    Campo contratto presente via API!"
      echo "$DETAIL" | jq '{contratto, contratto_id, contrattoId}' 2>/dev/null
    else
      echo "    Campo contratto NON presente via API"
    fi
    
  else
    echo " Creazione fallita"
    echo ""
    echo "Response:"
    echo "$RESPONSE" | jq '.' 2>/dev/null || echo "$RESPONSE"
  fi
  
  echo ""
  sleep 1
done

echo "════════════════════════════════════════════════════════════════════"
echo " Test completato!"
echo ""
echo " VERIFICA MANUALMENTE su UI YDEA:"
echo "   Controlla i ticket creati e vedi quale ha SLA 'Premium_Mon'"
echo "   invece di 'Standard'"
echo ""
echo " https://my.ydea.cloud"
echo "════════════════════════════════════════════════════════════════════"
