#!/bin/bash
# Launcher per eseguire smart-wrapper-example.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/smart-wrapper-example.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"