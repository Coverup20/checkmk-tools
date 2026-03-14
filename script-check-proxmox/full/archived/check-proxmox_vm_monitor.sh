#!/bin/bash
# Proxmox VM Monitor
# Check generale VM e container con metriche

set -euo pipefail

PVE_TIMEOUT=15

echo "<<<proxmox_vm_monitor>>>"

# Summary totals
total_vms=$(timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1' | wc -l || echo 0)
running_vms=$(timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1 && $3=="running"' | wc -l || echo 0)
stopped_vms=$((total_vms - running_vms))

total_lxc=$(timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1' | wc -l || echo 0)
running_lxc=$(timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1 && $3=="running"' | wc -l || echo 0)
stopped_lxc=$((total_lxc - running_lxc))

# Determine status
if [[ $stopped_vms -gt 0 || $stopped_lxc -gt 0 ]]; then
    status=1
    status_text="WARNING"
else
    status=0
    status_text="OK"
fi

echo "<<<local:sep(0)>>>"
echo "$status Proxmox_VM_Summary - VMs: $running_vms/$total_vms running, LXC: $running_lxc/$total_lxc running - $status_text | total_vms=$total_vms running_vms=$running_vms stopped_vms=$stopped_vms total_lxc=$total_lxc running_lxc=$running_lxc stopped_lxc=$stopped_lxc"

# Check individual VMs
timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}' | while IFS=' ' read -r vmid name status; do
    vm_safe_name=$(echo "$name" | tr -cd '[:alnum:]_-')
    
    if [[ "$status" == "running" ]]; then
        # Get CPU and memory usage
        vm_status=$(timeout "${PVE_TIMEOUT}" qm status "$vmid" 2>/dev/null || true)
        cpu_pct=$(echo "$vm_status" | grep -oP 'cpu \K[0-9.]+' || echo 0)
        mem_used=$(echo "$vm_status" | grep -oP 'mem \K[0-9]+' || echo 0)
        mem_max=$(echo "$vm_status" | grep -oP 'maxmem \K[0-9]+' || echo 1)
        
        # Calculate memory percentage
        if [[ $mem_max -gt 0 ]]; then
            mem_pct=$(awk "BEGIN {printf \"%.1f\", ($mem_used / $mem_max) * 100}")
        else
            mem_pct=0
        fi
        
        echo "0 VM_${vmid}_${vm_safe_name} - Running | cpu_pct=$cpu_pct mem_pct=$mem_pct mem_used_mb=$((mem_used / 1048576)) mem_max_mb=$((mem_max / 1048576))"
    else
        echo "1 VM_${vmid}_${vm_safe_name} - $status"
    fi
done

# Check individual LXC containers
timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}' | while IFS=' ' read -r ctid name status; do
    lxc_safe_name=$(echo "$name" | tr -cd '[:alnum:]_-')
    
    if [[ "$status" == "running" ]]; then
        ct_status=$(timeout "${PVE_TIMEOUT}" pct status "$ctid" 2>/dev/null || true)
        cpu_pct=$(echo "$ct_status" | grep -oP 'cpu \K[0-9.]+' || echo 0)
        mem_used=$(echo "$ct_status" | grep -oP 'mem \K[0-9]+' || echo 0)
        mem_max=$(echo "$ct_status" | grep -oP 'maxmem \K[0-9]+' || echo 1)
        
        if [[ $mem_max -gt 0 ]]; then
            mem_pct=$(awk "BEGIN {printf \"%.1f\", ($mem_used / $mem_max) * 100}")
        else
            mem_pct=0
        fi
        
        echo "0 LXC_${ctid}_${lxc_safe_name} - Running | cpu_pct=$cpu_pct mem_pct=$mem_pct mem_used_mb=$((mem_used / 1048576)) mem_max_mb=$((mem_max / 1048576))"
    else
        echo "1 LXC_${ctid}_${lxc_safe_name} - $status"
    fi
done

exit 0
