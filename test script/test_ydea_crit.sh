#!/bin/bash
# Test ydea_la - CRITICAL state (should create ticket attempt)
cd /omd/sites/monitoring/local/share/check_mk/notifications/
DEBUG_YDEA=1 \
NOTIFY_WHAT=SERVICE \
NOTIFY_HOSTNAME=test-noticket-xyz \
NOTIFY_SERVICEDESC=TestSvc \
NOTIFY_SERVICESHORTSTATE=CRIT \
NOTIFY_PREVIOUSSERVICEHARDSHORTSTATE=OK \
NOTIFY_SERVICEOUTPUT=test-critical \
NOTIFY_NOTIFICATIONTYPE=PROBLEM \
python3 ydea_la 2>&1
echo "EXIT: $?"
