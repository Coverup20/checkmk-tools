#!/bin/bash
# Launcher per eseguire install-frpc-dryrun.sh remoto dal repo GitHub

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/install-frpc-dryrun.sh"

# Esegue lo script remoto
bash <$(curl -fsSL "$SCRIPT_URL") "$@"