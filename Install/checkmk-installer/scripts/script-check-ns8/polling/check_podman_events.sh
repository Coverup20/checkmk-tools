#!/bin/bash
# Local check per Checkmk: Podman_Status
# Mostra ultimo evento (Nome + Azione) oppure "Nessun Evento"
# Esclude i container "redis"

LOGFILE="/var/log/podman_events.log"
RECENT=$(date -d "5 minutes ago" +"%F %T")

SVC="Podman_Status"

if [ -f "$LOGFILE" ]; then
    NEW_EVENTS=$(awk -v ts="$RECENT" '$0 > ts' "$LOGFILE" | grep -vi "redis")
    FILTERED_EVENTS=$(echo "$NEW_EVENTS" | grep -E " create | start | stop | remove ")

    if [ -n "$FILTERED_EVENTS" ]; then
        LAST_EVENT=$(echo "$FILTERED_EVENTS" | tail -n 1)
        ACTION=$(echo "$LAST_EVENT" | awk '{print $5}')
        NAME=$(echo "$LAST_EVENT" | awk '{print $6}')

        # WARNING: mostra solo Nome + Azione
        echo "1 ${SVC} - ${NAME^} ${ACTION^}"
    else
        echo "0 ${SVC} - Nessun Evento"
    fi
else
    echo "0 ${SVC} - Nessun Evento"
fi
