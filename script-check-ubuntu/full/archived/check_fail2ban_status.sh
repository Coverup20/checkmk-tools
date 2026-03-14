#!/bin/bash

# check_fail2ban_status.sh

# Controlla lo stato di fail2ban


SERVICE="Fail2ban"


# Verifica se fail2ban ├¿ installato
if ! command -v fail2ban-client &> /dev/null; then
    echo "3 $SERVICE - fail2ban not installed"
    exit 0
fi


# Verifica se fail2ban ├¿ in esecuzione
if ! systemctl is-active --quiet fail2ban 2>/dev/null && ! service fail2ban status &>/dev/null; then
    echo "2 $SERVICE - fail2ban service is not running"
    exit 0
fi


# Conta le jail attive e gli IP bannati

JAILS=$(fail2ban-client status 2>/dev/null | grep "Jail list" | sed 's/.*://;s/,//g')

TOTAL_BANNED=0

if [ -n "$JAILS" ]; then
    for jail in $JAILS; do
        
BANNED=$(fail2ban-client status "$jail" 2>/dev/null | grep "Currently banned" | awk '{print $NF}')
        
TOTAL_BANNED=$((TOTAL_BANNED + BANNED))
    done
    
    if [ "$TOTAL_BANNED" -gt 0 ]; then
    echo "1 $SERVICE - running, $TOTAL_BANNED IP(s) banned"
else         
echo "0 $SERVICE - running, no banned IPs"
    fi
else     
echo "0 $SERVICE - running, no jails configured"
fi
