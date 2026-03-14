#!/bin/bash
# Proxmox VM Disks Check
# Monitora utilizzo dischi VM e container

set -euo pipefail

PVE_TIMEOUT=30

# Check VM disks
timeout "${PVE_TIMEOUT}" qm list 2>/dev/null | awk 'NR>1 {print $1, $2}' | while IFS=' ' read -r vmid name; do
    disk_info=$(timeout "${PVE_TIMEOUT}" qm config "$vmid" 2>/dev/null | grep -E '^(scsi|ide|sata|virtio)[0-9]:' || true)
    
    if [[ -z "$disk_info" ]]; then
        continue
    fi
    
    disk_count=$(echo "$disk_info" | wc -l)
    vm_name_upper="DISKS_VM_${vmid}_$(echo "$name" | tr '[:lower:]' '[:upper:]')"
    
    # Parse sizes
    total_size=0
    while IFS= read -r line; do
        size=$(echo "$line" | grep -oP 'size=\K[0-9]+[GMK]' || echo "0")
        
        # Convert to GB
        if [[ "$size" =~ ^([0-9]+)G$ ]]; then
            total_size=$((total_size + ${BASH_REMATCH[1]}))
        elif [[ "$size" =~ ^([0-9]+)M$ ]]; then
            total_size=$((total_size + ${BASH_REMATCH[1]} / 1024))
        elif [[ "$size" =~ ^([0-9]+)K$ ]]; then
            total_size=$((total_size + ${BASH_REMATCH[1]} / 1048576))
        fi
    done <<< "$disk_info"
    
    echo "0 $vm_name_upper - $disk_count disks, Total: ${total_size}GB | disks=$disk_count size_gb=$total_size"
done

# Check LXC disks
timeout "${PVE_TIMEOUT}" pct list 2>/dev/null | awk 'NR>1 {print $1, $2}' | while IFS=' ' read -r ctid name; do
    rootfs=$(timeout "${PVE_TIMEOUT}" pct config "$ctid" 2>/dev/null | grep '^rootfs:' || true)
    
    if [[ -z "$rootfs" ]]; then
        continue
    fi
    
    lxc_name_upper="DISKS_CT_${ctid}_$(echo "$name" | tr '[:lower:]' '[:upper:]')"
    size=$(echo "$rootfs" | grep -oP 'size=\K[0-9]+[GMK]' || echo "0G")
    
    # Convert to GB
    if [[ "$size" =~ ^([0-9]+)G$ ]]; then
        size_gb=${BASH_REMATCH[1]}
    elif [[ "$size" =~ ^([0-9]+)M$ ]]; then
        size_gb=$((${BASH_REMATCH[1]} / 1024))
    else
        size_gb=0
    fi
    
    echo "0 $lxc_name_upper - RootFS: ${size_gb}GB | size_gb=$size_gb"
done

exit 0
