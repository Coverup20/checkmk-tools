#!/bin/bash

# check_ssh_root_sessions.sh

# Notifica se ci sono sessioni SSH aperte come root


SERVICE="Ubuntu.SSH.Count"


# Conta sessioni root correnti (utenti collegati con root via SSH)

SESSIONS=$(who | awk '$1 == "root" {count++} END {print count+0}')

if [ "$SESSIONS" -eq 0 ]; then
    echo "0 $SERVICE - no root sessions"
elif [ "$SESSIONS" -le 5 ]; then
    IPS=$(who | awk '$1=="root"{print $5}' | tr -d '()' | paste -sd "," -)
    echo "1 $SERVICE - $SESSIONS root session(s) from $IPS"
elif [ "$SESSIONS" -le 14 ]; then
    IPS=$(who | awk '$1=="root"{print $5}' | tr -d '()' | paste -sd "," -)
    echo "2 $SERVICE - $SESSIONS root session(s) from $IPS"
else
    IPS=$(who | awk '$1=="root"{print $5}' | tr -d '()' | paste -sd "," -)
    echo "2 $SERVICE - $SESSIONS root session(s) from $IPS"
fi
