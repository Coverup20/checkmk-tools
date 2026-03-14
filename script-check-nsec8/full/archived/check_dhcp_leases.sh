#!/bin/bash
# CheckMK plugin - Monitoraggio DHCP leases
# Conta lease attivi e disponibili

LEASE_FILE="/tmp/dhcp.leases"

if [[ ! -f "$LEASE_FILE" ]]; then
    echo "1 DHCP_Leases - File leases non trovato"
    exit 0
fi

# Conta lease attivi (non expired)
current_time=$(date +%s)
active_leases=0
expired_leases=0
total_leases=0

while IFS=' ' read -r expire_time mac ip hostname client_id; do
    total_leases=$((total_leases + 1))
    
    if [[ $expire_time -gt $current_time ]]; then
        active_leases=$((active_leases + 1))
    else
        expired_leases=$((expired_leases + 1))
    fi
done < "$LEASE_FILE"

# Leggi configurazione DHCP per trovare pool size
dhcp_start=$(uci get dhcp.lan.start 2>/dev/null || echo 100)
dhcp_limit=$(uci get dhcp.lan.limit 2>/dev/null || echo 150)
max_leases=$dhcp_limit

# Calcola percentuale utilizzo
if [[ $max_leases -gt 0 ]]; then
    percent=$((active_leases * 100 / max_leases))
else
    percent=0
fi

# Determina stato
if [[ $percent -ge 90 ]]; then
    status=2
    status_text="CRITICAL"
elif [[ $percent -ge 80 ]]; then
    status=1
    status_text="WARNING"
else
    status=0
    status_text="OK"
fi

echo "$status DHCP_Leases active=${active_leases};$((max_leases * 80 / 100));$((max_leases * 90 / 100));0;${max_leases} Lease attivi: $active_leases/$max_leases (${percent}%) - $status_text | active=$active_leases expired=$expired_leases total=$total_leases max=$max_leases percent=$percent"
