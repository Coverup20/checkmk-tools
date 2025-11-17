#!/bin/bash
# Launcher per eseguire checkmk-tuning-interactive-v4.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/checkmk-tuning-interactive-v4.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"