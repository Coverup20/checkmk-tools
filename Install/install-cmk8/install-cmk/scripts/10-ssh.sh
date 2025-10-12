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
