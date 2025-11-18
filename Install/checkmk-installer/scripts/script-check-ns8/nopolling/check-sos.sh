#!/bin/bash
# check-sos - Local check per Checkmk
# Verifica sessione SOS leggendo /var/log/messages

LOGFILE="/var/log/messages"
STATUS="INACTIVE"
SESSION_ID="N/A"
STATE=0   # 0=OK, 1=WARN

# ultima riga di start
START_LINE=$(grep "start-support-session" "$LOGFILE" | tail -n 1)
# ultima riga di stop
STOP_LINE=$(grep "stop-support-session" "$LOGFILE" | tail -n 1)
# ultima riga con ID
ID_LINE=$(grep "Transmit the following session ID" "$LOGFILE" | tail -n 1)

if [ -n "$ID_LINE" ]; then
    SESSION_ID=$(echo "$ID_LINE" | awk '{print $NF}')
fi

if [ -n "$START_LINE" ]; then
    if [ -z "$STOP_LINE" ]; then
        STATUS="ACTIVE"
        STATE=1
    else
        START_DATE=$(echo "$START_LINE" | awk '{print $1" "$2" "$3}')
        STOP_DATE=$(echo "$STOP_LINE" | awk '{print $1" "$2" "$3}')
        START_EPOCH=$(date -d "$START_DATE" +%s)
        STOP_EPOCH=$(date -d "$STOP_DATE" +%s)
        if [ "$START_EPOCH" -gt "$STOP_EPOCH" ]; then
            STATUS="ACTIVE"
            STATE=1
        fi
    fi
fi

echo "$STATE SOS_session - SOS Session: $STATUS (ID: $SESSION_ID)"

