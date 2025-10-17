#!/bin/bash
# check_dovecot_sessions.sh

SERVICE="Dovecot_sessions"
SESSIONS=$(doveadm who 2>/dev/null | wc -l)

# Sintassi: <status> <service_name> - <descrizione>
echo "0 $SERVICE - $SESSIONS active session(s)"

