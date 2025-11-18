#!/bin/bash
# Launcher per eseguire ydea-monitoring-integration.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/Ydea-Toolkit/ydea-monitoring-integration.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"