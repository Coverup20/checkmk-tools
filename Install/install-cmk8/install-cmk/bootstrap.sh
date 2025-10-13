#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
else
  echo "âš ï¸  .env non trovato. Copia .env.example in .env e personalizza."
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Devi eseguire come root o con sudo."
  exit 1
fi

export TIMEZONE SSH_PORT PERMIT_ROOT_LOGIN CLIENT_ALIVE_INTERVAL CLIENT_ALIVE_COUNTMAX LOGIN_GRACE_TIME ROOT_PASSWORD OPEN_HTTP_HTTPS LETSENCRYPT_EMAIL LETSENCRYPT_DOMAINS WEBSERVER NTP_SERVERS CHECKMK_ADMIN_PASSWORD CHECKMK_DEB_URL

run(){ echo -e "\n===== ESECUZIONE: $1 ====="; bash "$SCRIPT_DIR/scripts/$1"; }

run 10-ssh.sh
run 15-ntp.sh
run 20-packages.sh
run 25-postfix.sh
run 30-firewall.sh
run 40-fail2ban.sh
run 50-certbot.sh
run 60-checkmk.sh
run 80-timeshift.sh

echo -e "\nâœ… Bootstrap completato."
