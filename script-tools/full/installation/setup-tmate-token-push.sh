#!/bin/bash
# setup-tmate-token-push.sh
# Eseguire su ogni HOST CLIENT tmate per configurare il push del token al server
#
# Cosa fa:
#   1. Installa la chiave privata per SSH al server (tmate-token-receiver)
#   2. Modifica tmate-token.service per pushare il token al server
#
# Usage: bash setup-tmate-token-push.sh [SERVER_IP] [SERVER_PORT] [KEY_SOURCE]
# Default: monitor01.nethlab.it port 22 (SSH normale per push token)
#
# Prerequisito: la chiave privata deve essere disponibile in UNO di questi modi (in ordine di priorita'):
#   1. File /tmp/tmate_token_pusher.key (scp da vps-02:/opt/tmate-tokens/receiver_key)
#   2. Variabile d'ambiente TMATE_PUSHER_KEY (export TMATE_PUSHER_KEY='...')
#   3. Chiave gia' presente in /etc/ssh/tmate_token_pusher (reinstallazione)

VERSION="1.2.0"
SERVER_IP="${1:-monitor01.nethlab.it}"
SERVER_PORT="${2:-22}"
KEY_FILE="/etc/ssh/tmate_token_pusher"
SERVICE_FILE="/etc/systemd/system/tmate-token.service"
PUSH_SERVICE="/etc/systemd/system/tmate-token-push.service"

echo "=== setup-tmate-token-push.sh v${VERSION} ==="
echo "Server: ${SERVER_IP}:${SERVER_PORT}"

# 1. Installa chiave privata
# Priorita': file temporaneo > variabile env > chiave gia' presente
if [ -f "/tmp/tmate_token_pusher.key" ]; then
    cp /tmp/tmate_token_pusher.key "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    rm -f /tmp/tmate_token_pusher.key
    echo "[OK] Chiave installata da /tmp/tmate_token_pusher.key"
elif [ -n "${TMATE_PUSHER_KEY:-}" ]; then
    echo "${TMATE_PUSHER_KEY}" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "[OK] Chiave installata da variabile TMATE_PUSHER_KEY"
elif [ -f "$KEY_FILE" ]; then
    echo "[OK] Chiave gia' presente in $KEY_FILE (reinstallazione)"
else
    echo "[ERRORE] Chiave privata non trovata."
    echo "Eseguire prima:"
    echo "  scp checkmk-vps-02:/opt/tmate-tokens/receiver_key /tmp/tmate_token_pusher.key"
    echo "  scp /tmp/tmate_token_pusher.key TARGET:/tmp/tmate_token_pusher.key"
    exit 1
fi

# 2. Aggiorna tmate-token.service oppure crea tmate-token-push.service
if [ -f "$SERVICE_FILE" ]; then
    # == Formato A: tmate-token.service (srv-monitoring, srv-monitoring-us) ==
    # Leggi ExecStart attuale
    CURRENT_EXEC=$(grep '^ExecStart=' "$SERVICE_FILE" | head -1)
    echo "[INFO] ExecStart attuale: $CURRENT_EXEC"

    # Verifica se push gia' configurato
    if grep -q 'tmate_token_pusher' "$SERVICE_FILE"; then
        echo "[INFO] Push gia' configurato nel service, aggiorno..."
    fi

    # Scrivi nuovo service con push incluso
    cat > "$SERVICE_FILE" << SVCEOF
[Unit]
Description=Write current tmate SSH session string to /run/tmate-ssh.txt
After=tmate.service
Requires=tmate.service

[Service]
Type=oneshot
ExecStart=/bin/bash -c 'TOKEN=\$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null); if [ -n "\$TOKEN" ]; then echo "\$TOKEN" > /run/tmate-ssh.txt; echo "\$TOKEN" | ssh -i ${KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p ${SERVER_PORT} root@${SERVER_IP} "\$(hostname -s)" 2>/dev/null || true; fi'
SVCEOF

    systemctl daemon-reload
    echo "[OK] tmate-token.service aggiornato con push"

    # Test immediato
    echo "[INFO] Test push immediato..."
    TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null)
    if [ -z "$TOKEN" ]; then
        echo "[WARN] tmate non attivo, push non eseguito ora. Partira' automaticamente al prossimo timer."
    else
        echo "$TOKEN" | ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p "$SERVER_PORT" "root@${SERVER_IP}" "$(hostname -s)" 2>/dev/null && \
            echo "[OK] Token pushato: $TOKEN" || \
            echo "[WARN] Push fallito (verificare connettivita' a ${SERVER_IP}:${SERVER_PORT})"
    fi

    # Crea timer periodico ogni 5 minuti (aggiorna token se tmate riconoette)
    cat > /etc/systemd/system/tmate-token.timer << TIMEREOF
[Unit]
Description=Periodic push of tmate token to receiver server
After=tmate.service

[Timer]
OnBootSec=30
OnUnitActiveSec=5min
Unit=tmate-token.service

[Install]
WantedBy=timers.target
TIMEREOF

    systemctl daemon-reload
    systemctl enable --now tmate-token.timer 2>/dev/null || true
    echo "[OK] tmate-token.timer creato e avviato (ogni 5 min)"
    systemctl start tmate-token.service 2>/dev/null || true

elif [ -f "/run/tmate/token.txt" ] || systemctl is-active --quiet tmate.service 2>/dev/null; then
    # == Formato B: tmate.service con /run/tmate/token.txt (checkmk-z1plus) ==
    echo "[INFO] Rilevato formato tmate.service con /run/tmate/token.txt"

    # Crea servizio dedicato per il push
    cat > "$PUSH_SERVICE" << SVCEOF
[Unit]
Description=Push tmate token to receiver server
After=tmate.service
Requires=tmate.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 3
ExecStart=/bin/bash -c 'TOKEN=\$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null); if [ -z "\$TOKEN" ] && [ -f "/run/tmate/token.txt" ]; then TOKEN=\$(grep "^RW=" "/run/tmate/token.txt" | cut -d= -f2-); fi; if [ -n "\$TOKEN" ]; then echo "\$TOKEN" | ssh -i ${KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p ${SERVER_PORT} root@${SERVER_IP} "\$(hostname -s)" 2>/dev/null && echo "Token pushato: \$TOKEN" || echo "Push fallito"; fi'

[Install]
WantedBy=multi-user.target
SVCEOF

    # Crea timer periodico ogni 5 minuti (aggiorna token se tmate riconoette)
    cat > /etc/systemd/system/tmate-token-push.timer << TIMEREOF
[Unit]
Description=Periodic push of tmate token to receiver server
After=tmate.service

[Timer]
OnBootSec=30
OnUnitActiveSec=5min
Unit=tmate-token-push.service

[Install]
WantedBy=timers.target
TIMEREOF

    systemctl daemon-reload
    systemctl enable tmate-token-push.service 2>/dev/null || true
    systemctl enable --now tmate-token-push.timer 2>/dev/null || true
    echo "[OK] tmate-token-push.service creato e abilitato"
    echo "[OK] tmate-token-push.timer creato e avviato (ogni 5 min)"

    # Test immediato
    echo "[INFO] Test push immediato..."
    # Priorita': socket (sempre live) > token.txt (scritto solo all'avvio del servizio)
    TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null)
    if [ -z "$TOKEN" ] && [ -f "/run/tmate/token.txt" ]; then
        TOKEN=$(grep "^RW=" /run/tmate/token.txt 2>/dev/null | cut -d= -f2-)
    fi

    if [ -z "$TOKEN" ]; then
        echo "[WARN] Token non disponibile ora. Partira' automaticamente all'avvio di tmate."
    else
        echo "$TOKEN" | ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p "$SERVER_PORT" "root@${SERVER_IP}" "$(hostname -s)" 2>/dev/null && \
            echo "[OK] Token pushato: $TOKEN" || \
            echo "[WARN] Push fallito (verificare connettivita' a ${SERVER_IP}:${SERVER_PORT})"
    fi

else
    echo "[ERRORE] Nessun servizio tmate trovato ($SERVICE_FILE o tmate.service). Eseguire prima install-tmate-client.sh"
    exit 1
fi

echo "=== Setup completato ==="
