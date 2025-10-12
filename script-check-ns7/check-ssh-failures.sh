#!/bin/bash
#
# check-ssh-failures.sh
# Local check per Checkmk su NethServer 7.9
# Conta gli IP attualmente bannati da fail2ban per SSH
#

JAIL_INFO=$(fail2ban-client status sshd 2>/dev/null)

if [ $? -ne 0 ] || [ -z "$JAIL_INFO" ]; then
    echo "0 SSH-Failures - Fail2ban non attivo o jail sshd non trovato"
    exit 0
fi

BANNED=$(echo "$JAIL_INFO" | grep 'Currently banned:' | awk '{print $4}')

if [ -z "$BANNED" ]; then
    BANNED=0
fi

if [ "$BANNED" -gt 0 ]; then
    echo "1 SSH-Failures - SSH failed logins blocked (banned IPs) = $BANNED"
else
    echo "0 SSH-Failures - No SSH failed logins currently blocked"
fi
