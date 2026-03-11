#!/bin/bash
CLIENT_IP=$(echo $SSH_CONNECTION | awk '{print $1}')

# Metodo 1: client passa hostname come argomento SSH (es: ssh ... "checkmk-z1plus")
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
fi
