#!/bin/bash
# check_ssh_root_sessions.sh
# Notifica se ci sono sessioni SSH aperte come root

SERVICE="SSH_root_sessions"

# Conta sessioni root correnti (utenti collegati con root via SSH)
SESSIONS=$(who | awk '$1 == "root" {count++} END {print count+0}')

if [ "$SESSIONS" -gt 0 ]; then
    IPS=$(who | awk '$1=="root"{print $5}' | tr -d '()' | paste -sd "," -)
    echo "2 $SERVICE - $SESSIONS root session(s) from $IPS"
else
    echo "0 $SERVICE - no root sessions"
fi

