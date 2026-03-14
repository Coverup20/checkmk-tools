#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=30

# Thresholds (percent)
CPU_WARN=85
CPU_CRIT=95
MEM_WARN=85
MEM_CRIT=95
DISK_WARN=85
DISK_CRIT=95

if ! command -v pvesh >/dev/null 2>&1; then
  echo "3 PVE_QEMU_Runtime - pvesh not found"
  exit 0
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "3 PVE_QEMU_Runtime - jq not found"
  exit 0
fi

NODE="$(hostname -s)"

sanitize() {
  echo "$1" | tr ' /' '__' | tr -cd 'A-Za-z0-9_.:-'
}

# Get all VMs at once
vm_list="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/qemu" --output-format json 2>/dev/null || true)"
if [[ -z "${vm_list:-}" || "$vm_list" == "[]" ]]; then
  echo "1 PVE_QEMU_Runtime_Summary - WARN - no VMs found via pvesh on node ${NODE}"
  exit 0
fi

running=0
total=0

# Process each VM from the list
echo "$vm_list" | jq -c '.[]' 2>/dev/null | while IFS= read -r vm_basic; do
  vmid="$(echo "$vm_basic" | jq -r '.vmid // empty')"
  [[ -z "$vmid" ]] && continue
  
  total=$((total+1))
  
  name="$(echo "$vm_basic" | jq -r '.name // empty')"
  status="$(echo "$vm_basic" | jq -r '.status // "unknown"')"  
  
  # Skip if not running
  if [[ "$status" != "running" ]]; then
    [[ -z "${name:-}" || "$name" == "null" ]] && name="vm${vmid}"
    safe_name="$(sanitize "$name")"
    echo "0 PVE_QEMU_${vmid}_${safe_name}_Runtime - OK - status=${status}"
    continue
  fi
  running=$((running+1))
  
  # Get detailed status only for running VMs
  json="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/qemu/${vmid}/status/current" --output-format json 2>/dev/null || true)"
  if [[ -z "${json:-}" ]]; then
    echo "2 PVE_QEMU_${vmid}_Runtime - CRIT - cannot read status/current"
    continue
  fi

  name="$(echo "$json" | jq -r '.name // empty')"
  [[ -z "${name:-}" || "$name" == "null" ]] && name="vm${vmid}"
  safe_name="$(sanitize "$name")"
  svc="PVE_QEMU_${vmid}_${safe_name}_Runtime"

  status="$(echo "$json" | jq -r '.status // "unknown"')"
  if [[ "$status" != "running" ]]; then
    echo "0 ${svc} - OK - status=${status}"
    continue
  fi
  running=$((running+1))

  cpu_frac="$(echo "$json" | jq -r '.cpu // 0')"
  mem="$(echo "$json" | jq -r '.mem // 0')"
  maxmem="$(echo "$json" | jq -r '.maxmem // 0')"
  disk="$(echo "$json" | jq -r '.disk // 0')"
  maxdisk="$(echo "$json" | jq -r '.maxdisk // 0')"
  uptime="$(echo "$json" | jq -r '.uptime // 0')"

  cpu_pct="$(awk -v c="${cpu_frac}" 'BEGIN{printf "%.0f", c*100}')"

  mem_pct=0
  if [[ "${maxmem}" -gt 0 ]]; then
    mem_pct="$(awk -v m="${mem}" -v mm="${maxmem}" 'BEGIN{printf "%.0f", (m/mm)*100}')"
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

  echo "${state} ${svc} - ${label} - cpu ${cpu_pct}%, mem ${mem_pct}%, disk ${disk_pct}%, uptime ${up_h}h | cpu=${cpu_pct}%;${CPU_WARN};${CPU_CRIT};0;100 mem=${mem_pct}%;${MEM_WARN};${MEM_CRIT};0;100 disk=${disk_pct}%;${DISK_WARN};${DISK_CRIT};0;100 uptime_h=${up_h};;;;"
done

echo "0 PVE_QEMU_Runtime_Summary - OK - ${running}/${total} running on ${NODE} | running=${running};;;; total=${total};;;;"

exit 0
