#!/bin/bash
# Launcher per eseguire deploy-plain-agent-multi.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/deploy-plain-agent-multi.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"