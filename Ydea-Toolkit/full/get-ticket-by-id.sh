#!/bin/bash
# get-ticket-by-id.sh - Recupera un ticket specifico per ID numerico

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

echo " Recuperando ticket ID: $TICKET_ID..."
echo ""

# Assicurati di avere il token
ensure_token
TOKEN="$(load_token)"

# Prova prima con l'endpoint diretto /tickets/{id}
echo " Tentativo 1: GET /tickets/$TICKET_ID"
RESPONSE=$(curl -s -w '\n%{http_code}' \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${TOKEN}" \
  "${YDEA_BASE_URL}/tickets/${TICKET_ID}" 2>&1 || echo -e "\n404")

HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"

echo "   HTTP Status: $HTTP_CODE"
echo ""

if [[ "$HTTP_CODE" == "200" ]]; then
    TICKET_DATA="$HTTP_BODY"
else
    # Se fallisce, prova con paginazione
    TICKET_DATA=""
    LIMIT=100
    MAX_PAGES=100
    
    # Cerca fino a 100 pagine (10000 ticket totali)
    echo " Ricerca con paginazione (limit=$LIMIT per pagina)..."
    echo ""
    
    for PAGE in $(seq 1 $MAX_PAGES); do
        echo -n "   Pagina $PAGE... "
        
        RESPONSE=$(curl -s -w '\n%{http_code}' \
          -H "Accept: application/json" \
          -H "Authorization: Bearer ${TOKEN}" \
          "${YDEA_BASE_URL}/tickets?limit=${LIMIT}&page=${PAGE}")
        
        HTTP_BODY="$(echo "$RESPONSE" | sed '$d')"
        HTTP_CODE="$(echo "$RESPONSE" | tail -n1)"
        
        if [[ "$HTTP_CODE" != "200" ]]; then
            echo " Errore HTTP $HTTP_CODE"
            break
        fi
        
        # Controlla se ci sono risultati
        COUNT=$(echo "$HTTP_BODY" | jq -r '.objs | length')
        if [[ "$COUNT" -eq 0 ]]; then
            echo "Nessun ticket, fine ricerca"
            break
        fi
        
        # Mostra range ID disponibili
        MIN_ID=$(echo "$HTTP_BODY" | jq -r '.objs | map(.id) | min')
        MAX_ID=$(echo "$HTTP_BODY" | jq -r '.objs | map(.id) | max')
        echo "Range: $MIN_ID - $MAX_ID ($COUNT ticket)"
        
        # Filtra per ID
        TICKET_DATA=$(echo "$HTTP_BODY" | jq --arg tid "$TICKET_ID" '.objs[] | select(.id == ($tid|tonumber))')
        
        if [[ -n "$TICKET_DATA" && "$TICKET_DATA" != "null" ]]; then
            echo ""
            echo "    Ticket trovato alla pagina $PAGE!"
            break
        fi
        
        # Se l'ID cercato è inferiore al minimo, continua con pagina successiva
        if [[ "$TICKET_ID" -lt "$MIN_ID" ]]; then
            # Continua a cercare nelle pagine successive (ticket più vecchi)
            continue
        fi
        
        # Se l'ID cercato è superiore al massimo, il ticket è nella pagina precedente o non esiste
        if [[ "$TICKET_ID" -gt "$MAX_ID" ]]; then
            echo ""
            echo "     Ticket ID $TICKET_ID > $MAX_ID, cercato oltre il range"
            break
        fi
    done
    
    if [[ -z "$TICKET_DATA" || "$TICKET_DATA" == "null" ]]; then
        echo ""
        echo " Ticket ID $TICKET_ID non trovato"
        echo ""
        echo " Il ticket potrebbe essere:"
        echo "   - Oltre la pagina $MAX_PAGES (più di 10000 ticket fa)"
        echo "   - Stato archiviato o eliminato"
        echo "   - Con ID errato"
        exit 1
    fi
fi

echo " Ticket trovato!"
echo ""

TICKET_CODE=$(echo "$TICKET_DATA" | jq -r '.codice // "N/A"')

echo "════════════════════════════════════════════════════════════════════"
echo "STRUTTURA COMPLETA DEL TICKET ID=$TICKET_ID CODICE=$TICKET_CODE"
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
echo "   Descrizione: $(echo "$TICKET_DATA" | jq -r '.descrizione // .testo // "N/A"')"
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
echo "   Macro Categoria: $(echo "$TICKET_DATA" | jq -r '.macrocategoria // .macro_categoria // "N/A"')"
echo "   Macro Categoria ID: $(echo "$TICKET_DATA" | jq -r '.macrocategoria_id // .macrocategoriaId // "N/A"')"
echo ""

echo "  SLA:"
echo "   SLA: $(echo "$TICKET_DATA" | jq -r '.sla // "N/A"')"
echo "   SLA ID: $(echo "$TICKET_DATA" | jq -r '.sla_id // .slaId // "N/A"')"
echo "   SLA Nome: $(echo "$TICKET_DATA" | jq -r '.sla_nome // .slaNome // "N/A"')"
echo "   SLA Descrizione: $(echo "$TICKET_DATA" | jq -r '.sla_descrizione // .slaDescrizione // "N/A"')"
echo ""

echo " Stato:"
echo "   Stato: $(echo "$TICKET_DATA" | jq -r '.stato // "N/A"')"
echo "   Stato ID: $(echo "$TICKET_DATA" | jq -r '.stato_id // .statoId // "N/A"')"
echo ""

echo " Assegnazione:"
echo "   Assegnato A: $(echo "$TICKET_DATA" | jq -r '.assegnatoA // .assegnato_a // "N/A"')"
echo ""

echo " Azienda/Cliente:"
echo "   Azienda: $(echo "$TICKET_DATA" | jq -r '.azienda // "N/A"')"
echo "   Azienda ID: $(echo "$TICKET_DATA" | jq -r '.azienda_id // .aziendaId // "N/A"')"
echo "   Cliente: $(echo "$TICKET_DATA" | jq -r '.cliente // "N/A"')"
echo ""

echo " Custom Attributes:"
if echo "$TICKET_DATA" | jq -e '.customAttributes' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.customAttributes'
elif echo "$TICKET_DATA" | jq -e '.custom_attributes' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.custom_attributes'
elif echo "$TICKET_DATA" | jq -e '.campiCustom' >/dev/null 2>&1; then
    echo "$TICKET_DATA" | jq '.campiCustom'
else
    echo "   Nessun custom attribute trovato"
fi
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "TUTTE LE CHIAVI DISPONIBILI NEL JSON"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "$TICKET_DATA" | jq -r 'keys[]' | sort

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "CAMPI CONTENENTI 'CATEGORIA', 'SLA', 'PREMIUM' O 'MON'"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "$TICKET_DATA" | jq 'to_entries | map(select(.key | test("categoria|sla|premium|mon|categor|custom"; "i"))) | from_entries'

echo ""
echo " Ispezione completata!"
echo ""
echo " Salvo il JSON completo in /tmp/ticket-${TICKET_ID}.json per riferimento futuro..."
echo "$TICKET_DATA" | jq '.' > "/tmp/ticket-${TICKET_ID}.json"
echo "   File salvato: /tmp/ticket-${TICKET_ID}.json"
