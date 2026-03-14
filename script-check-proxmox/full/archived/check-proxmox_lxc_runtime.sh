#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=5

# Thresholds (percent)
CPU_WARN=85
CPU_CRIT=95
MEM_WARN=85
MEM_CRIT=95
DISK_WARN=85
DISK_CRIT=95

if ! command -v pvesh >/dev/null 2>&1; then
  echo "3 PVE_LXC_Runtime - pvesh not found"
  exit 0
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "3 PVE_LXC_Runtime - jq not found"
  exit 0
fi

NODE="$(hostname -s)"

# CTIDs on this node
ctids="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/lxc" --output-format json 2>/dev/null | jq -r '.[].vmid' || true)"
if [[ -z "${ctids:-}" ]]; then
  echo "1 PVE_LXC_Runtime_Summary - WARN - no CTs found via pvesh on node ${NODE}"
  exit 0
fi

running=0
total=0

sanitize() {
  echo "$1" | tr ' /' '__' | tr -cd 'A-Za-z0-9_.:-'
}

for ctid in $ctids; do
  total=$((total+1))

  json="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/lxc/${ctid}/status/current" --output-format json 2>/dev/null || true)"
  if [[ -z "${json:-}" ]]; then
    echo "2 PVE_LXC_${ctid}_Runtime - CRIT - cannot read status/current"
    continue
  fi

  name="$(echo "$json" | jq -r '.name // empty')"
  [[ -z "${name:-}" || "$name" == "null" ]] && name="ct${ctid}"
  safe_name="$(sanitize "$name")"
  svc="PVE_LXC_${ctid}_${safe_name}_Runtime"

  status="$(echo "$json" | jq -r '.status // "unknown"')"
  if [[ "$status" != "running" ]]; then
    echo "0 ${svc} - OK - status=${status}"
    continue
  fi
  running=$((running+1))

  cpu_frac="$(echo "$json" | jq -r '.cpu // 0')"          # 0..1
  mem="$(echo "$json" | jq -r '.mem // 0')"              # bytes
  maxmem="$(echo "$json" | jq -r '.maxmem // 0')"        # bytes
  swap="$(echo "$json" | jq -r '.swap // 0')"            # bytes
  maxswap="$(echo "$json" | jq -r '.maxswap // 0')"      # bytes
  disk="$(echo "$json" | jq -r '.disk // 0')"            # bytes
  maxdisk="$(echo "$json" | jq -r '.maxdisk // 0')"      # bytes
  uptime="$(echo "$json" | jq -r '.uptime // 0')"        # seconds

  cpu_pct="$(awk -v c="${cpu_frac}" 'BEGIN{printf "%.0f", c*100}')"

  mem_pct=0
  if [[ "${maxmem}" -gt 0 ]]; then
    mem_pct="$(awk -v m="${mem}" -v mm="${maxmem}" 'BEGIN{printf "%.0f", (m/mm)*100}')"
  fi

  swap_pct=0
  if [[ "${maxswap}" -gt 0 ]]; then
    swap_pct="$(awk -v s="${swap}" -v ms="${maxswap}" 'BEGIN{printf "%.0f", (s/ms)*100}')"
  fi

  disk_pct=0
  if [[ "${maxdisk}" -gt 0 ]]; then
    disk_pct="$(awk -v d="${disk}" -v md="${maxdisk}" 'BEGIN{printf "%.0f", (d/md)*100}')"
  fi

  state=0
  if (( cpu_pct >= CPU_CRIT )); then state=2
  elif (( cpu_pct >= CPU_WARN )) && (( state < 1 )); then state=1
  fi
  if (( mem_pct >= MEM_CRIT )); then state=2
  elif (( mem_pct >= MEM_WARN )) && (( state < 1 )); then state=1
  fi
  if (( disk_pct >= DISK_CRIT )); then state=2
  elif (( disk_pct >= DISK_WARN )) && (( state < 1 )); then state=1
  fi

  label="OK"
  if (( state == 1 )); then label="WARN"; fi
  if (( state == 2 )); then label="CRIT"; fi

  up_h="0.0"
  if [[ "${uptime}" -gt 0 ]]; then
    up_h="$(awk -v u="${uptime}" 'BEGIN{printf "%.1f", u/3600}')"
  fi

  # Perfdata:
  # - cpu/mem/disk in percent with thresholds and range
  # - swap_pct only as info (no thresholds), but plottable
  # - uptime_h as info
  echo "${state} ${svc} - ${label} - cpu ${cpu_pct}%, mem ${mem_pct}%, disk ${disk_pct}%, swap ${swap_pct}%, uptime ${up_h}h | cpu=${cpu_pct}%;${CPU_WARN};${CPU_CRIT};0;100 mem=${mem_pct}%;${MEM_WARN};${MEM_CRIT};0;100 disk=${disk_pct}%;${DISK_WARN};${DISK_CRIT};0;100 swap=${swap_pct};;;; uptime_h=${up_h};;;;"
done

echo "0 PVE_LXC_Runtime_Summary - OK - ${running}/${total} running on ${NODE} | running=${running};;;; total=${total};;;;"

exit 0
