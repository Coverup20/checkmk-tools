#!/bin/bash
# check_dovecot_status.sh
SERVICE="NS7.Dovecot.Status"
if systemctl is-active --quiet dovecot; then
    echo "0 $SERVICE - Dovecot running"
else    
echo "2 $SERVICE - Dovecot not running"
fi 