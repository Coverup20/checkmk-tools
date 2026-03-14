#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=30

if ! command -v pvesh >/dev/null 2>&1; then
  echo "3 PVE_QGA_Summary - pvesh not found"
  exit 0
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "3 PVE_QGA_Summary - jq not found"
  exit 0
fi

NODE="$(hostname -s)"

sanitize() {
  echo "$1" | tr ' /' '__' | tr -cd 'A-Za-z0-9_.:-'
}

# Get all VMs with status in one call (includes vmid, name, status)
vm_list="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/qemu" --output-format json 2>/dev/null || true)"
if [[ -z "${vm_list:-}" || "$vm_list" == "[]" ]]; then
  echo "1 PVE_QGA_Summary - WARN - no VMs found on ${NODE}"
  exit 0
fi

total=0
running=0
qga_ok=0
qga_missing=0
qga_error=0
qga_skipped=0

# Process each VM
echo "$vm_list" | jq -c '.[]' 2>/dev/null | while IFS= read -r vm; do
  vmid="$(echo "$vm" | jq -r '.vmid // empty')"
  [[ -z "$vmid" ]] && continue
  
  total=$((total+1))
  
  name="$(echo "$vm" | jq -r '.name // empty')"
  [[ -z "${name:-}" || "$name" == "null" ]] && name="vm${vmid}"
  safe_name="$(sanitize "$name")"
  svc="PVE_QGA_${vmid}_${safe_name}"

  status="$(echo "$vm" | jq -r '.status // "unknown"')"
  if [[ "$status" != "running" ]]; then
    # Stopped VM: we do not enforce QGA
    echo "0 ${svc} - OK - VM status=${status} (QGA check skipped)"
    qga_skipped=$((qga_skipped+1))
    continue
  fi
  running=$((running+1))

  # Check whether agent is enabled in config
  cfg="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/qemu/${vmid}/config" --output-format json 2>/dev/null || true)"
  agent_cfg="$(echo "$cfg" | jq -r '.agent // empty' 2>/dev/null || true)"

  # If config explicitly disables it (agent 0)
  if [[ "${agent_cfg:-}" == "0" ]]; then
    echo "1 ${svc} - WARN - QEMU Guest Agent disabled in VM config (agent=0)"
    qga_missing=$((qga_missing+1))
    continue
  fi

  # Query QGA ping (best simple probe)
  # Endpoint exists only if QGA responds; otherwise it returns an error.
  probe="$(timeout "${PVE_TIMEOUT}" pvesh get "/nodes/${NODE}/qemu/${vmid}/agent/ping" --output-format json 2>/dev/null || true)"

  if [[ -n "${probe:-}" ]]; then
    echo "0 ${svc} - OK - QEMU Guest Agent responding"
    qga_ok=$((qga_ok+1))
  else
    # Most common: QGA not installed/started inside guest, or virtio serial not present
    echo "2 ${svc} - CRIT - QEMU Guest Agent not responding (install/start qemu-guest-agent in guest OS)"
    qga_error=$((qga_error+1))
  fi
done

# Summary service with perfdata
# Note: qga_skipped counts non-running VMs.
echo "0 PVE_QGA_Summary - OK - total=${total}, running=${running}, ok=${qga_ok}, missing/disabled=${qga_missing}, error=${qga_error}, skipped=${qga_skipped} | total=${total};;;; running=${running};;;; ok=${qga_ok};;;; missing=${qga_missing};;;; error=${qga_error};;;; skipped=${qga_skipped};;;;"

exit 0
