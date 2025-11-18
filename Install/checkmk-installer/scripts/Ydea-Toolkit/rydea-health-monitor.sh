#!/bin/bash
# Launcher per eseguire ydea-health-monitor.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/Ydea-Toolkit/ydea-health-monitor.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"