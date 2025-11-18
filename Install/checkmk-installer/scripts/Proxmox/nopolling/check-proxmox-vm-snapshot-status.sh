#!/bin/bash
# ============================================================
# Check-Proxmox-VM-Snapshot-Status.sh
# Versione: 1.6
# Autore: NethLab / Marzio Project
# Compatibilità: Proxmox VE 8.x + Checkmk Raw 2.4.x
# ============================================================

# Funzione per trasformare testo in Title Case
to_title_case() {
    echo "$1" | sed 's/.*/\L&/' | sed 's/[a-z]*/\u&/g'
}

# Funzione per analizzare snapshot VM
check_vm_snapshots() {
    qm list | awk 'NR>1 {print $1, $2}' | while read -r vmid name; do
        output=$(qm listsnapshot "$vmid" 2>/dev/null)
        snapshot_list=$(echo "$output" | awk 'NR>1 {for(i=1;i<=NF;i++) if ($i !~ /^[-`>|]/) {print $i; break}}')
        snapshot_count=$(echo "$snapshot_list" | grep -c .)
        running_snapshot=$(echo "$output" | grep -i "state" | grep -i "prepare\|running")

        vm_name_upper=$(echo "SNAPSHOT_VM_${vmid}_$(echo "$name" | tr '[:lower:]' '[:upper:]')")
        details=$(echo "$snapshot_list" | tr '\n' ',' | sed 's/,$//')

        if [[ -n "$running_snapshot" ]]; then
            echo "1 $vm_name_upper - Snapshot In Corso: $(to_title_case "$details")"
        elif [[ "$snapshot_count" -eq 0 ]]; then
            echo "2 $vm_name_upper - Nessuno Snapshot Presente"
        else
            echo "0 $vm_name_upper - $snapshot_count Snapshot: $(to_title_case "$details")"
        fi
    done
}

# Funzione per analizzare snapshot LXC
check_lxc_snapshots() {
    pct list | awk 'NR>1 {print $1, $2}' | while read -r ctid name; do
        output=$(pct listsnapshot "$ctid" 2>/dev/null)
        snapshot_list=$(echo "$output" | awk 'NR>1 {for(i=1;i<=NF;i++) if ($i !~ /^[-`>|]/) {print $i; break}}')
        snapshot_count=$(echo "$snapshot_list" | grep -c .)
        running_snapshot=$(echo "$output" | grep -i "state" | grep -i "prepare\|running")

        lxc_name_upper=$(echo "SNAPSHOT_CT_${ctid}_$(echo "$name" | tr '[:lower:]' '[:upper:]')")
        details=$(echo "$snapshot_list" | tr '\n' ',' | sed 's/,$//')

        if [[ -n "$running_snapshot" ]]; then
            echo "1 $lxc_name_upper - Snapshot In Corso: $(to_title_case "$details")"
        elif [[ "$snapshot_count" -eq 0 ]]; then
            echo "2 $lxc_name_upper - Nessuno Snapshot Presente"
        else
            echo "0 $lxc_name_upper - $snapshot_count Snapshot: $(to_title_case "$details")"
        fi
    done
}

# Esecuzione
check_vm_snapshots
check_lxc_snapshots
