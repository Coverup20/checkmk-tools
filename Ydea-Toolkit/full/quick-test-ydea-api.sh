#!/bin/bash
# quick-test-ydea-api.sh — Test rapido connessione API Ydea
# Verifica che le credenziali funzionino prima di eseguire la discovery completa

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YDEA_TOOLKIT="${SCRIPT_DIR}/ydea-toolkit.sh"

# Carica le funzioni da ydea-toolkit
# shellcheck disable=SC1090
source "$YDEA_TOOLKIT"

echo ""
echo " Test Connessione Ydea API"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Test 1: Verifica variabili ambiente
echo " Test 1: Verifica configurazione..."

if [[ -z "${YDEA_ID:-}" || "${YDEA_ID}" == "ID" ]]; then
  echo " YDEA_ID non configurato correttamente"
  echo "   Edita il file .env e imposta YDEA_ID"
  exit 1
fi

if [[ -z "${YDEA_API_KEY:-}" || "${YDEA_API_KEY}" == "TOKEN" ]]; then
  echo " YDEA_API_KEY non configurato correttamente"
  echo "   Edita il file .env e imposta YDEA_API_KEY"
  exit 1
fi

echo " Variabili configurate:"
echo "   YDEA_ID: ${YDEA_ID}"
echo "   YDEA_API_KEY: ${YDEA_API_KEY:0:10}..."
echo ""

# Test 2: Login
echo " Test 2: Autenticazione..."

if ! ensure_token 2>&1; then
  echo " Autenticazione fallita"
  echo "   Verifica che YDEA_ID e YDEA_API_KEY siano corretti"
  exit 1
fi

echo " Autenticazione riuscita"
echo ""

# Test 3: Test chiamata API categorie
echo " Test 3: Test chiamata API categorie..."

set +e  # Disabilita exit on error temporaneamente
categories_data=$(ydea_api GET "/categories" 2>&1)
exit_code=$?
set -e  # Riabilita exit on error

if [[ $exit_code -ne 0 ]]; then
  echo " Errore nella chiamata API categorie (exit code: $exit_code)"
  echo ""
  echo "Risposta/Errore:"
  echo "$categories_data"
  echo ""
  echo "Possibili cause:"
  echo "  - Endpoint /categories non esiste o non è accessibile"
  echo "  - Problema di connessione o timeout"
  echo "  - Token scaduto o non valido"
  exit 1
fi

# Verifica se la risposta è JSON valido
if ! echo "$categories_data" | jq empty 2>/dev/null; then
  echo " Risposta non è JSON valido"
  echo ""
  echo "Risposta ricevuta:"
  echo "$categories_data" | head -30
  exit 1
fi

# Verifica se c'è un errore nella risposta
if echo "$categories_data" | jq -e 'has("error")' >/dev/null 2>&1; then
  echo " Errore nella risposta API"
  echo "$categories_data" | jq '.'
  exit 1
fi

cat_count=$(echo "$categories_data" | jq -r '.objs | length' 2>/dev/null || echo "0")
echo " API categorie funzionante - $cat_count categorie trovate"
echo ""

# Test 4: Test chiamata API ticket
echo " Test 4: Test chiamata API tickets..."
tickets_data=$(ydea_api GET "/tickets?limit=1" 2>&1)

if [[ $? -ne 0 ]] || echo "$tickets_data" | jq -e '.error' >/dev/null 2>&1; then
  echo " Errore nella chiamata API tickets"
  echo "Risposta API:"
  echo "$tickets_data" | head -20
  exit 1
fi

echo " API tickets funzionante"
echo ""

# Test 5: Test chiamata API users
echo " Test 5: Test chiamata API users..."
users_data=$(ydea_api GET "/users?limit=1" 2>&1)

if [[ $? -ne 0 ]] || echo "$users_data" | jq -e '.error' >/dev/null 2>&1; then
  echo " Errore nella chiamata API users"
  echo "Risposta API:"
  echo "$users_data" | head -20
  exit 1
fi

echo " API users funzionante"
echo ""

# Riepilogo
echo "════════════════════════════════════════════════════════════════"
echo " Tutti i test superati!"
echo ""
