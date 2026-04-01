#!/bin/bash
# tmate-receive-token.sh
# Forced command on vps-02 server: receives tmate tokens from clients via SSH
#
# Called from: authorized_keys with command="/opt/tmate-receive-token.sh"
# Stdin: tmate token (e.g. "ssh -p10022 AbCdEf@monitor01.nethlab.it")
# SSH_ORIGINAL_COMMAND: client hostname (e.g. "checkmk-z1plus")
# SSH_CONNECTION: Client IP in field 1
#
# Funzionalita':
# 1. Save tokens in /opt/tmate-tokens/<nodename>.txt
# 2. Automatic cleanup: remove files with stale IP name if nodename different from IP

CLIENT_IP=$(echo $SSH_CONNECTION | awk '{print $1}')

# Method 1: Client passes hostname as SSH argument (ex: ssh ... "checkmk-z1plus")
NODENAME=$(echo "$SSH_ORIGINAL_COMMAND" | tr -cd 'a-zA-Z0-9._-')

# Metodo 2: fallback journal lookup (1000 righe)
if [ -z "$NODENAME" ]; then
    NODENAME=$(journalctl -u tmate-ssh-server -n 1000 --no-pager 2>/dev/null \
      | grep "ip=${CLIENT_IP}" | grep 'nodename=' \
      | tail -1 | grep -oP 'nodename=\K\S+')
fi

# Metodo 3: fallback IP
[ -z "$NODENAME" ] && NODENAME="$CLIENT_IP"

read TOKEN
if [ -n "$TOKEN" ]; then
  echo "$TOKEN" > "/opt/tmate-tokens/${NODENAME}.txt"
  chmod 644 "/opt/tmate-tokens/${NODENAME}.txt"
  logger -t tmate-receiver "Token salvato per ${NODENAME} (ip=${CLIENT_IP})"

  # Cleanup: remove stale file with IP name if nodename is different from IP
  # (happens when client configured old style without hostname passing)
  if [ "$NODENAME" != "$CLIENT_IP" ] && [ -f "/opt/tmate-tokens/${CLIENT_IP}.txt" ]; then
    rm -f "/opt/tmate-tokens/${CLIENT_IP}.txt"
    logger -t tmate-receiver "Rimosso file stale ${CLIENT_IP}.txt (sostituito da ${NODENAME}.txt)"
  fi
fi
