#!/bin/bash
# check_ns8_tomcat8.sh
# Local check per Checkmk: controlla Tomcat8 (memoria + uptime)

echo "<<<local>>>"

FOUND=0
WARN=1024   # soglia warning in MB
CRIT=1536   # soglia critical in MB

for INSTANCE in $(runagent -l | grep -vE '^(cluster|node)$'); do
    CONTAINERS=$(runagent -m "$INSTANCE" podman ps --format "{{.Names}}")

    for C in $CONTAINERS; do
        PID=$(runagent -m "$INSTANCE" podman exec "$C" pgrep -f "org.apache.catalina.startup.Bootstrap" 2>/dev/null | head -n1)

        if [[ -n "$PID" ]]; then
            FOUND=1
            # Memoria in MB
            MEM=$(runagent -m "$INSTANCE" podman exec "$C" ps -o rss= -p "$PID" | awk '{printf "%.0f", $1/1024}')
            # Uptime del processo
            UPTIME=$(runagent -m "$INSTANCE" podman exec "$C" ps -o etime= -p "$PID" | tr -d ' ')

            # Valutazione soglie
            if (( MEM >= CRIT )); then
                STATE=2
                MSG="Tomcat8 CRIT - Memoria=${MEM}MB (>${CRIT}MB); Uptime=${UPTIME}"
            elif (( MEM >= WARN )); then
                STATE=1
                MSG="Tomcat8 WARN - Memoria=${MEM}MB (>${WARN}MB); Uptime=${UPTIME}"
            else
                STATE=0
                MSG="Tomcat8 OK - Memoria=${MEM}MB; Uptime=${UPTIME}"
            fi

            echo "$STATE Tomcat8 - $MSG"
        fi
    done
done

if [[ $FOUND -eq 0 ]]; then
    echo "2 Tomcat8 - NON attivo"
fi
