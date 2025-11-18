#!/bin/bash
# Script per forzare l'aggiornamento del servizio WS2022AD su CheckMK

echo "=== FORCE UPDATE WS2022AD SU CHECKMK ==="
echo ""

# Nome host
HOST="WS2022AD"

echo "1. Flush cache host..."
cmk --flush $HOST
echo ""

echo "2. Service discovery completo..."
cmk -II $HOST
echo ""

echo "3. Ricarica configurazione..."
cmk -O
echo ""

echo "4. Test output agent diretto..."
cmk --debug --detect-plugins $HOST | grep -A10 "Ransomware"
echo ""

echo "5. Verifica servizi attivi..."
cmk --list-checks $HOST | grep -i ransomware
echo ""

echo "=== COMPLETATO ==="
echo "Verifica nella Web GUI tra 1-2 minuti"
