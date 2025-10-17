#!/bin/bash
# check_postfix_queue.sh - Local check per Postfix queue

QUEUE=$(mailq 2>/dev/null | grep -c '^[A-F0-9]')
if [ -z "$QUEUE" ]; then
    echo "3 Postfix_queue - Unable to read postfix queue"
    exit 0
fi

if [ "$QUEUE" -lt 20 ]; then
    echo "0 Postfix_queue - Mail queue OK: $QUEUE messages"
elif [ "$QUEUE" -lt 100 ]; then
    echo "1 Postfix_queue - Mail queue WARNING: $QUEUE messages"
else
    echo "2 Postfix_queue - Mail queue CRITICAL: $QUEUE messages"
fi
