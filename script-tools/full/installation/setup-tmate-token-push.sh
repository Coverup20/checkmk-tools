#!/bin/bash
# setup-tmate-token-push.sh
# Run tmate on each CLIENT HOST to configure token push to the server
#
# Cosa fa:
# 1. Install the private key for SSH to the server (tmate-token-receiver)
# 2. Edit tmate-token.service to push the token to the server
#
# Usage: bash setup-tmate-token-push.sh [SERVER_IP] [SERVER_PORT] [KEY_SOURCE]
# Default: monitor01.nethlab.it port 22 (normal SSH for token push)
#
# Prerequisite: The private key must be available in ONE of these ways (in order of priority):
# 1. File /tmp/tmate_token_pusher.key (scp from vps-02:/opt/tmate-tokens/receiver_key)
#   2. Variabile d'ambiente TMATE_PUSHER_KEY (export TMATE_PUSHER_KEY='...')
# 3. Key already present in /etc/ssh/tmate_token_pusher (reinstallation)

VERSION="1.2.0"
SERVER_IP="${1:-monitor01.nethlab.it}"
SERVER_PORT="${2:-22}"
KEY_FILE="/etc/ssh/tmate_token_pusher"
SERVICE_FILE="/etc/systemd/system/tmate-token.service"
PUSH_SERVICE="/etc/systemd/system/tmate-token-push.service"

echo "=== setup-tmate-token-push.sh v${VERSION} ==="
echo "Server: ${SERVER_IP}:${SERVER_PORT}"

# 1. Install private key
# Priority: temporary file > env variable > key already present
if [ -f "/tmp/tmate_token_pusher.key" ]; then
    cp /tmp/tmate_token_pusher.key "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    rm -f /tmp/tmate_token_pusher.key
    echo "[OK] Key installed from /tmp/tmate_token_pusher.key"
elif [ -n "${TMATE_PUSHER_KEY:-}" ]; then
    echo "${TMATE_PUSHER_KEY}" > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "[OK] Key installed by TMATE_PUSHER_KEY variable"
elif [ -f "$KEY_FILE" ]; then
    echo "[OK] Key already present in $KEY_FILE (reinstallation)"
else
    echo "[ERROR] Private key not found."
    echo "Run first:"
    echo "  scp checkmk-vps-02:/opt/tmate-tokens/receiver_key /tmp/tmate_token_pusher.key"
    echo "  scp /tmp/tmate_token_pusher.key TARGET:/tmp/tmate_token_pusher.key"
    exit 1
fi

# 2. Update tmate-token.service or create tmate-token-push.service
if [ -f "$SERVICE_FILE" ]; then
    # == Format A: tmate-token.service (srv-monitoring, srv-monitoring-us) ==
    # Leggi ExecStart attuale
    CURRENT_EXEC=$(grep '^ExecStart=' "$SERVICE_FILE" | head -1)
    echo "[INFO] ExecStart attuale: $CURRENT_EXEC"

    # Check if push is already configured
    if grep -q 'tmate_token_pusher' "$SERVICE_FILE"; then
        echo "[INFO] Push already configured in the service, updating..."
    fi

    # Write new service with push included
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
    echo "[OK] tmate-token.service updated with push"

    # Test immediato
    echo "[INFO] Test push immediato..."
    TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null)
    if [ -z "$TOKEN" ]; then
        echo "[WARN] tmate down, push not done now. It will automatically start on the next timer."
    else
        echo "$TOKEN" | ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p "$SERVER_PORT" "root@${SERVER_IP}" "$(hostname -s)" 2>/dev/null && \
            echo "[OK] Pushed token: $TOKEN" || \
            echo "[WARN] Push failed (check connectivity to ${SERVER_IP}:${SERVER_PORT})"
    fi

    # Create periodic timer every 5 minutes (update token if tmate recognizes)
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
    echo "[OK] tmate-token.timer created and started (every 5 min)"
    systemctl start tmate-token.service 2>/dev/null || true

elif [ -f "/run/tmate/token.txt" ] || systemctl is-active --quiet tmate.service 2>/dev/null; then
    # == Format B: tmate.service with /run/tmate/token.txt (checkmk-z1plus) ==
    echo "[INFO] Detected tmate.service format with /run/tmate/token.txt"

    # Create dedicated service for push
    cat > "$PUSH_SERVICE" << SVCEOF
[Unit]
Description=Push tmate token to receiver server
After=tmate.service
Requires=tmate.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 3
ExecStart=/bin/bash -c 'TOKEN=\$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null); if [ -z "\$TOKEN" ] && [ -f "/run/tmate/token.txt" ]; then TOKEN=\$(grep "^RW=" "/run/tmate/token.txt" | cut -d= -f2-); fi; if [ -n "\$TOKEN" ]; then echo "\$TOKEN" | ssh -i ${KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p ${SERVER_PORT} root@${SERVER_IP} "\$(hostname -s)" 2>/dev/null && echo "Pushed token: \$TOKEN" || echo "Push failed"; fi'

[Install]
WantedBy=multi-user.target
SVCEOF

    # Create periodic timer every 5 minutes (update token if tmate recognizes)
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
    echo "[OK] tmate-token-push.service created and enabled"
    echo "[OK] tmate-token-push.timer created and started (every 5 min)"

    # Test immediato
    echo "[INFO] Test push immediato..."
    # Priority: socket (always live) > token.txt (written only when the service starts)
    TOKEN=$(tmate -S /run/tmate/tmate.sock display -p "#{tmate_ssh}" 2>/dev/null)
    if [ -z "$TOKEN" ] && [ -f "/run/tmate/token.txt" ]; then
        TOKEN=$(grep "^RW=" /run/tmate/token.txt 2>/dev/null | cut -d= -f2-)
    fi

    if [ -z "$TOKEN" ]; then
        echo "[WARN] Token not available now. It will start automatically when tmate starts."
    else
        echo "$TOKEN" | ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no -o ConnectTimeout=5 -o BatchMode=yes -p "$SERVER_PORT" "root@${SERVER_IP}" "$(hostname -s)" 2>/dev/null && \
            echo "[OK] Pushed token: $TOKEN" || \
            echo "[WARN] Push failed (check connectivity to ${SERVER_IP}:${SERVER_PORT})"
    fi

else
    echo "[ERROR] No tmate service found ($SERVICE_FILE or tmate.service). Run install-tmate-client.sh first"
    exit 1
fi

echo "=== Setup complete ==="
