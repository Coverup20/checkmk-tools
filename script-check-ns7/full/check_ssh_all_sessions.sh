#!/bin/bash

# check_ssh_all_sessions.sh

# Conta tutte le sessioni SSH attive (tutti gli utenti)


SERVICE="NS7.SSH.AllSessions"


# Conta tutte le sessioni SSH attive

SESSIONS=$(who | wc -l)

if [ "$SESSIONS" -gt 0 ]; then
    USERS=$(who | awk '{print $1}' | sort -u | paste -sd "," -)
    
echo "0 $SERVICE - $SESSIONS SSH session(s) active: $USERS"
else     
echo "0 $SERVICE - no SSH sessions"
fi
