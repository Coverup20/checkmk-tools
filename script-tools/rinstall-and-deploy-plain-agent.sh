#!/bin/bash
# Launcher per eseguire install-and-deploy-plain-agent.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/install-and-deploy-plain-agent.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"