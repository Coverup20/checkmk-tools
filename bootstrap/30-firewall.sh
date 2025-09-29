#!/usr/bin/env bash
set -euo pipefail

if ! dpkg -s ufw >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ufw
fi

ufw --force reset || true
ufw default deny incoming
ufw default allow outgoing

SSH_P="${SSH_PORT:-22}"
ufw allow "${SSH_P}/tcp"

if [[ "${OPEN_HTTP_HTTPS:-false}" == "true" ]]; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

ufw --force enable
echo "UFW configurato."