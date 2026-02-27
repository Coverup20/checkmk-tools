#!/bin/bash
# CheckMK plugin - Monitoraggio Martian Packets
# Controlla pacchetti con IP sorgente/destinazione non validi
# Version: 1.1.0 - rimossa logica rp_filter (normale su firewall)

# Configurazione soglie
WARN_THRESHOLD=10
CRIT_THRESHOLD=50
TIME_WINDOW=3600  # Ultimi 60 minuti

# File log da verificare
LOG_FILE="/var/log/messages"
DMESG_LOG="/var/log/dmesg"

# Contatori
martian_count=0
martian_sources=()
martian_destinations=()
unique_ips=0

# Cerca nei log di sistema
if [[ -f "$LOG_FILE" ]]; then
    # Cerca martian source/destination negli ultimi log
    while IFS= read -r line; do
        # Estrai IP sorgente martian
        if echo "$line" | grep -q "martian source"; then
            martian_count=$((martian_count + 1))
            ip=$(echo "$line" | grep -oE "from ([0-9]{1,3}\.){3}[0-9]{1,3}" | awk '{print $2}')
            [[ -n "$ip" ]] && martian_sources+=("$ip")
        fi
        
        # Estrai IP destinazione martian
        if echo "$line" | grep -q "martian destination"; then
            martian_count=$((martian_count + 1))
            ip=$(echo "$line" | grep -oE "to ([0-9]{1,3}\.){3}[0-9]{1,3}" | awk '{print $2}')
            [[ -n "$ip" ]] && martian_destinations+=("$ip")
        fi
    done < <(grep -i "martian" "$LOG_FILE" 2>/dev/null | tail -200)
fi

# Verifica anche dmesg (buffer kernel)
if command -v dmesg >/dev/null 2>&1; then
    dmesg_martians=$(dmesg 2>/dev/null | grep -i "martian" | wc -l)
    if [[ $dmesg_martians -gt 0 ]]; then
        martian_count=$((martian_count + dmesg_martians))
    fi
fi

# Conta IP univoci
all_ips=("${martian_sources[@]}" "${martian_destinations[@]}")
if [[ ${#all_ips[@]} -gt 0 ]]; then
    unique_ips=$(printf '%s\n' "${all_ips[@]}" | sort -u | wc -l)
fi

# Determina stato
status=0
status_text="OK"

if [[ $martian_count -ge $CRIT_THRESHOLD ]]; then
    status=2
    status_text="CRITICAL - $martian_count martian packets rilevati"
elif [[ $martian_count -ge $WARN_THRESHOLD ]]; then
    status=1
    status_text="WARNING - $martian_count martian packets rilevati"
elif [[ $martian_count -gt 0 ]]; then
    status=0
    status_text="OK - $martian_count martian packets (sotto soglia)"
else
    status=0
    status_text="OK - Nessun martian packet"
fi

# Output CheckMK
echo "$status Martian_Packets count=$martian_count;$WARN_THRESHOLD;$CRIT_THRESHOLD;0 unique_ips=$unique_ips - $status_text | martian_count=$martian_count unique_ips=$unique_ips"

# Dettagli IP sorgente (se presenti)
if [[ ${#martian_sources[@]} -gt 0 ]]; then
    source_list=$(printf '%s\n' "${martian_sources[@]}" | sort -u | head -5 | tr '\n' ' ')
    echo "0 Martian_Sources - IPs: $source_list"
fi

# Dettagli IP destinazione (se presenti)
if [[ ${#martian_destinations[@]} -gt 0 ]]; then
    dest_list=$(printf '%s\n' "${martian_destinations[@]}" | sort -u | head -5 | tr '\n' ' ')
    echo "0 Martian_Destinations - IPs: $dest_list"
fi


