#!/bin/bash
# Test ydea_la - WARN state (should NOT create ticket)
cd /omd/sites/monitoring/local/share/check_mk/notifications/
DEBUG_YDEA=1 \
NOTIFY_WHAT=SERVICE \
NOTIFY_HOSTNAME=test-noticket-xyz \
NOTIFY_SERVICEDESC=TestSvc \
NOTIFY_SERVICESHORTSTATE=WARN \
NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE=OK \
NOTIFY_SERVICEOUTPUT=test-warning \
NOTIFY_NOTIFICATIONTYPE=PROBLEM \
python3 ydea_la 2>&1
echo "EXIT: $?"
