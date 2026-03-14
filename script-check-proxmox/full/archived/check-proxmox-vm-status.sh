#!/bin/bash
# Check Proxmox VM Status
# Monitora stato runtime VM e container

set -euo pipefail

PVE_TIMEOUT=15

# Formatta uptime leggibile
format_uptime() {
    local seconds="$1"
    local days=$((seconds / 86400))
    local hours=$(( (seconds % 86400) / 3600 ))
    local minutes=$(( (seconds % 3600) / 60 ))
    local secs=$((seconds % 60))
    
    local output=""
    (( days > 0 )) && output+="${days}d "
    (( hours > 0 )) && output+="${hours}h "
    (( minutes > 0 )) && output+="${minutes}m "
    (( secs > 0 )) && output+="${secs}s"
    
    [[ -z "$output" ]] && output="0s"
    echo "$output"
}

# Check VM status
check_vm_status() {
    timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1 {print $1, $2, $3}' | while IFS=' ' read -r vmid name status; do
        vm_name_upper="STATUS_VM_${vmid}_$(echo "$name" | tr '[:lower:]' '[:upper:]')"
        
        if [[ "$status" == "running" ]]; then
            uptime_seconds=$(timeout "${PVE_TIMEOUT}" qm status "$vmid" --verbose 2>/dev/null | awk '/^uptime:/ {print $2}')
            [[ -z "$uptime_seconds" ]] && uptime_seconds=0
            uptime_formatted=$(format_uptime "$uptime_seconds")
            
            echo "0 $vm_name_upper - Running (Uptime: $uptime_formatted)"
        elif [[ "$status" == "stopped" ]]; then
            echo "2 $vm_name_upper - Stopped"
        else
            echo "2 $vm_name_upper - Status: $status"
        fi
    done
}

# Check LXC status
check_lxc_status() {
    timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1 {print $1, $3, $2}' | while IFS=' ' read -r ctid name status; do
        lxc_name_upper="STATUS_CT_${ctid}_$(echo "$name" | tr '[:lower:]' '[:upper:]')"
        
        if [[ "$status" == "running" ]]; then
            uptime_seconds=$(timeout "${PVE_TIMEOUT}" pct status "$ctid" --verbose 2>/dev/null | awk '/^uptime:/ {print $2}')
            [[ -z "$uptime_seconds" ]] && uptime_seconds=0
            uptime_formatted=$(format_uptime "$uptime_seconds")
            
            echo "0 $lxc_name_upper - Running (Uptime: $uptime_formatted)"
        elif [[ "$status" == "stopped" ]]; then
            echo "2 $lxc_name_upper - Stopped"
        else
            echo "2 $lxc_name_upper - Status: $status"
        fi
    done
}

# Output CheckMK
echo "<<<local:sep(0)>>>"
check_vm_status
check_lxc_status

exit 0
