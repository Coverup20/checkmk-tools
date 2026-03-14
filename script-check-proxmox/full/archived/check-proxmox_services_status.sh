#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=5

if ! command -v systemctl >/dev/null 2>&1; then
  echo "3 PVE_Services - systemctl not found"
  exit 0
fi

services=(
  pvedaemon
  pveproxy
  pvestatd
  pve-cluster
  corosync
  pve-ha-lrm
  pve-ha-crm
)

for s in "${services[@]}"; do
  if ! systemctl list-unit-files --type=service 2>/dev/null | awk '{print $1}' | grep -qx "${s}.service"; then
    # Not installed on this node
    continue
  fi

  active="$(systemctl is-active "${s}.service" 2>/dev/null || echo unknown)"
  enabled="$(systemctl is-enabled "${s}.service" 2>/dev/null || echo unknown)"

  svc="PVE_Service_${s}"

  if [[ "$active" == "active" ]]; then
    echo "0 ${svc} enabled=${enabled} OK - active"
  elif [[ "$active" == "inactive" || "$active" == "failed" ]]; then
    echo "2 ${svc} enabled=${enabled} CRIT - ${active}"
  else
    echo "1 ${svc} enabled=${enabled} WARN - ${active}"
  fi
done

exit 0
