#!/bin/bash
# setup-tmate-token-push.sh
# Eseguire su ogni HOST CLIENT tmate per configurare il push del token al server
#
# Cosa fa:
#   1. Installa la chiave privata per SSH al server (tmate-token-receiver)
#   2. Modifica tmate-token.service per pushare il token al server
#
# Usage: bash setup-tmate-token-push.sh [SERVER_IP] [SERVER_PORT]
# Default: 143.110.148.110 port 22

VERSION="1.0.2"
SERVER_IP="${1:-monitor01.nethlab.it}"
SERVER_PORT="${2:-22}"
KEY_FILE="/etc/ssh/tmate_token_pusher"
SERVICE_FILE="/etc/systemd/system/tmate-token.service"
PUSH_SERVICE="/etc/systemd/system/tmate-token-push.service"

# Chiave privata del receiver (generata dal server)
PRIVATE_KEY='-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACCKv7wISky+KX1KI3gFduMwUWq9A6JTsxCZs39UCj+cuwAAAJhvIgyDbyIM
gwAAAAtzc2gtZWQyNTUxOQAAACCKv7wISky+KX1KI3gFduMwUWq9A6JTsxCZs39UCj+cuw
AAAEDLVTIKBkFbJ9pFbQaXADuLQQToWYDjDSr3Y/leb9BIsoq/vAhKTL4pfUojeAV24zBR
ar0DolOzEJmzf1QKP5y7AAAAFHRtYXRlLXRva2VuLXJlY2VpdmVyAQ==
-----END OPENSSH PRIVATE KEY-----'

echo "=== setup-tmate-token-push.sh v${VERSION} ==="
echo "Server: ${SERVER_IP}:${SERVER_PORT}"

# 1. Installa chiave privata
echo "$PRIVATE_KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE"
echo "[OK] Chiave installata in $KEY_FILE"

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
ExecStart=/bin/bash -c 'TOKEN=\$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null); if [ -n "\$TOKEN" ]; then echo "\$TOKEN" > /run/tmate-ssh.txt; echo "\$TOKEN" | ssh -i ${KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p ${SERVER_PORT} root@${SERVER_IP} token-push 2>/dev/null || true; fi'
SVCEOF

    systemctl daemon-reload
    echo "[OK] tmate-token.service aggiornato con push"

    # Test immediato
    echo "[INFO] Test push immediato..."
    TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null)
    if [ -z "$TOKEN" ]; then
        echo "[WARN] tmate non attivo, push non eseguito ora. Partira' automaticamente al prossimo timer."
    else
        echo "$TOKEN" | ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p "$SERVER_PORT" "root@${SERVER_IP}" token-push 2>/dev/null && \
            echo "[OK] Token pushato: $TOKEN" || \
            echo "[WARN] Push fallito (verificare connettivita' a ${SERVER_IP}:${SERVER_PORT})"
    fi

    systemctl start tmate-token.timer 2>/dev/null || true
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
ExecStart=/bin/bash -c 'TOK_FILE=/run/tmate/token.txt; if [ -f "\$TOK_FILE" ]; then TOKEN=\$(grep "^RW=" "\$TOK_FILE" | cut -d= -f2-); else TOKEN=\$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null); fi; if [ -n "\$TOKEN" ]; then echo "\$TOKEN" | ssh -i ${KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p ${SERVER_PORT} root@${SERVER_IP} token-push 2>/dev/null && echo "Token pushato: \$TOKEN" || echo "Push fallito"; fi'

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable tmate-token-push.service 2>/dev/null || true
    echo "[OK] tmate-token-push.service creato e abilitato"

    # Test immediato
    echo "[INFO] Test push immediato..."
    TOKEN=""
    if [ -f "/run/tmate/token.txt" ]; then
        TOKEN=$(grep "^RW=" /run/tmate/token.txt 2>/dev/null | cut -d= -f2-)
    fi
    if [ -z "$TOKEN" ]; then
        TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null)
    fi

    if [ -z "$TOKEN" ]; then
        echo "[WARN] Token non disponibile ora. Partira' automaticamente all'avvio di tmate."
    else
        echo "$TOKEN" | ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p "$SERVER_PORT" "root@${SERVER_IP}" token-push 2>/dev/null && \
            echo "[OK] Token pushato: $TOKEN" || \
            echo "[WARN] Push fallito (verificare connettivita' a ${SERVER_IP}:${SERVER_PORT})"
    fi

else
    echo "[ERRORE] Nessun servizio tmate trovato ($SERVICE_FILE o tmate.service). Eseguire prima install-tmate-client.sh"
    exit 1
fi

echo "=== Setup completato ==="
