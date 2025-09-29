#!/usr/bin/env bash
set -euo pipefail

# Timezone
if [[ -n "${TIMEZONE:-}" ]]; then
  timedatectl set-timezone "$TIMEZONE" || true
fi

# Install openssh-server if missing
if ! dpkg -s openssh-server >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y openssh-server
fi

mkdir -p /etc/ssh/sshd_config.d
DROPIN="/etc/ssh/sshd_config.d/99-bootstrap.conf"

cat > "$DROPIN" <<EOF
# Managed by bootstrap
Port ${SSH_PORT:-22}
LoginGraceTime ${LOGIN_GRACE_TIME:-30}
ClientAliveInterval ${CLIENT_ALIVE_INTERVAL:-600}
ClientAliveCountMax ${CLIENT_ALIVE_COUNTMAX:-2}
TCPKeepAlive yes
PermitRootLogin ${PERMIT_ROOT_LOGIN:-no}
PasswordAuthentication yes
EOF

# Change root password if provided
if [[ -n "${ROOT_PASSWORD:-}" ]]; then
  echo "root:${ROOT_PASSWORD}" | chpasswd
fi

systemctl enable --now ssh
systemctl restart ssh || true
echo "SSH configurato. Porta: ${SSH_PORT:-22}"
root@laboratorio:/mnt/data/backups/install-cmk/scripts# cat 15-ntp.sh
#!/usr/bin/env bash
set -euo pipefail

if dpkg -s chrony >/dev/null 2>&1; then
  echo "chrony installato: salto systemd-timesyncd."
  exit 0
fi
if dpkg -s ntp >/dev/null 2>&1; then
  echo "ntp installato: salto systemd-timesyncd."
  exit 0
fi

apt-get update -y
apt-get install -y systemd-timesyncd

mkdir -p /etc/systemd/timesyncd.conf.d
SERVERS="${NTP_SERVERS:-0.pool.ntp.org 1.pool.ntp.org 2.pool.ntp.org 3.pool.ntp.org}"
cat > /etc/systemd/timesyncd.conf.d/99-bootstrap.conf <<EOF
[Time]
NTP=${SERVERS}
FallbackNTP=ntp.ubuntu.com
EOF

systemctl enable systemd-timesyncd
systemctl restart systemd-timesyncd || true
timedatectl set-ntp true || true

echo "==> Stato timedatectl:"
timedatectl status || true