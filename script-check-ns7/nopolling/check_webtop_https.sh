#!/bin/bash
# check_webtop_https.sh

SERVICE="WebTop_https"
URL="https://$(hostname -f)/webtop/"

HTTP_CODE=$(curl -L -s -k -o /dev/null -w "%{http_code}" --max-time 5 "$URL")

if [ "$HTTP_CODE" = "200" ]; then
    echo "0 $SERVICE - WebTop reachable"
elif [ "$HTTP_CODE" = "000" ]; then
    echo "2 $SERVICE - WebTop not reachable"
else
    echo "2 $SERVICE - WebTop not reachable (code $HTTP_CODE)"
fi

