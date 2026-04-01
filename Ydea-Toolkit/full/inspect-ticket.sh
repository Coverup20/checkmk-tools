#!/bin/bash
# inspect-ticket.sh - Ispeziona un singolo ticket per vedere la struttura completa

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source del toolkit solo per funzioni helper
source "$SCRIPT_DIR/ydea-toolkit.sh"

TICKET_ID="${1:-}"

if [[ -z "$TICKET_ID" ]]; then
    echo " Uso: $0 <ticket_id>"
    echo ""
    echo "Esempio:"
    echo "  $0 1486125"
    exit 1
fi

echo " Ispezionando ticket #$TICKET_ID..."
echo ""

# Assicurati di avere il token
ensure_token
TOKEN="$(load_token)"

# Chiamata diretta all'API per ottenere lista ticket e filtrare per ID
echo " Chiamata API: GET /tickets?limit=100"
echo ""

RESPONSE=$(curl -s -w '\n%{http_code}' \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  "${YDEA_BASE_URL}/tickets?limit=100")

HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"

echo " HTTP Status: $HTTP_CODE"

if [[ "$HTTP_CODE" != "200" ]]; then
    echo " Errore nella chiamata API"
    echo "$HTTP_BODY" | jq . 2>/dev/null || echo "$HTTP_BODY"
    exit 1
fi

# Filtra per il ticket specifico
TICKET_DATA=$(echo "$HTTP_BODY" | jq --arg tid "$TICKET_ID" '.objs[] | select(.id == ($tid|tonumber))')

if [[ -z "$TICKET_DATA" || "$TICKET_DATA" == "null" ]]; then
    echo " Ticket #$TICKET_ID non trovato nei risultati"
    echo ""
    echo "Ticket disponibili:"
    echo "$HTTP_BODY" | jq -r '.objs[] | "\(.id) - \(.codice) - \(.titolo)"' | head -20
    exit 1
fi

echo " Ticket trovato!"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "STRUTTURA COMPLETA DEL TICKET"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Mostra tutto il JSON formattato
echo "$TICKET_DATA" | jq '.'

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "CAMPI CHIAVE ESTRATTI"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo " Info Base:"
echo "   ID: $(echo "$TICKET_DATA" | jq -r '.id')"
echo "   Codice: $(echo "$TICKET_DATA" | jq -r '.codice // "N/A"')"
echo "   Titolo: $(echo "$TICKET_DATA" | jq -r '.titolo // "N/A"')"
echo ""

echo " Priorità:"
echo "   Priorità: $(echo "$TICKET_DATA" | jq -r '.priorita // "N/A"')"
echo "   Priorità ID: $(echo "$TICKET_DATA" | jq -r '.priorita_id // .prioritaId // "N/A"')"
echo ""

echo " Categorie:"
echo "   Categoria: $(echo "$TICKET_DATA" | jq -r '.categoria // "N/A"')"
echo "   Categoria ID: $(echo "$TICKET_DATA" | jq -r '.categoria_id // .categoriaId // "N/A"')"
echo "   Sotto-categoria: $(echo "$TICKET_DATA" | jq -r '.sottocategoria // .sotto_categoria // "N/A"')"
echo "   Sotto-categoria ID: $(echo "$TICKET_DATA" | jq -r '.sottocategoria_id // .sottocategoriaId // "N/A"')"
echo ""

echo "  SLA:"
echo "   SLA: $(echo "$TICKET_DATA" | jq -r '.sla // "N/A"')"
echo "   SLA ID: $(echo "$TICKET_DATA" | jq -r '.sla_id // .slaId // "N/A"')"
echo "   SLA Nome: $(echo "$TICKET_DATA" | jq -r '.sla_nome // .slaNome // "N/A"')"
echo ""

echo " Stato:"
echo "   Stato: $(echo "$TICKET_DATA" | jq -r '.stato // "N/A"')"
echo "   Stato ID: $(echo "$TICKET_DATA" | jq -r '.stato_id // .statoId // "N/A"')"
echo ""

echo " Custom Attributes:"
if echo "$TICKET_DATA" | jq -e '.customAttributes' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.customAttributes'
else
    echo "   Nessun custom attribute trovato"
fi
echo ""

echo " Assegnazione:"
echo "   Assegnato A: $(echo "$TICKET_DATA" | jq -r '.assegnatoA // .assegnato_a // "N/A"')"
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "TUTTE LE CHIAVI DISPONIBILI NEL JSON"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "$TICKET_DATA" | jq -r 'keys[]' | sort

echo ""
echo " Ispezione completata!"
echo ""
echo " Suggerimento: Per vedere solo i campi che contengono 'categoria' o 'sla':"
echo "   echo '\$TICKET_DATA' | jq 'to_entries | map(select(.key | test(\"categoria|sla|categor\"; \"i\")))'"
