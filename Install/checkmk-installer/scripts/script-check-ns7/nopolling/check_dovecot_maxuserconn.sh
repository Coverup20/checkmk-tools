#!/bin/bash
# check_dovecot_maxuserconn.sh

SERVICE="Dovecot_maxuserconn"

# Estraggo il valore (terza colonna)
MAXCONN=$(doveconf -a 2>/dev/null | awk '/^mail_max_userip_connections/ {print $3}' | head -n1)

if [ -z "$MAXCONN" ]; then
    echo "0 $SERVICE - unset"
else
    echo "0 $SERVICE - $MAXCONN"
fi

