#!/usr/bin/env bash
set -u

PVE_TIMEOUT=8

if ! command -v qm >/dev/null 2>&1; then
  echo "3 PVE_QEMU - qm command not found"
  exit 0
fi

# Esegui una sola volta qm list
qm_out="$(timeout "${PVE_TIMEOUT}" qm list 2>/dev/null)"
rc=$?

if [[ $rc -ne 0 || -z "${qm_out}" ]]; then
  # 124 = timeout
  if [[ $rc -eq 124 ]]; then
    echo "2 PVE_QEMU - CRIT - qm list timed out after ${PVE_TIMEOUT}s"
  else
    echo "2 PVE_QEMU - CRIT - qm list failed (rc=${rc})"
  fi
  exit 0
fi

# Summary: ignora header (NR>1). Colonne: VMID NAME STATUS ...
total="$(awk 'NR>1{c++} END{print c+0}' <<< "${qm_out}")"
running="$(awk 'NR>1 && $3=="running"{c++} END{print c+0}' <<< "${qm_out}")"
stopped=$(( total - running ))

echo "0 PVE_QEMU_Summary running=${running} total=${total} OK - ${running}/${total} running"
echo "0 PVE_QEMU_Stopped_Count stopped=${stopped} OK - ${stopped} stopped"

# Per-VM status (da qm list)
awk 'NR>1{print $1, $2, $3}' <<< "${qm_out}" | while read -r vmid name status; do
  [[ -z "${name:-}" ]] && name="vm${vmid}"

  svc="PVE_QEMU_${vmid}_$(echo "$name" | tr ' /' '__' | tr -cd 'A-Za-z0-9_.:-')"

  if [[ "$status" == "running" ]]; then
    echo "0 ${svc} - OK - running"
  elif [[ "$status" == "stopped" ]]; then
    echo "0 ${svc} - OK - stopped"
  else
    echo "2 ${svc} - CRIT - status ${status:-unknown}"
  fi
done

exit 0