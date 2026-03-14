#!/usr/bin/env bash
set -euo pipefail

PVE_TIMEOUT=30

WARN_DAYS=14
CRIT_DAYS=30

now_epoch="$(date +%s)"

sanitize() {
  echo "$1" | tr ' /' '__' | tr -cd 'A-Za-z0-9_.:-'
}

# --- QEMU snapshots ---
if command -v qm >/dev/null 2>&1; then
  vm_total="$(timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1{c++} END{print c+0}')"
  snaps_total=0
  
  while read -r vmid; do
    snap_count="$(timeout "${PVE_TIMEOUT}" qm listsnapshot "$vmid" 2>/dev/null | awk 'NR>1 && NF>0{c++} END{print c+0}')"
    snaps_total=$((snaps_total + snap_count))
  done < <(timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1{print $1}')
  
  echo "0 PVE_QEMU_Snapshots_Summary vms=${vm_total} snapshots=${snaps_total} OK - ${snaps_total} snapshots across ${vm_total} VMs"

  timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1{print $1}' | while read -r vmid; do
    name="$(timeout "${PVE_TIMEOUT}" qm config "$vmid" 2>/dev/null | awk -F': ' '/^name: /{print $2; exit}')"
    [[ -z "${name:-}" ]] && name="vm${vmid}"
    svc_base="PVE_QEMU_Snapshots_${vmid}_$(sanitize "$name")"

    snap_count="$(timeout "${PVE_TIMEOUT}" qm listsnapshot "$vmid" 2>/dev/null | awk 'NR>1 && NF>0{c++} END{print c+0}')"
    [[ -z "${snap_count:-}" ]] && snap_count=0

    if [[ "$snap_count" -eq 0 ]]; then
      echo "2 ${svc_base}_Count count=0 CRIT - 0 snapshots"
      continue
    elif [[ "$snap_count" -eq 1 ]]; then
      echo "1 ${svc_base}_Count count=1 WARN - 1 snapshot"
    else
      echo "0 ${svc_base}_Count count=${snap_count} OK - ${snap_count} snapshots"
    fi

    conf="/etc/pve/qemu-server/${vmid}.conf"
    if [[ -r "$conf" ]]; then
      snaptime_min="$(awk '/^snaptime: /{print $2}' "$conf" 2>/dev/null | sort -n | head -n 1 || true)"
      
      if [[ -n "${snaptime_min:-}" && "$snaptime_min" =~ ^[0-9]+$ ]]; then
        age_sec=$(( now_epoch - snaptime_min ))
        age_days=$(( age_sec / 86400 ))
        st=0
        if (( age_days >= CRIT_DAYS )); then st=2
        elif (( age_days >= WARN_DAYS )); then st=1
        fi
        echo "${st} ${svc_base}_OldestAge age_days=${age_days};${WARN_DAYS};${CRIT_DAYS} - oldest snapshot ${age_days} days"
      fi
    fi
  done
fi

# --- LXC snapshots ---
if command -v pct >/dev/null 2>&1; then
  ct_total="$(timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1{c++} END{print c+0}')"
  snaps_total=0
  
  while read -r ctid; do
    snap_count="$(timeout "${PVE_TIMEOUT}" pct listsnapshot "$ctid" 2>/dev/null | awk 'NR>1 && NF>0{c++} END{print c+0}')"
    snaps_total=$((snaps_total + snap_count))
  done < <(timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1{print $1}')
  
  echo "0 PVE_LXC_Snapshots_Summary cts=${ct_total} snapshots=${snaps_total} OK - ${snaps_total} snapshots across ${ct_total} CTs"

  timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1{print $1}' | while read -r ctid; do
    name="$(timeout "${PVE_TIMEOUT}" pct config "$ctid" 2>/dev/null | awk -F': ' '/^hostname: /{print $2; exit}')"
    [[ -z "${name:-}" ]] && name="ct${ctid}"
    svc_base="PVE_LXC_Snapshots_${ctid}_$(sanitize "$name")"

    snap_count="$(timeout "${PVE_TIMEOUT}" pct listsnapshot "$ctid" 2>/dev/null | awk 'NR>1 && NF>0{c++} END{print c+0}')"
    if [[ "$snap_count" -eq 0 ]]; then
      echo "2 ${svc_base}_Count count=0 CRIT - 0 snapshots"
    elif [[ "$snap_count" -eq 1 ]]; then
      echo "1 ${svc_base}_Count count=1 WARN - 1 snapshot"
    else
      echo "0 ${svc_base}_Count count=${snap_count} OK - ${snap_count} snapshots"
    fi
  done
fi

exit 0