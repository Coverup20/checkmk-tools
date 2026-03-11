#!/bin/bash
set -e

# Setup token receiver su vps-02 (tmate server)
mkdir -p /opt/tmate-tokens

# Rigenera chiave senza passphrase
rm -f /opt/tmate-tokens/receiver_key /opt/tmate-tokens/receiver_key.pub
ssh-keygen -t ed25519 -f /opt/tmate-tokens/receiver_key -C tmate-token-receiver -N '' -q
chmod 600 /opt/tmate-tokens/receiver_key

# Crea script receiver (chiamato via SSH forced command)
cat > /opt/tmate-receive-token.sh << 'RECEIVER_EOF'
#!/bin/bash
# Riceve token dal client via SSH e lo salva in /opt/tmate-tokens/<hostname>.txt
CLIENT_IP=$(echo $SSH_CONNECTION | awk '{print $1}')
# Cerca hostname nei log di tmate-ssh-server
NODENAME=$(journalctl -u tmate-ssh-server -n 300 --no-pager 2>/dev/null \
  | grep "ip=${CLIENT_IP}" | grep 'nodename=' \
  | tail -1 | grep -oP 'nodename=\K\S+')
[ -z "$NODENAME" ] && NODENAME="$CLIENT_IP"
read TOKEN
if [ -n "$TOKEN" ]; then
  echo "$TOKEN" > "/opt/tmate-tokens/${NODENAME}.txt"
  chmod 644 "/opt/tmate-tokens/${NODENAME}.txt"
fi
RECEIVER_EOF
chmod +x /opt/tmate-receive-token.sh

# Autorizza la chiave in authorized_keys con forced command
PUBKEY=$(cat /opt/tmate-tokens/receiver_key.pub)
AUTHKEYS='/root/.ssh/authorized_keys'
grep -v 'tmate-token-receiver' "$AUTHKEYS" > /tmp/ak_tmp 2>/dev/null && mv /tmp/ak_tmp "$AUTHKEYS" || true
echo "command=\"/opt/tmate-receive-token.sh\",no-pty,no-X11-forwarding,no-agent-forwarding,no-port-forwarding $PUBKEY" >> "$AUTHKEYS"

echo "=== Setup receiver OK ==="
echo "Chiave privata da distribuire ai client:"
echo "--- INIZIO CHIAVE ---"
cat /opt/tmate-tokens/receiver_key
echo "--- FINE CHIAVE ---"
echo "Pubkey: $PUBKEY"
