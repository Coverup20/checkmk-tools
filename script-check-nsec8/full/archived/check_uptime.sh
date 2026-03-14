#!/bin/bash
# CheckMK plugin - Uptime e load average firewall

# Leggi uptime in secondi
if [[ -f /proc/uptime ]]; then
    uptime_seconds=$(cut -d. -f1 /proc/uptime)
else
    uptime_seconds=0
fi

# Converti in giorni, ore, minuti
days=$((uptime_seconds / 86400))
hours=$(( (uptime_seconds % 86400) / 3600 ))
minutes=$(( (uptime_seconds % 3600) / 60 ))

# Leggi load average
if [[ -f /proc/loadavg ]]; then
    read -r load1 load5 load15 rest < /proc/loadavg
else
    load1=0
    load5=0
    load15=0
fi

# Numero di CPU
cpu_count=$(nproc 2>/dev/null || echo 1)

# Calcola load normalizzato per CPU
load1_norm=$(awk "BEGIN {printf \"%.2f\", $load1 / $cpu_count}")
load5_norm=$(awk "BEGIN {printf \"%.2f\", $load5 / $cpu_count}")

# Determina stato in base al load (warning se > 0.8 per CPU, critical se > 1.5)
load1_check=$(awk "BEGIN {if ($load1_norm > 1.5) print 2; else if ($load1_norm > 0.8) print 1; else print 0}")
status=$load1_check

if [[ $status -eq 2 ]]; then
    status_text="CRITICAL - Load alto"
elif [[ $status -eq 1 ]]; then
    status_text="WARNING - Load elevato"
else
    status_text="OK"
fi

echo "$status Firewall_Uptime - Uptime: ${days}d ${hours}h ${minutes}m, Load: $load1 $load5 $load15 (${cpu_count} CPU) - $status_text | uptime_seconds=$uptime_seconds load1=$load1 load5=$load5 load15=$load15 cpu_count=$cpu_count"
