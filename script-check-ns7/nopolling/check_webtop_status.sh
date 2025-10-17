#!/bin/bash
# check_webtop_status.sh

SERVICE="WebTop_status"

if systemctl is-active --quiet tomcat8@webtop; then
    echo "0 $SERVICE - WebTop running"
else
    echo "2 $SERVICE - WebTop not running"
fi

