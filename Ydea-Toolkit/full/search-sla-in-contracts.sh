#!/bin/bash
# search-sla-in-contracts.sh - Cerca SLA Premium_Mon nei contratti

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

echo " Ricerca 'Premium_Mon' nei contratti..."
echo ""

ensure_token
TOKEN="$(load_token)"

# Recupera tutti i contratti (paginati)
echo " Recupero contratti..."
ALL_CONTRACTS="/tmp/all-contracts.json"
echo "[]" > "$ALL_CONTRACTS"

for PAGE in $(seq 1 10); do
  echo -n "   Pagina $PAGE... "
  
  RESPONSE=$(curl -s \
    -H "Accept: application/json" \
    -H "Authorization: Bearer ${TOKEN}" \
    "${YDEA_BASE_URL}/contratti?limit=100&page=${PAGE}")
  
  if ! echo "$RESPONSE" | jq -e '.objs' >/dev/null 2>&1; then
    echo "Fine"
    break
  fi
  
  COUNT=$(echo "$RESPONSE" | jq -r '.objs | length')
  
  if [[ "$COUNT" -eq 0 ]]; then
    echo "Fine"
    break
  fi
  
  echo "$COUNT contratti"
  
  echo "$RESPONSE" | jq '.objs' >> "$ALL_CONTRACTS.tmp"
done

# Combina tutti i risultati
jq -s 'add' "$ALL_CONTRACTS.tmp" 2>/dev/null > "$ALL_CONTRACTS" || echo "[]" > "$ALL_CONTRACTS"
rm -f "$ALL_CONTRACTS.tmp"

TOTAL=$(jq 'length' "$ALL_CONTRACTS")
echo ""
echo "   Totale contratti raccolti: $TOTAL"
echo ""

# Cerca "Premium" o "Mon" nei contratti
echo "════════════════════════════════════════════════════════════════════"
echo "CONTRATTI CONTENENTI 'Premium' o 'Mon'"
echo "════════════════════════════════════════════════════════════════════"
echo ""

MATCHING=$(jq '[.[] | select((. | tostring) | test("Premium|Mon|premium|mon"))]' "$ALL_CONTRACTS")
MATCHING_COUNT=$(echo "$MATCHING" | jq 'length')

echo "Trovati: $MATCHING_COUNT contratti"

if [[ "$MATCHING_COUNT" -gt 0 ]]; then
    echo ""
    echo "$MATCHING" | jq '.[]'
else
    echo "   Nessun contratto trovato con 'Premium' o 'Mon'"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "DETTAGLIO DI UN CONTRATTO (per vedere struttura completa)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Prendi il primo contratto e fai GET dettagliato
FIRST_ID=$(jq -r '.[0].id' "$ALL_CONTRACTS")

if [[ -n "$FIRST_ID" && "$FIRST_ID" != "null" ]]; then
    echo "Recupero dettagli contratto ID: $FIRST_ID..."
    echo ""
    
    DETAIL=$(curl -s \
      -H "Accept: application/json" \
      -H "Authorization: Bearer ${TOKEN}" \
      "${YDEA_BASE_URL}/contratti/${FIRST_ID}")
    
    echo "$DETAIL" | jq '.'
    
    echo ""
    echo "Tutte le chiavi disponibili in un contratto:"
    echo "$DETAIL" | jq 'keys[]' | sort
fi

echo ""
echo " File salvato: $ALL_CONTRACTS"
echo ""
echo " Ricerca completata!"
