#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=5

if ! command -v pvesm >/dev/null 2>&1; then
  echo "3 PVE_Storage - pvesm command not found"
  exit 0
fi

# Thresholds
WARN=80
CRIT=90

# pvesm status output: Name Type Status Total(KiB) Used(KiB) Avail(KiB) %
timeout "${PVE_TIMEOUT}" pvesm status 2>/dev/null | awk 'NR>1' | while read -r name type status total used avail pct; do
  # pct like "37.17%"
  p="${pct%\%}"
  p_int="$(awk -v x="$p" 'BEGIN{printf "%.0f", x}')"

  if [[ "$status" != "active" ]]; then
    echo "2 PVE_Storage_${name} used=${p_int}%;${WARN};${CRIT} CRIT - ${status}"
    continue
  fi

  state=0
  if (( p_int >= CRIT )); then state=2
  elif (( p_int >= WARN )); then state=1
  fi

  echo "${state} PVE_Storage_${name} used=${p_int}%;${WARN};${CRIT} OK - used ${p_int}%"
done

exit 0
