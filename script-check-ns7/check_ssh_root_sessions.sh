#!/bin/bash
# check_ssh_root_sessions.sh
# Genera notifica per ogni login e logout SSH root

SERVICE="SSH_root_sessions"
STATEFILE="/var/lib/check_mk_agent/ssh_root_sessions.state"

mkdir -p /var/lib/check_mk_agent

# elenco attuale IP root attivi
CURR_IPS=$(who | awk '$1=="root"{print $5}' | tr -d '()' | sort -u)
NOW=$(date +"%Y-%m-%d %H:%M:%S")

# elenco precedente dal file di stato
if [ -f "$STATEFILE" ]; then
    PREV_IPS=$(cat "$STATEFILE")
else
    PREV_IPS=""
fi

# salva lo stato attuale per la prossima volta
echo "$CURR_IPS" > "$STATEFILE"

# trova login nuovi
NEW_LOGINS=$(comm -13 <(echo "$PREV_IPS") <(echo "$CURR_IPS"))
# trova logout (IP che câ€™erano prima e non ci sono piÃ¹)
LOGOUTS=$(comm -23 <(echo "$PREV_IPS") <(echo "$CURR_IPS"))

if [ -n "$NEW_LOGINS" ]; then
    for ip in $NEW_LOGINS; do
        if [ $((RANDOM % 2)) -eq 0 ]; then
            echo "1 $SERVICE - $NOW root login from $ip"
        else
            echo "2 $SERVICE - $NOW root login from $ip"
        fi
    done
fi

if [ -n "$LOGOUTS" ]; then
    for ip in $LOGOUTS; do
        echo "0 $SERVICE - $NOW root logout from $ip"
    done
fi

# se nessun evento, mostra numero sessioni attuali
if [ -z "$NEW_LOGINS" ] && [ -z "$LOGOUTS" ]; then
    COUNT=$(echo "$CURR_IPS" | wc -w)
    echo "0 $SERVICE - $COUNT root session(s) active"
fi

