#!/bin/bash
# ==========================================================
#  Installazione Auto Git Sync Service
#  Installa e configura il servizio di sync automatico
#  Autore: ChatGPT per Marzio Bordin
# ==========================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="auto-git-sync.service"
SCRIPT_FILE="auto-git-sync.sh"

echo "========================================="
echo "  Installazione Auto Git Sync Service"
echo "========================================="
echo ""

# Verifica esecuzione come root
if [[ $EUID -ne 0 ]]; then
    echo "❌ Questo script deve essere eseguito come root"
    echo "   Usa: sudo bash install-auto-git-sync.sh"
    exit 1
fi

echo "✅ Esecuzione come root"

# Verifica esistenza file
if [[ ! -f "$SCRIPT_DIR/$SCRIPT_FILE" ]]; then
    echo "❌ File non trovato: $SCRIPT_FILE"
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/$SERVICE_FILE" ]]; then
    echo "❌ File non trovato: $SERVICE_FILE"
    exit 1
fi

echo "✅ File trovati"

# Rendi eseguibile lo script
chmod +x "$SCRIPT_DIR/$SCRIPT_FILE"
echo "✅ Permessi di esecuzione impostati"

# Copia il service file in systemd
cp "$SCRIPT_DIR/$SERVICE_FILE" /etc/systemd/system/
echo "✅ Service file copiato in /etc/systemd/system/"

# Ricarica systemd
systemctl daemon-reload
echo "✅ Systemd ricaricato"

# Abilita il servizio all'avvio
systemctl enable auto-git-sync.service
echo "✅ Servizio abilitato all'avvio"

# Mostra menu opzioni
echo ""
echo "========================================="
echo "  Installazione Completata!"
echo "========================================="
echo ""
echo "Comandi disponibili:"
echo ""
echo "  • Avvia servizio:"
echo "    systemctl start auto-git-sync"
echo ""
echo "  • Ferma servizio:"
echo "    systemctl stop auto-git-sync"
echo ""
echo "  • Stato servizio:"
echo "    systemctl status auto-git-sync"
echo ""
echo "  • Log in tempo reale:"
echo "    journalctl -u auto-git-sync -f"
echo ""
echo "  • Log completo:"
echo "    tail -f /var/log/auto-git-sync.log"
echo ""

read -p "Vuoi avviare il servizio ora? (s/N): " start_now

if [[ "$start_now" =~ ^[sS]$ ]]; then
    systemctl start auto-git-sync
    echo ""
    echo "✅ Servizio avviato!"
    echo ""
    sleep 2
    systemctl status auto-git-sync --no-pager
else
    echo ""
    echo "ℹ️  Servizio non avviato. Usa 'systemctl start auto-git-sync' per avviarlo."
fi

echo ""
echo "========================================="
