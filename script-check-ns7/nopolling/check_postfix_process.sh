#!/bin/bash
# check_postfix_processes.sh

SERVICE="Postfix_processes"

PROCS=$(pgrep -c -f "postfix")

if [ "$PROCS" -gt 0 ]; then
    echo "0 $SERVICE - $PROCS Postfix process(es) running"
else
    echo "2 $SERVICE - No Postfix processes found"
fi

