#!/bin/bash
# check_cockpit_sessions.sh
# Notifica login/logout Cockpit leggendo /var/log/messages
# e mostra quante sessioni sono attive

SERVICE="Cockpit_sessions"
STATEFILE="/var/lib/check_mk_agent/cockpit_sessions.state"
LOGFILE="/var/log/messages"
NOW=$(date +"%Y-%m-%d %H:%M:%S")

mkdir -p /var/lib/check_mk_agent

# ultima riga processata
LAST_LINE=0
[ -f "$STATEFILE" ] && LAST_LINE=$(cat "$STATEFILE")

# nuove righe cockpit
NEW_LINES=$(awk -v last="$LAST_LINE" 'NR>last && /cockpit-ws:/ {print NR " " $0}' "$LOGFILE")

# aggiorna puntatore
if [ -n "$NEW_LINES" ]; then
    NEW_LAST=$(echo "$NEW_LINES" | tail -n1 | awk '{print $1}')
    echo "$NEW_LAST" > "$STATEFILE"

    while read -r _nr line; do
        if [[ "$line" =~ "New connection to session from" ]]; then
            ip=$(echo "$line" | sed -n 's/.*from \([0-9\.]\+\).*/\1/p')
            if [ -n "$ip" ]; then
                # alterna WARN/CRIT per forzare notifica ad ogni login
                if [ $(("$RANDOM" % 2)) -eq 0 ]; then
                    echo "1 $SERVICE - $NOW cockpit login from $ip"
                else
                    echo "2 $SERVICE - $NOW cockpit login from $ip"
                fi
            fi
        elif [[ "$line" =~ "for session closed" ]]; then
            ip=$(echo "$line" | sed -n 's/.*from \([0-9\.]\+\).*/\1/p')
            [ -n "$ip" ] && echo "0 $SERVICE - $NOW cockpit logout from $ip"
        fi
    done <<< "$NEW_LINES"
else
    # info di stato (non notifica perché rimane 0)
    ACTIVE=$(ss -tnp 2>/dev/null | grep -c cockpit-ws)
    echo "0 $SERVICE - $ACTIVE cockpit session(s) active"
fi

