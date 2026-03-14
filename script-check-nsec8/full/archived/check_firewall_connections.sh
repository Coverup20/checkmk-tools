#!/bin/bash
# CheckMK plugin - Monitoraggio connessioni firewall (conntrack)
# Controlla numero di connessioni attive e limiti
# Leggi statistiche conntrack
if [[ -f /proc/sys/net/netfilter/nf_conntrack_count ]]; then
    current=$(cat /proc/sys/net/netfilter/nf_conntrack_count)
    max=$(cat /proc/sys/net/netfilter/nf_conntrack_max)
else    
    echo "1 Firewall_Connections - Conntrack non disponibile"
    exit 0
fi # Calcola percentuale utilizzopercent=$((current * 100 / max))
# Determina stato (warning 80%, critical 90%)
if [[ $percent -ge 90 ]]; then
    status=2    status_text="CRITICAL"
elif [[ $percent -ge 80 ]]; then
    status=1    status_text="WARNING"
else    status=0    status_text="OK"
fi # Output CheckMK con perfdata
echo "$status Firewall_Connections connections=${current};$((max * 80 / 100));$((max * 90 / 100));0;${max} Connessioni attive: $current/$max (${percent}%) - Status: $status_text | current=$current max=$max percent=$percent"
