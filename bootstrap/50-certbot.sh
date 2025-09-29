#!/usr/bin/env bash
set -euo pipefail

apt-get update -y
apt-get install -y certbot

WS="${WEBSERVER:-apache}"
case "$WS" in
  apache)
    apt-get install -y apache2 python3-certbot-apache
    ;;
  nginx)
    apt-get install -y nginx python3-certbot-nginx
    ;;
  standalone)
    ;;
  *)
    echo "Valore WEBSERVER non valido: $WS (usa apache|nginx|standalone)"
    exit 1
    ;;
esac

if [[ -n "${LETSENCRYPT_EMAIL:-}" || -n "${LETSENCRYPT_DOMAINS:-}" ]]; then
  mkdir -p /etc/letsencrypt
  CLI_INI="/etc/letsencrypt/cli.ini"
  {
    [[ -n "${LETSENCRYPT_EMAIL:-}" ]] && echo "email = ${LETSENCRYPT_EMAIL}"
    [[ -n "${LETSENCRYPT_DOMAINS:-}" ]] && echo "# domains = ${LETSENCRYPT_DOMAINS}"
    echo "agree-tos = true"
    echo "non-interactive = true"
  } > "$CLI_INI"
fi

echo "Certbot installato (nessuna challenge eseguita)."