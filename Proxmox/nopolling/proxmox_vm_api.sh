#!/bin/bash
# Script Checkmk local check per Proxmox VE (RAM + Stato)
# Richiede: jq

echo "<<<local>>>"

vms=$(pvesh get /cluster/resources --type vm --output-format json | jq -c '.[] | select(.type=="qemu")')

for vm in $vms; do
    vmid=$(echo "$vm" | jq -r '.vmid')
    name=$(echo "$vm" | jq -r '.name')
    status=$(echo "$vm" | jq -r '.status')
    maxmem=$(echo "$vm" | jq -r '.maxmem')
    mem=$(echo "$vm" | jq -r '.mem')

    # Stato
    if [[ "$status" == "running" ]]; then
        echo "0 vm_${vmid}_${name} Stato - VM ${vmid} (${name}) accesa"
    else
        echo "0 vm_${vmid}_${name} Stato - VM ${vmid} (${name}) spenta"
    fi

    # RAM
    if [[ "$status" == "running" && "$maxmem" -gt 0 ]]; then
        used_percent=$(( mem * 100 / maxmem ))
        echo "0 vm_${vmid}_${name} RAM used=${mem};;;0;${maxmem} RAM: ${used_percent}%"
    else
        conf="/etc/pve/qemu-server/${vmid}.conf"
        if [[ -f "$conf" ]]; then
            conf_mem=$(grep -i '^memory:' "$conf" | awk '{print $2}')
            if [[ -n "$conf_mem" ]]; then
                maxmem_conf=$(( conf_mem * 1024 * 1024 ))
                echo "0 vm_${vmid}_${name} RAM used=0;;;0;${maxmem_conf} RAM: 0% (VM spenta)"
            else
                echo "0 vm_${vmid}_${name} RAM - RAM non configurata (VM spenta)"
            fi
        else
            echo "0 vm_${vmid}_${name} RAM - Config mancante (VM spenta)"
        fi
    fi
done
