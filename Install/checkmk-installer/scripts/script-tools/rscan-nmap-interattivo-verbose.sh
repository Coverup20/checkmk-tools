#!/bin/bash
# Launcher per eseguire scan-nmap-interattivo-verbose.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/scan-nmap-interattivo-verbose.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"