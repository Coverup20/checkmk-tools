#!/bin/bash
# check_dovecot_vsz.sh

SERVICE="Dovecot_vsz_limit"

# Estrae il valore da config
RAW_VSZ=$(config show dovecot 2>/dev/null | grep -i 'VszLimit' | awk '{print $2}')

if [ -z "$RAW_VSZ" ]; then
    echo "0 $SERVICE - VSZ limit unset"
else
    echo "0 $SERVICE - VSZ limit = $RAW_VSZ"
fi

