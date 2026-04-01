#!/usr/bin/env bash
# install-tmate-client.sh
# Install and configure tmate client to connect to the self-hosted server
#
# Usage: bash install-tmate-client.sh
# Compatibile: Ubuntu/Debian
#
# After installation the SSH token is available in: /run/tmate-ssh.txt
# Read token with: cat /run/tmate-ssh.txt

set -euo pipefail

VERSION="1.1.0"

TMATE_SERVER_PORT="10022"
TMATE_SERVER_RSA_FP="SHA256:J71q24ldCtHKvDsVrShV3WAIWVy/73KdgbcqcUo0T80"
TMATE_SERVER_ED25519_FP="SHA256:sfN9/q+YFgewu0TCSJZZAKFjSXSRwhMADw6P1wHpQjo"

log() { echo "[$(date '+%F %T')] $*"; }

log "=== install-tmate-client.sh v${VERSION} ==="

# Ask tmate server IP or FQDN interactively
while true; do
    read -rp "Inserisci IP o FQDN del server tmate (es: 143.110.148.110): " TMATE_SERVER_HOST
    [[ -n "$TMATE_SERVER_HOST" ]] && break
    echo "ERROR: value cannot be empty."
done
log "Server tmate: ${TMATE_SERVER_HOST}:${TMATE_SERVER_PORT}"

# 1. Install tmate
if ! command -v tmate &>/dev/null; then
    log "Installazione tmate..."
    apt-get install -y tmate
else
    log "tmate già installato: $(tmate -V)"
fi

# 2. /etc/tmate.conf (globale - disabilita web share)
log "Configurazione /etc/tmate.conf..."
cat > /etc/tmate.conf << 'EOF'
set -g tmate-web-share off
EOF

# 3. ~/.tmate.conf (root - points to self-hosted server)
log "Configurazione ~/.tmate.conf..."
cat > /root/.tmate.conf << EOF
set -g tmate-server-host ${TMATE_SERVER_HOST}
set -g tmate-server-port ${TMATE_SERVER_PORT}

set -g tmate-server-rsa-fingerprint ${TMATE_SERVER_RSA_FP}
set -g tmate-server-ed25519-fingerprint ${TMATE_SERVER_ED25519_FP}
EOF

# 4. Token writer script
log "Installazione tmate-token-writer.sh..."
cat > /usr/local/bin/tmate-token-writer.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

SOCK="/run/tmate/tmate.sock"
OUT="/run/tmate-ssh.txt"

pgrep -x tmate >/dev/null || exit 0

for _ in $(seq 1 30); do
  [[ -S "$SOCK" ]] && break
  sleep 1
done
[[ -S "$SOCK" ]] || exit 0

TMP="$(mktemp)"
if ! tmate -S "$SOCK" display -p '#{tmate_ssh}' > "$TMP" 2>/dev/null; then
  rm -f "$TMP"
  exit 0
fi

chmod 0600 "$TMP"
mv -f "$TMP" "$OUT"
SCRIPT
chmod +x /usr/local/bin/tmate-token-writer.sh

# 5. tmate.service
log "Installazione tmate.service..."
cat > /etc/systemd/system/tmate.service << 'EOF'
[Unit]
Description=Persistent tmate session (public servers)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
RuntimeDirectory=tmate
RuntimeDirectoryMode=0755
ExecStartPre=/bin/rm -f /run/tmate/tmate.sock
ExecStart=/usr/bin/tmate -S /run/tmate/tmate.sock -F
Restart=always
RestartSec=10
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

# 6. tmate-token.service
cat > /etc/systemd/system/tmate-token.service << 'EOF'
[Unit]
Description=Write current tmate SSH session string to /run/tmate-ssh.txt
After=tmate.service
Requires=tmate.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/tmate-token-writer.sh
EOF

# 7. tmate-token.timer (refresh every 15 seconds)
cat > /etc/systemd/system/tmate-token.timer << 'EOF'
[Unit]
Description=Periodically refresh tmate token file

[Timer]
OnBootSec=10
OnUnitActiveSec=15
AccuracySec=1s
Unit=tmate-token.service

[Install]
WantedBy=timers.target
EOF

# 8. Enable and launch
log "Abilitazione e avvio servizi..."
systemctl daemon-reload
systemctl enable --now tmate.service tmate-token.timer

# 9. Wait and show token
log "Attesa generazione token (max 45s)..."
for i in $(seq 1 45); do
    if [[ -s /run/tmate-ssh.txt ]]; then
        TOKEN=$(cat /run/tmate-ssh.txt)
        log "=== TOKEN TMATE ==="
        echo ""
        echo "$TOKEN"
        echo ""
        log "=== Fine ==="
        exit 0
    fi
    sleep 1
done

log "WARN: Token non ancora disponibile. Riprova con: cat /run/tmate-ssh.txt"
