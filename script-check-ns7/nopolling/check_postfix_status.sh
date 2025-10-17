#!/bin/bash
# check_postfix_status.sh

SERVICE="Postfix_status"

if systemctl is-active --quiet postfix; then
    echo "0 $SERVICE - Postfix running"
else
    echo "2 $SERVICE - Postfix not running"
fi

