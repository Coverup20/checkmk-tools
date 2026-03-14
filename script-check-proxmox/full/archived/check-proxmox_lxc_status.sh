#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=5

if ! command -v pct >/dev/null 2>&1; then
  echo "3 PVE_LXC - pct command not found"
  exit 0
fi

total="$(timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1{c++} END{print c+0}')"
running="$(timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1 && $2=="running"{c++} END{print c+0}')"
echo "0 PVE_LXC_Summary running=${running} total=${total} OK - ${running}/${total} running"

timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1{print $1}' | while read -r ctid; do
  name="$(timeout "${PVE_TIMEOUT}" pct config "$ctid" 2>/dev/null | awk -F': ' '/^hostname: /{print $2; exit}')"
  [[ -z "${name:-}" ]] && name="ct${ctid}"
  status="$(timeout "${PVE_TIMEOUT}" pct status "$ctid" 2>/dev/null | awk '{print $2}')"

  svc="PVE_LXC_${ctid}_$(echo "$name" | tr ' /' '__' | tr -cd 'A-Za-z0-9_.:-')"

  if [[ "$status" == "running" ]]; then
    echo "0 ${svc} - OK - running"
  elif [[ "$status" == "stopped" ]]; then
    echo "1 ${svc} - WARN - stopped"
  else
    echo "2 ${svc} - CRIT - status ${status:-unknown}"
  fi
done

exit 0
