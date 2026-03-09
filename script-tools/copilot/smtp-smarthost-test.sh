#!/usr/bin/env bash
set -euo pipefail

DEST_EMAIL="${1:-marzio@nethesis.it}"
ENV_FILE="/opt/checkmk-tools/install/checkmk-installer/.env"

SMART_HOST="smtp-relay.nethesis.it"
SMTP_USER=""
SMTP_PASSWORD=""
MAIL_FROM_ADDR="checkmk@srv-monitoring"

if [[ -f "$ENV_FILE" ]]; then
  source "$ENV_FILE"
  SMART_HOST="${SMTP_RELAY_HOST:-$SMART_HOST}"
  SMTP_USER="${SMTP_RELAY_USER:-}"
  SMTP_PASSWORD="${SMTP_RELAY_PASSWORD:-}"
  if [[ -n "${MAIL_FROM:-}" ]]; then
    MAIL_FROM_ADDR="$MAIL_FROM"
  fi
fi

if ! command -v postconf >/dev/null 2>&1; then
  echo "[SETUP] Postfix non trovato: installazione in corso..."
  echo "postfix postfix/mailname string srv-monitoring" | debconf-set-selections
  echo "postfix postfix/main_mailer_type string Internet Site" | debconf-set-selections
  DEBIAN_FRONTEND=noninteractive apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y postfix libsasl2-modules ca-certificates bsd-mailx
fi

if [[ -n "$SMTP_USER" && -n "$SMTP_PASSWORD" ]]; then
  echo "[SETUP] Configuro postfix relay su ${SMART_HOST}:587"
  postconf -e "relayhost = [${SMART_HOST}]:587"
  postconf -e "smtp_sasl_auth_enable = yes"
  postconf -e "smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd"
  postconf -e "smtp_sasl_security_options = noanonymous"
  postconf -e "smtp_use_tls = yes"
  postconf -e "smtp_tls_security_level = encrypt"
  postconf -e "smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt"
  printf '[%s]:587 %s:%s\n' "$SMART_HOST" "$SMTP_USER" "$SMTP_PASSWORD" > /etc/postfix/sasl_passwd
  chmod 600 /etc/postfix/sasl_passwd
  postmap /etc/postfix/sasl_passwd
  chmod 600 /etc/postfix/sasl_passwd.db
  systemctl enable --now postfix
  systemctl restart postfix
fi

printf '===== SMTP SMART HOST CHECK =====\n'
printf 'Smart host: %s\n' "$SMART_HOST"
printf 'Recipient : %s\n\n' "$DEST_EMAIL"

printf '[1] Postfix service\n'
systemctl is-enabled postfix 2>/dev/null || true
systemctl is-active postfix 2>/dev/null || true
printf '\n'

printf '[2] Key Postfix settings\n'
postconf -n | grep -E '^relayhost|^smtp_sasl_auth_enable|^smtp_sasl_password_maps|^smtp_use_tls|^smtp_tls_security_level|^myhostname|^myorigin' || true
printf '\n'

printf '[3] SASL credential files\n'
ls -l /etc/postfix/sasl_passwd* 2>/dev/null || echo 'No /etc/postfix/sasl_passwd* found'
printf '\n'

printf '[4] DNS + TCP checks to smart host\n'
getent hosts "$SMART_HOST" || true
python3 - <<PY
import socket
host = "${SMART_HOST}"
for port in (25, 587):
    s = socket.socket()
    s.settimeout(5)
    try:
        s.connect((host, port))
        print(f"TCP {port}: OK")
    except Exception as e:
        print(f"TCP {port}: FAIL ({e})")
    finally:
        s.close()
PY
printf '\n'

printf '[5] Sending test email\n'
SUBJ="[TEST] CheckMK srv-monitoring SMTP $(date +%Y-%m-%d_%H:%M:%S)"
{
  echo "From: ${MAIL_FROM_ADDR}"
  echo "To: ${DEST_EMAIL}"
  echo "Subject: ${SUBJ}"
  echo
  echo "Test email from srv-monitoring via smart host ${SMART_HOST}"
  echo "Timestamp: $(date -Is)"
  echo "Host: $(hostname -f 2>/dev/null || hostname)"
} | /usr/sbin/sendmail -v "${DEST_EMAIL}"
printf '\n'

printf '[6] Mail queue\n'
postqueue -p || true
printf '\n'

printf '[7] Log tail\n'
if [[ -f /var/log/mail.log ]]; then
  tail -n 80 /var/log/mail.log
else
  journalctl -u postfix -n 80 --no-pager || true
fi
