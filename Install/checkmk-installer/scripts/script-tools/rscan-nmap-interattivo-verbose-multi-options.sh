#!/bin/bash
# Launcher per eseguire scan-nmap-interattivo-verbose-multi-options.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/scan-nmap-interattivo-verbose-multi-options.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"