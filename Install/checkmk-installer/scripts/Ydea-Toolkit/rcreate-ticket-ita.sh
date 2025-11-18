#!/bin/bash
# Launcher per eseguire create-ticket-ita.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/Ydea-Toolkit/create-ticket-ita.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"