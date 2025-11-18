#!/bin/bash
# Script base di monitoraggio spazio disco
# Uso: bash check_disk_space.sh

THRESHOLD=80 # percentuale di soglia

USAGE=$(df / | tail -1 | awk '{print $5}' | sed 's/%//')

if [ "$USAGE" -lt "$THRESHOLD" ]; then
    echo "OK - Spazio disco utilizzato: $USAGE%"
    exit 0
elif [ "$USAGE" -lt 95 ]; then
    echo "WARNING - Spazio disco utilizzato: $USAGE%"
    exit 1
else
    echo "CRITICAL - Spazio disco utilizzato: $USAGE%"
    exit 2
fi
