#!/usr/bin/env bash
[ -z "$BASH_VERSION" ] && exec /bin/bash "$0" "$@"

# check-sosid-ns7.sh - versione pulita e verificata, una sola riga per Checkmk
# Evita qualunque carattere o virgolette non bilanciata.

set -uo pipefail

YUM_LOG="/var/log/yum.log"
STATE_FILE="/var/lib/check_pkg_install/last_event"
WARN_TIMEOUT_MINUTES=5

if [[ ! -r "$YUM_LOG" ]]; then
    echo "2 PKG_INSTALL - CRITICAL: $YUM_LOG non leggibile"
    exit 2
fi

mkdir -p /var/lib/check_pkg_install >/dev/null 2>&1 || true

event_line=$(grep -E 'Installed:|Updated:|Erased:|Removed:' "$YUM_LOG" | tail -n 1)
if [[ -z "$event_line" ]]; then
    echo "0 PKG_INSTALL - OK: nessuna attività pacchetti"
    exit 0
fi

event_date=$(echo "$event_line" | awk '{print $1, $2, $3}')
current_ts=$(date +%s)
# tenta con e senza anno
if ! event_ts=$(date -d "$event_date" +%s 2>/dev/null); then
    event_ts=$(date -d "$(date +%Y) $event_date" +%s 2>/dev/null || echo 0)
fi

[[ -z "$event_ts" ]] && event_ts=0

last_saved=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
if [[ "$event_ts" -gt "$last_saved" ]]; then
    echo "$event_ts" > "$STATE_FILE"
fi

last_event_ts=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
elapsed_min=$(( (current_ts - last_event_ts) / 60 ))

recent_entry=$(echo "$event_line" | sed -E 's/^[A-Z][a-z]{2} +[0-9]+ +[0-9:]{2}:[0-9:]{2} +//' | sed -E 's/^.*(Installed:|Updated:|Erased:|Removed:)/\1/' | tr -d '\n')

if [[ "$elapsed_min" -lt "$WARN_TIMEOUT_MINUTES" ]]; then
    echo "1 PKG_INSTALL - WARN: attività recente ($event_date): $recent_entry"
else
    echo "0 PKG_INSTALL - OK: nessuna nuova attività nelle ultime $WARN_TIMEOUT_MINUTES min (Ultima: $event_date)"
fi

exit 0