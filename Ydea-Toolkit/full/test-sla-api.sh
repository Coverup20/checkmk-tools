#!/bin/bash
# test-sla-api.sh - Test nuova API YDEA per SLA automatica
#
# YDEA ha implementato API per inserimento automatico SLA:
# - SLA di default dell'anagrafica
# - SLA del contratto associato
#
# Questo script testa entrambe le modalità

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/ydea-toolkit.sh"

CONFIG_FILE="$SCRIPT_DIR/../config/premium-mon-config.json"

if [[ ! -f "$CONFIG_FILE" ]]; then
    log_error "File configurazione non trovato: $CONFIG_FILE"
    exit 1
fi

# Carica configurazione
ANAGRAFICA_ID=$(jq -r '.anagrafica_id' "$CONFIG_FILE")
PRIORITA_ID=$(jq -r '.priorita_id' "$CONFIG_FILE")
FONTE=$(jq -r '.fonte' "$CONFIG_FILE")
SLA_ID=$(jq -r '.sla_id // empty' "$CONFIG_FILE")
ASSEGNATOA_ID=$(jq -r '.assegnatoa_id // empty' "$CONFIG_FILE")

echo "════════════════════════════════════════════════════════════════════"
echo " TEST NUOVA API YDEA - SLA AUTOMATICA"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo " Configurazione:"
echo "   Anagrafica ID: $ANAGRAFICA_ID"
echo "   Priorita ID: $PRIORITA_ID"
echo "   SLA ID (config): $SLA_ID"
echo ""

# Autenticazione
ensure_token

echo "════════════════════════════════════════════════════════════════════"
echo "TEST 1: Creazione ticket SENZA sla_id (SLA default anagrafica)"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo " Aspettativa: API dovrebbe usare SLA di default dell'anagrafica"
echo ""

# Ticket senza sla_id
TICKET_BODY_1=$(jq -n \
  --arg titolo "[TEST] Ticket senza SLA - $(date '+%Y-%m-%d %H:%M:%S')" \
  --arg descrizione "Test SLA automatica - caso 1: senza sla_id" \
  --argjson anagrafica "$ANAGRAFICA_ID" \
  --argjson priorita "$PRIORITA_ID" \
  --arg fonte "$FONTE" \
  --arg tipo "Consulenza tecnica specialistica" \
  '{
    titolo: $titolo,
    descrizione: $descrizione,
    anagrafica_id: $anagrafica,
    priorita_id: $priorita,
    fonte: $fonte,
    tipo: $tipo
  }')

if [[ -n "$ASSEGNATOA_ID" ]]; then
    TICKET_BODY_1=$(echo "$TICKET_BODY_1" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
fi

echo " Invio richiesta API..."
echo ""
echo "Body JSON:"
echo "$TICKET_BODY_1" | jq '.'
echo ""

RESPONSE_1=$(ydea_api POST "/ticket" "$TICKET_BODY_1")

TICKET_ID_1=$(echo "$RESPONSE_1" | jq -r '.id // .ticket_id // .data.id // empty')
TICKET_CODE_1=$(echo "$RESPONSE_1" | jq -r '.codice // .code // .data.codice // empty')

if [[ -n "$TICKET_ID_1" && "$TICKET_ID_1" != "null" ]]; then
  echo " Ticket 1 creato con successo!"
  echo "   ID: $TICKET_ID_1"
  echo "   Codice: ${TICKET_CODE_1:-N/A}"
  echo ""
  
  # Recupera dettaglio ticket per verificare SLA
  echo " Verifica SLA assegnata..."
  DETAIL_1=$(ydea_api GET "/ticket/${TICKET_ID_1}")
  
  echo ""
  echo "Dettaglio ticket:"
  echo "$DETAIL_1" | jq '{id, codice, titolo, sla_id, sla_nome: .sla.nome, contratto_id, contratto_nome: .contratto.nome}'
  echo ""
  
  SLA_FOUND=$(echo "$DETAIL_1" | jq -r '.sla_id // .sla.id // empty')
  if [[ -n "$SLA_FOUND" && "$SLA_FOUND" != "null" ]]; then
    echo " SLA automaticamente assegnata: ID=$SLA_FOUND"
  else
    echo " NESSUNA SLA assegnata (possibile problema API)"
  fi
else
  echo " Creazione ticket fallita"
  echo ""
  echo "Response completa:"
  echo "$RESPONSE_1" | jq '.'
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "TEST 2: Creazione ticket CON sla_id esplicito"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo " Aspettativa: API dovrebbe usare SLA specificata (ID=$SLA_ID)"
echo ""

# Ticket con sla_id esplicito
TICKET_BODY_2=$(jq -n \
  --arg titolo "[TEST] Ticket con SLA esplicita - $(date '+%Y-%m-%d %H:%M:%S')" \
  --arg descrizione "Test SLA automatica - caso 2: con sla_id=$SLA_ID" \
  --argjson anagrafica "$ANAGRAFICA_ID" \
  --argjson priorita "$PRIORITA_ID" \
  --arg fonte "$FONTE" \
  --arg tipo "Consulenza tecnica specialistica" \
  --argjson sla_id "$SLA_ID" \
  '{
    titolo: $titolo,
    descrizione: $descrizione,
    anagrafica_id: $anagrafica,
    priorita_id: $priorita,
    fonte: $fonte,
    tipo: $tipo,
    sla_id: $sla_id
  }')

if [[ -n "$ASSEGNATOA_ID" ]]; then
    TICKET_BODY_2=$(echo "$TICKET_BODY_2" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
fi

echo " Invio richiesta API..."
echo ""
echo "Body JSON:"
echo "$TICKET_BODY_2" | jq '.'
echo ""

RESPONSE_2=$(ydea_api POST "/ticket" "$TICKET_BODY_2")

TICKET_ID_2=$(echo "$RESPONSE_2" | jq -r '.id // .ticket_id // .data.id // empty')
TICKET_CODE_2=$(echo "$RESPONSE_2" | jq -r '.codice // .code // .data.codice // empty')

if [[ -n "$TICKET_ID_2" && "$TICKET_ID_2" != "null" ]]; then
  echo " Ticket 2 creato con successo!"
  echo "   ID: $TICKET_ID_2"
  echo "   Codice: ${TICKET_CODE_2:-N/A}"
  echo ""
  
  # Recupera dettaglio ticket per verificare SLA
  echo " Verifica SLA assegnata..."
  DETAIL_2=$(ydea_api GET "/ticket/${TICKET_ID_2}")
  
  echo ""
  echo "Dettaglio ticket:"
  echo "$DETAIL_2" | jq '{id, codice, titolo, sla_id, sla_nome: .sla.nome, contratto_id, contratto_nome: .contratto.nome}'
  echo ""
  
  SLA_FOUND=$(echo "$DETAIL_2" | jq -r '.sla_id // .sla.id // empty')
  if [[ "$SLA_FOUND" == "$SLA_ID" ]]; then
    echo " SLA corretta assegnata: ID=$SLA_FOUND (atteso: $SLA_ID)"
  else
    echo " SLA diversa: trovato ID=$SLA_FOUND, atteso ID=$SLA_ID"
  fi
else
  echo " Creazione ticket fallita"
  echo ""
  echo "Response completa:"
  echo "$RESPONSE_2" | jq '.'
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "TEST 3: Creazione ticket CON contratto_id (SLA da contratto)"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo " Aspettativa: API dovrebbe estrarre SLA dal contratto specificato"
echo ""

# Prima trova un contratto valido per l'anagrafica
echo " Ricerca contratti per anagrafica $ANAGRAFICA_ID..."

CONTRACTS=$(ydea_api GET "/contratti?anagrafica_id=${ANAGRAFICA_ID}&limit=10")
CONTRACT_ID=$(echo "$CONTRACTS" | jq -r '.objs[0].id // .data[0].id // empty')

if [[ -z "$CONTRACT_ID" || "$CONTRACT_ID" == "null" ]]; then
  echo " NESSUN CONTRATTO trovato per questa anagrafica"
  echo "   Skippo TEST 3"
  echo ""
else
  echo " Contratto trovato: ID=$CONTRACT_ID"
  echo ""
  
  # Ticket con contratto_id
  TICKET_BODY_3=$(jq -n \
    --arg titolo "[TEST] Ticket con contratto_id - $(date '+%Y-%m-%d %H:%M:%S')" \
    --arg descrizione "Test SLA automatica - caso 3: con contratto_id=$CONTRACT_ID" \
    --argjson anagrafica "$ANAGRAFICA_ID" \
    --argjson priorita "$PRIORITA_ID" \
    --arg fonte "$FONTE" \
    --arg tipo "Consulenza tecnica specialistica" \
    --argjson contratto_id "$CONTRACT_ID" \
    '{
      titolo: $titolo,
      descrizione: $descrizione,
      anagrafica_id: $anagrafica,
      priorita_id: $priorita,
      fonte: $fonte,
      tipo: $tipo,
      contratto_id: $contratto_id
    }')
  
  if [[ -n "$ASSEGNATOA_ID" ]]; then
      TICKET_BODY_3=$(echo "$TICKET_BODY_3" | jq --argjson uid "$ASSEGNATOA_ID" '. + {assegnatoa: [$uid]}')
  fi
  
  echo " Invio richiesta API..."
  echo ""
  echo "Body JSON:"
  echo "$TICKET_BODY_3" | jq '.'
  echo ""
  
  RESPONSE_3=$(ydea_api POST "/ticket" "$TICKET_BODY_3")
  
  TICKET_ID_3=$(echo "$RESPONSE_3" | jq -r '.id // .ticket_id // .data.id // empty')
  TICKET_CODE_3=$(echo "$RESPONSE_3" | jq -r '.codice // .code // .data.codice // empty')
  
  if [[ -n "$TICKET_ID_3" && "$TICKET_ID_3" != "null" ]]; then
    echo " Ticket 3 creato con successo!"
    echo "   ID: $TICKET_ID_3"
    echo "   Codice: ${TICKET_CODE_3:-N/A}"
    echo ""
    
    # Recupera dettaglio ticket per verificare SLA e contratto
    echo " Verifica SLA e contratto assegnati..."
    DETAIL_3=$(ydea_api GET "/ticket/${TICKET_ID_3}")
    
    echo ""
    echo "Dettaglio ticket:"
    echo "$DETAIL_3" | jq '{id, codice, titolo, sla_id, sla_nome: .sla.nome, contratto_id, contratto_nome: .contratto.nome}'
    echo ""
    
    CONTRACT_FOUND=$(echo "$DETAIL_3" | jq -r '.contratto_id // .contratto.id // empty')
    SLA_FOUND=$(echo "$DETAIL_3" | jq -r '.sla_id // .sla.id // empty')
    
    if [[ "$CONTRACT_FOUND" == "$CONTRACT_ID" ]]; then
      echo " Contratto correttamente associato: ID=$CONTRACT_FOUND"
    else
      echo " Contratto diverso o mancante: trovato ID=$CONTRACT_FOUND, atteso ID=$CONTRACT_ID"
    fi
    
    if [[ -n "$SLA_FOUND" && "$SLA_FOUND" != "null" ]]; then
      echo " SLA estratta dal contratto: ID=$SLA_FOUND"
    else
      echo " SLA NON estratta dal contratto"
    fi
  else
    echo " Creazione ticket fallita"
    echo ""
    echo "Response completa:"
    echo "$RESPONSE_3" | jq '.'
  fi
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo " RIEPILOGO TEST"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "TEST 1 (senza sla_id):"
if [[ -n "$TICKET_ID_1" && "$TICKET_ID_1" != "null" ]]; then
  echo "    Ticket creato: $TICKET_CODE_1 (ID: $TICKET_ID_1)"
  echo "    https://my.ydea.cloud/ticket/${TICKET_ID_1}"
else
  echo "    FALLITO"
fi
echo ""

echo "TEST 2 (con sla_id esplicito):"
if [[ -n "$TICKET_ID_2" && "$TICKET_ID_2" != "null" ]]; then
  echo "    Ticket creato: $TICKET_CODE_2 (ID: $TICKET_ID_2)"
  echo "    https://my.ydea.cloud/ticket/${TICKET_ID_2}"
else
  echo "    FALLITO"
fi
echo ""

if [[ -n "$CONTRACT_ID" && "$CONTRACT_ID" != "null" ]]; then
  echo "TEST 3 (con contratto_id):"
  if [[ -n "$TICKET_ID_3" && "$TICKET_ID_3" != "null" ]]; then
    echo "    Ticket creato: $TICKET_CODE_3 (ID: $TICKET_ID_3)"
    echo "    https://my.ydea.cloud/ticket/${TICKET_ID_3}"
  else
    echo "    FALLITO"
  fi
  echo ""
fi

echo "════════════════════════════════════════════════════════════════════"
echo " Test completato!"
echo ""
echo " NOTA: Se YDEA non ha documentato gli endpoint, questi sono i campi testati:"
echo "   - sla_id (esistente, dovrebbe funzionare)"
echo "   - contratto_id (nuovo?, da verificare se supportato)"
echo ""
echo "Verifica manualmente i ticket creati su Ydea UI per confermare SLA:"
echo " https://my.ydea.cloud"
echo ""
