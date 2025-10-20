#!/bin/bash
# Launcher base per eseguire uno script remoto dal repo GitHub
# Inserisci l'URL dello script qui sotto

SCRIPT_URL="https://github.com/Coverup20/checkmk-tools/blob/main/script-check-ns7/nopolling/check_cockpit_sessions.sh"

# Puoi passare parametri aggiuntivi allo script remoto
# Uso: bash rcheck_cockpit_sessions.sh [parametri]

bash <(curl -fsSL "$SCRIPT_URL") "$@"