#!/usr/bin/env bash
set -euo pipefail

ENV="/opt/checkmk-tools/install/checkmk-installer/.env"

if grep -q '^MAIL_FROM=' "$ENV"; then
  sed -i 's|^MAIL_FROM=.*|MAIL_FROM="no-reply@nethesis.it"|' "$ENV"
else
  echo 'MAIL_FROM="no-reply@nethesis.it"' >> "$ENV"
fi

cat > /etc/postfix/generic <<'EOF'
root no-reply@nethesis.it
root@srv-monitoring no-reply@nethesis.it
root@srv-monitoring.nethesis.it no-reply@nethesis.it
checkmk@srv-monitoring no-reply@nethesis.it
checkmk@srv-monitoring.nethesis.it no-reply@nethesis.it
@srv-monitoring no-reply@nethesis.it
@srv-monitoring.nethesis.it no-reply@nethesis.it
EOF

chmod 600 /etc/postfix/generic
postmap /etc/postfix/generic
chmod 600 /etc/postfix/generic.db
postconf -e 'smtp_generic_maps = hash:/etc/postfix/generic'
systemctl reload postfix

echo "===== CONFIG ====="
postconf -n | grep -E '^smtp_generic_maps'
grep -E '^MAIL_FROM=' "$ENV"

echo "===== TEST SEND ====="
if [[ -f /tmp/smtp-smarthost-test.sh ]]; then
  bash /tmp/smtp-smarthost-test.sh marzio@nethesis.it
else
  echo "Test script not found: /tmp/smtp-smarthost-test.sh"
fi
