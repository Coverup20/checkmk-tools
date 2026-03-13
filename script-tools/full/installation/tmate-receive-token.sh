#!/bin/bash
# tmate-receive-token.sh
# Forced command su server vps-02: riceve token tmate dai client via SSH
#
# Chiamato da: authorized_keys con command="/opt/tmate-receive-token.sh"
# Stdin: token tmate (es: "ssh -p10022 AbCdEf@monitor01.nethlab.it")
# SSH_ORIGINAL_COMMAND: hostname del client (es: "checkmk-z1plus")
# SSH_CONNECTION: IP del client in campo 1
#
# Funzionalita':
#   1. Salva token in /opt/tmate-tokens/<nodename>.txt
#   2. Cleanup automatico: rimuove file con nome IP stale se nodename diverso dall'IP

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

  # Cleanup: rimuovi file stale con nome IP se il nodename e' diverso dall'IP
  # (succede quando client configurato vecchio stile senza passaggio hostname)
  if [ "$NODENAME" != "$CLIENT_IP" ] && [ -f "/opt/tmate-tokens/${CLIENT_IP}.txt" ]; then
    rm -f "/opt/tmate-tokens/${CLIENT_IP}.txt"
    logger -t tmate-receiver "Rimosso file stale ${CLIENT_IP}.txt (sostituito da ${NODENAME}.txt)"
  fi
fi
