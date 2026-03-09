#!/bin/bash
# Test WARNING alert support in ydea_realip
# Simula variabili d'ambiente CheckMK per alert WARNING

export NOTIFY_WHAT="SERVICE"
export NOTIFY_HOSTNAME="test-host-warning-$(date +%s)"
export NOTIFY_SERVICEDESC="Test Service WARNING"
export NOTIFY_SERVICESTATE="WARNING"
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"
export NOTIFY_SERVICEOUTPUT="Test WARNING output - simulazione alert"
export NOTIFY_LONGSERVICEOUTPUT="Dettagli aggiuntivi del test WARNING"
export NOTIFY_SERVICEACKAUTHOR=""
export NOTIFY_SERVICEACKCOMMENT=""
export NOTIFY_LONGDATETIME="$(date '+%Y-%m-%d %H:%M:%S')"
export NOTIFY_SHORTDATETIME="$(date '+%Y-%m-%d %H:%M:%S')"
export NOTIFY_CONTACTNAME="checkmk-notify"
export NOTIFY_HOSTADDRESS="192.168.1.100"
export NOTIFY_HOSTATTEMPT="1"
export NOTIFY_HOSTMAXATTEMPTS="3"
export NOTIFY_SERVICESTATETYPE="HARD"

# Path al launcher remoto
LAUNCHER="/opt/checkmk-tools/script-notify-checkmk/remote/rydea_realip"

echo "=========================================="
echo "TEST WARNING ALERT - COMPLETO"
echo "=========================================="
echo "Host: $NOTIFY_HOSTNAME"
echo "Service: $NOTIFY_SERVICEDESC"
echo "State: $NOTIFY_LASTSERVICESTATE -> $NOTIFY_SERVICESTATE"
echo "Output: $NOTIFY_SERVICEOUTPUT"
echo "Launcher: $LAUNCHER"
echo "=========================================="
echo ""

# Verifica che il launcher esista
if [[ ! -f "$LAUNCHER" ]]; then
    echo "⚠ ERRORE: Launcher non trovato in $LAUNCHER"
    exit 1
fi

echo "1. Eseguo launcher..."
$LAUNCHER
RESULT=$?

echo ""
echo "2. Exit code: $RESULT"
echo ""

# Mostra ultimi log
echo "3. Ultimi 20 log:"
echo "---"
tail -20 /var/log/ydea_notify.log 2>/dev/null || echo "Log non disponibile"
echo "---"
echo ""

# Verifica cache
echo "4. Ticket in cache per $NOTIFY_HOSTNAME:"
jq -r "to_entries | .[] | select(.key | contains(\"$NOTIFY_HOSTNAME\")) | \"\(.key): ticket #\(.value.ticket_id) - stato \(.value.state)\"" /tmp/ydea_checkmk_tickets.json 2>/dev/null || echo "Nessun ticket in cache"

echo ""
echo "=========================================="
echo "Test completato!"
echo "Controlla:"
echo "1. Ticket creato su Ydea con priorità 'high' (3)"
echo "2. SLA_ID = 147 (8-tipologie)"
echo "3. Titolo: [WARNING] $NOTIFY_HOSTNAME - Test Service WARNING"
echo "=========================================="
