#!/bin/bash
# ============================================
# Installazione e Configurazione Postfix Smarthost
# ============================================

set -euo pipefail

echo ">>> Installazione Postfix"
apt update -qq
apt install -y postfix mailutils libsasl2-modules

echo ">>> Configurazione Postfix come Smarthost"
read -p "Inserisci SMTP relay (es. smtp.gmail.com): " RELAYHOST
read -p "Inserisci porta SMTP (default 587): " RELAYPORT
RELAYPORT=${RELAYPORT:-587}
read -p "Inserisci utente SMTP: " SMTP_USER
set +o history
read -s -p "Inserisci password SMTP: " SMTP_PASS
set -o history
echo
read -p "Inserisci indirizzo email di test: " TEST_EMAIL

postconf -e "relayhost = [$RELAYHOST]:$RELAYPORT"
postconf -e "smtp_use_tls = yes"
postconf -e "smtp_sasl_auth_enable = yes"
postconf -e "smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd"
postconf -e "smtp_sasl_security_options = noanonymous"
postconf -e "smtp_sasl_tls_security_options = noanonymous"

echo "[$RELAYHOST]:$RELAYPORT $SMTP_USER:$SMTP_PASS" > /etc/postfix/sasl_passwd
chmod 600 /etc/postfix/sasl_passwd
postmap /etc/postfix/sasl_passwd

systemctl enable postfix
systemctl restart postfix

echo ">>> Test invio email..."
echo "Test Postfix Smarthost su $(hostname)" | mail -s "Checkmk Smarthost Test" "$TEST_EMAIL"

echo "============================================"
echo " Postfix installato e configurato come Smarthost"
echo " Relayhost: $RELAYHOST"
echo " Porta: $RELAYPORT"
echo " Utente: $SMTP_USER"
echo " Email di test: $TEST_EMAIL"
echo "============================================"
