#!/bin/bash
# check_webtop_maxmemory.sh
SERVICE="NS7.WebTop.MaxMemory"
MAXMEM=$(config show webtop 2>/dev/null | grep -i 'MaxMemory' | awk -
F= '{print $2}')
if [ -z "$MAXMEM" ]; then
    echo "0 $SERVICE - MaxMemory unset"
else    
echo "0 $SERVICE - MaxMemory = ${MAXMEM}M"
fi 