#!/bin/bash
# Monitor Proxmox VM: Status, RAM, Disk (con LVM-thin)
# Checkmk local check format

# Soglie
WARN_RAM=80
CRIT_RAM=90
WARN_DISK=80
CRIT_DISK=90

NODE=$(hostname)

# Loop sulle VM (estrai VMID e NAME dalla tabella di qm list)
qm list | awk 'NR>1 {print $1, $2}' | while read -r vmid name; do

    # -------------------------
    # STATUS VM
    # -------------------------
    status=$(qm status $vmid | awk '{print $2}')
    if [[ "$status" == "running" ]]; then
        echo "0 vm_${vmid}_${name} Status VM ${vmid} (${name}) accesa"
    else
        echo "0 vm_${vmid}_${name} Status VM ${vmid} (${name}) spenta"
    fi

    # -------------------------
    # RAM
    # -------------------------
    config=$(pvesh get /nodes/$NODE/qemu/$vmid/config --output-format json 2>/dev/null)
    alloc=$(echo "$config" | jq -r '.memory // empty')

    if [[ -n "$alloc" && "$alloc" != "null" ]]; then
        alloc_bytes=$((alloc * 1024 * 1024))

        if [[ "$status" == "running" ]]; then
            current=$(pvesh get /nodes/$NODE/qemu/$vmid/status/current --output-format json 2>/dev/null)
            used=$(echo "$current" | jq -r '.mem // 0')

            perc=$(( used * 100 / alloc_bytes ))
            used_h=$(awk "BEGIN {printf \"%.1f\", $used / 1024 / 1024 / 1024}")
            alloc_h=$(awk "BEGIN {printf \"%.1f\", $alloc_bytes / 1024 / 1024 / 1024}")

            if (( perc >= CRIT_RAM )); then
                state=2
            elif (( perc >= WARN_RAM )); then
                state=1
            else
                state=0
            fi

            # Perfdata + testo leggibile
            echo "$state vm_${vmid}_${name} RAM | used=$used;$WARN_RAM;$CRIT_RAM;0;$alloc_bytes RAM: ${perc}% (${used_h} GB / ${alloc_h} GB)"
        else
            alloc_h=$(awk "BEGIN {printf \"%.1f\", $alloc_bytes / 1024 / 1024 / 1024}")
            echo "0 vm_${vmid}_${name} RAM RAM: 0% (VM spenta, ${alloc_h} GB allocata)"
        fi
    else
        echo "0 vm_${vmid}_${name} RAM RAM: non configurata (VM spenta)"
    fi

    # -------------------------
    # DISCHI (solo LVM-thin, ignora snapshot)
    # -------------------------
    disks=$(lvs --noheadings -o lv_name,lv_size,data_percent --units g --nosuffix 2>/dev/null \
            | grep "vm-${vmid}-disk-" | grep -v "snap_")

    if [[ -n "$disks" ]]; then
        while read -r lv size pct; do
            # Salta se valori vuoti
            if [[ -z "$size" || -z "$pct" || "$pct" == "-" ]]; then
                continue
            fi

            size_gb=$(awk "BEGIN {printf \"%.1f\", $size}")
            pct_int=$(awk "BEGIN {printf \"%d\", $pct}")
            used_gb=$(awk "BEGIN {printf \"%.1f\", $size * $pct / 100}")

            if (( pct_int >= CRIT_DISK )); then
                state=2
            elif (( pct_int >= WARN_DISK )); then
                state=1
            else
                state=0
            fi

            # Perfdata + testo leggibile
            used_bytes=$(awk "BEGIN {printf \"%d\", $used_gb * 1024 * 1024 * 1024}")
            size_bytes=$(awk "BEGIN {printf \"%d\", $size_gb * 1024 * 1024 * 1024}")

            echo "$state vm_${vmid}_${name} Disk | used=$used_bytes;$WARN_DISK;$CRIT_DISK;0;$size_bytes Disk: ${lv} ${pct_int}% (${used_gb} GB / ${size_gb} GB)"
        done <<< "$disks"
    else
        echo "0 vm_${vmid}_${name} Disk Disk: nessun disco trovato su LVM-thin"
    fi

done
