#!/usr/bin/env bash
set -euo pipefail

apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y   curl vim git htop net-tools unzip python3-venv unattended-upgrades ca-certificates   software-properties-common

systemctl enable --now unattended-upgrades || true
echo "Pacchetti base installati."