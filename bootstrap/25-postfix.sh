#!/bin/bash
# ============================================
# Installazione e configurazione Postfix Smarthost
# ============================================

set -euo pipefail

echo ">>> Installazione Postfix"
apt update
apt install -y postfix mailutils libsasl2-modules

echo ">>> Configurazione Postfix come smarthost"
read -p "Inserisci SMTP relay (es. smtp.gmail.com:587): " RELAYHOST
read -p "Inserisci utente SMTP: " SMTP_USER
read -s -p "Inserisci password SMTP: " SMTP_PASS
echo

postconf -e "relayhost = [$RELAYHOST]"
postconf -e "smtp_use_tls = yes"
postconf -e "smtp_sasl_auth_enable = yes"
postconf -e "smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd"
postconf -e "smtp_sasl_security_options = noanonymous"
postconf -e "smtp_sasl_tls_security_options = noanonymous"

echo "[$RELAYHOST] $SMTP_USER:$SMTP_PASS" > /etc/postfix/sasl_passwd
chmod 600 /etc/postfix/sasl_passwd
postmap /etc/postfix/sasl_passwd

systemctl enable postfix
systemctl restart postfix

echo ">>> Test invio email"
echo "Test Postfix smarthost su $(hostname)" | mail -s "Checkmk Smarthost Test" $SMTP_USER

echo "============================================"
echo " Postfix installato e configurato come smarthost"
echo " Relayhost: $RELAYHOST"
echo " Utente: $SMTP_USER"
echo "============================================"