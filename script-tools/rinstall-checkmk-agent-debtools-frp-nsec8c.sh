#!/bin/bash
# Launcher per eseguire install-checkmk-agent-debtools-frp-nsec8c.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/install-checkmk-agent-debtools-frp-nsec8c.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"