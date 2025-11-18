#!/bin/bash
# Launcher base per eseguire uno script remoto dal repo GitHub
# Inserisci l'URL dello script qui sotto

SCRIPT_URL="https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/Proxmox/nopolling/check-proxmox-vm-snapshot-status.sh"

# Puoi passare parametri aggiuntivi allo script remoto
# Uso: bash rcheck-proxmox-vm-snapshot-status.sh [parametri]

bash <(curl -fsSL "$SCRIPT_URL") "$@"
