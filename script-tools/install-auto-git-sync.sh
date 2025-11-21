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
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# Chiedi intervallo di sync
echo ""
echo "⏱️  Configurazione intervallo di sync"
echo ""
echo "Scegli ogni quanto eseguire il git pull:"
echo "  1) Ogni 30 secondi"
echo "  2) Ogni 1 minuto (consigliato)"
echo "  3) Ogni 5 minuti"
echo "  4) Ogni 10 minuti"
echo "  5) Ogni 30 minuti"
echo "  6) Personalizzato"
echo ""
read -p "Scelta [2]: " interval_choice

case "$interval_choice" in
    1) SYNC_INTERVAL=30 ;;
    2|"") SYNC_INTERVAL=60 ;;
    3) SYNC_INTERVAL=300 ;;
    4) SYNC_INTERVAL=600 ;;
    5) SYNC_INTERVAL=1800 ;;
    6)
        read -p "Inserisci intervallo in secondi: " SYNC_INTERVAL
        if ! [[ "$SYNC_INTERVAL" =~ ^[0-9]+$ ]] || [ "$SYNC_INTERVAL" -lt 10 ]; then
            echo "❌ Valore non valido, uso default 60 secondi"
            SYNC_INTERVAL=60
        fi
        ;;
    *)
        echo "❌ Scelta non valida, uso default 60 secondi"
        SYNC_INTERVAL=60
        ;;
esac

echo "✅ Intervallo impostato: $SYNC_INTERVAL secondi"
echo ""

# Rileva l'utente proprietario del repository
REPO_OWNER=$(stat -c '%U' "$REPO_DIR")
REPO_OWNER_HOME=$(eval echo "~$REPO_OWNER")

echo "ℹ️  Repository owner: $REPO_OWNER"
echo "ℹ️  Repository path: $REPO_DIR"
echo "ℹ️  Home directory: $REPO_OWNER_HOME"
echo ""

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

# Crea service file personalizzato
echo "ℹ️  Creazione service file personalizzato..."
cat > /tmp/auto-git-sync.service.tmp << EOF
[Unit]
Description=Auto Git Sync Service
After=network.target

[Service]
Type=simple
User=$REPO_OWNER
WorkingDirectory=$REPO_OWNER_HOME
ExecStart=/bin/bash $REPO_DIR/script-tools/auto-git-sync.sh $SYNC_INTERVAL
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Copia il service file in systemd
cp /tmp/auto-git-sync.service.tmp /etc/systemd/system/auto-git-sync.service
rm /tmp/auto-git-sync.service.tmp
echo "✅ Service file creato e installato"

# Ricarica systemd
systemctl daemon-reload
echo "✅ Systemd ricaricato"

# Abilita il servizio all'avvio
systemctl enable auto-git-sync.service
echo "✅ Servizio abilitato all'avvio"

# Riavvia il servizio se già attivo
if systemctl is-active --quiet auto-git-sync.service; then
    echo "ℹ️  Servizio già attivo, riavvio in corso..."
    systemctl restart auto-git-sync.service
    echo "✅ Servizio riavviato con nuova configurazione"
fi

# Mostra menu opzioni
echo ""
echo "========================================="
echo "  Installazione Completata!"
echo "========================================="
echo ""
echo "📊 Configurazione:"
echo "   • Utente: $REPO_OWNER"
echo "   • Repository: $REPO_DIR"
echo "   • Intervallo sync: $SYNC_INTERVAL secondi"
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
