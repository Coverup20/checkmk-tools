#!/usr/bin/env bash
# =====================================================
# Installazione e Configurazione Certbot (interattiva)
# =====================================================

set -euo pipefail

echo ">>> Aggiornamento repository..."
apt-get update -y >/dev/null

echo ">>> Installazione base di Certbot..."
apt-get install -y certbot >/dev/null

# Determina il webserver
read -p "Specifica webserver (apache/nginx/standalone) [apache]: " WS
WS="${WS:-apache}"

case "$WS" in
  apache)
    echo ">>> Installazione plugin Apache..."
    apt-get install -y apache2 python3-certbot-apache >/dev/null
    ;;
  nginx)
    echo ">>> Installazione plugin Nginx..."
    apt-get install -y nginx python3-certbot-nginx >/dev/null
    ;;
  standalone)
    echo ">>> Modalità standalone selezionata (nessun webserver installato)."
    ;;
  *)
    echo "ERRORE: Valore WEBSERVER non valido: $WS"
    exit 1
    ;;
esac

# Dati utente
read -p "Inserisci email Let's Encrypt (lascia vuoto per nessuna): " LETSENCRYPT_EMAIL
read -p "Inserisci domini separati da virgola (es. example.com,www.example.com): " LETSENCRYPT_DOMAINS

mkdir -p /etc/letsencrypt
CLI_INI="/etc/letsencrypt/cli.ini"

echo ">>> Creazione configurazione globale in $CLI_INI"
{
  [[ -n "$LETSENCRYPT_EMAIL" ]] && echo "email = $LETSENCRYPT_EMAIL"
  echo "agree-tos = true"
  echo "non-interactive = true"
  echo "quiet = true"
} > "$CLI_INI"

echo ">>> Certbot installato e configurato."

# Esecuzione challenge opzionale
read -p "Vuoi eseguire subito la challenge Let's Encrypt per ottenere il certificato? (s/n): " RUN_CHALLENGE
if [[ "$RUN_CHALLENGE" =~ ^[sS]$ ]]; then
  if [[ -z "$LETSENCRYPT_DOMAINS" ]]; then
    echo "ERRORE: Nessun dominio specificato. Impossibile procedere con la challenge."
    exit 1
  fi

  echo ">>> Avvio richiesta certificato..."
  IFS=',' read -r -a DOM_ARRAY <<< "$LETSENCRYPT_DOMAINS"
  DOMAIN_ARGS=()
  for D in "${DOM_ARRAY[@]}"; do
    DOMAIN_ARGS+=("-d" "$D")
  done

  certbot certonly --"$WS" "${DOMAIN_ARGS[@]}"
  echo ">>> Challenge completata (se non ci sono errori sopra)."
else
  echo ">>> Challenge non eseguita. Potrai lanciarla manualmente in seguito, es.:"
  echo "    certbot certonly --$WS -d dominio.it"
fi

echo ">>> Installazione Certbot completata."
