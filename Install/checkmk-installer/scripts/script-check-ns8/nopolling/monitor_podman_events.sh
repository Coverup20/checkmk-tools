#!/bin/bash
# Demone che ascolta eventi Podman e registra solo create/start/stop/remove
# Esclude i container "redis"

LOGFILE="/var/log/podman_events.log"
mkdir -p "$(dirname "$LOGFILE")"

podman events --filter type=container --format "{{.Time}} {{.Status}} {{.Name}} ({{.ID}})" |
while read -r event; do
    # escludi redis
    if echo "$event" | grep -qi "redis"; then
        continue
    fi

    # prendi solo create/start/stop/remove
    if echo "$event" | grep -Eq " create | start | stop | remove "; then
        echo "$(date '+%F %T') - $event" >> "$LOGFILE"
    fi
done
1~#!/bin/bash
# Demone che ascolta eventi Podman e registra solo create/start/stop/remove
# Esclude i container "redis"

LOGFILE="/var/log/podman_events.log"
mkdir -p "$(dirname "$LOGFILE")"

podman events --filter type=container --format "{{.Time}} {{.Status}} {{.Name}} ({{.ID}})" |
while read -r event; do
    # escludi redis
    if echo "$event" | grep -qi "redis"; then
        continue
    fi

    # prendi solo create/start/stop/remove
    if echo "$event" | grep -Eq " create | start | stop | remove "; then
        echo "$(date '+%F %T') - $event" >> "$LOGFILE"
    fi
done
1~#!/bin/bash
# Demone che ascolta eventi Podman e registra solo create/start/stop/remove
# Esclude i container "redis"

LOGFILE="/var/log/podman_events.log"
mkdir -p "$(dirname "$LOGFILE")"

podman events --filter type=container --format "{{.Time}} {{.Status}} {{.Name}} ({{.ID}})" |
while read -r event; do
    # escludi redis
    if echo "$event" | grep -qi "redis"; then
        continue
    fi

    # prendi solo create/start/stop/remove
    if echo "$event" | grep -Eq " create | start | stop | remove "; then
        echo "$(date '+%F %T') - $event" >> "$LOGFILE"
    fi
done
