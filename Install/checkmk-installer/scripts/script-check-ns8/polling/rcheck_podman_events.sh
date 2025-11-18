#!/bin/bash
# Launcher base per eseguire uno script remoto dal repo GitHub
# Inserisci l'URL dello script qui sotto

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-check-ns8/polling/check_podman_events.sh"

# Puoi passare parametri aggiuntivi allo script remoto
# Uso: bash rcheck_podman_events.sh [parametri]

bash <(curl -fsSL "$SCRIPT_URL") "$@"
