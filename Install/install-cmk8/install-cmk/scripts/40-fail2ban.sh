#!/usr/bin/env bash
set -euo pipefail

if ! dpkg -s fail2ban >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y fail2ban
fi

mkdir -p /etc/fail2ban/jail.d
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
bantime = 1h
EOF

systemctl enable --now fail2ban
systemctl restart fail2ban || true
echo "Fail2Ban configurato."
