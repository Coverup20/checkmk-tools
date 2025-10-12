#!/bin/bash
# Script Checkmk local check per Proxmox VE (Dischi VM)
# Richiede: jq

echo "<<<local>>>"

vms=$(pvesh get /cluster/resources --type vm --output-format json | jq -c '.[] | select(.type=="qemu")')

for vm in $vms; do
    vmid=$(echo "$vm" | jq -r '.vmid')
    name=$(echo "$vm" | jq -r '.name')

    # Ottieni info dischi
    disks=$(pvesh get /nodes/$(hostname)/qemu/${vmid}/config --output-format json | jq -r '. | to_entries[] | select(.key|test("ide|scsi|sata|virtio")) | "\(.key)=\(.value)"')

    for d in $disks; do
        dev=$(echo "$d" | cut -d= -f1)
        size=$(echo "$d" | cut -d= -f2 | sed 's/,.*//')
        [[ "$size" == "" ]] && size="unknownG"

        # Qui puoi calcolare uso se vuoi, per ora mettiamo 0%
        used=0

        echo "0 vm_${vmid}_${name} Disk disk_used=${used}%;80;90 disk_alloc=${size} - VM ${vmid} (${name}) disco ${size}"
    done
done
