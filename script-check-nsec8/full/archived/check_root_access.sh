#!/bin/bash
# CheckMK plugin - Monitoraggio accessi root
# Controlla login root, sessioni attive e tentativi falliti

# Configurazione
LOG_FILE="/var/log/messages"
WARN_FAILED_LOGINS=5
CRIT_FAILED_LOGINS=10
TIME_WINDOW=3600  # Ultimi 60 minuti

# Timestamp corrente e limite
current_time=$(date +%s)
time_limit=$((current_time - TIME_WINDOW))

# Variabili contatori
active_sessions=0
successful_logins=0
failed_logins=0
recent_ips=()

# Controlla sessioni root attive (usa ps se who non disponibile)
if command -v who >/dev/null 2>&1; then
    active_sessions=$(who | grep -c "^root" || echo 0)
else
    # Conta processi bash/sh con UID 0 (root)
    active_sessions=$(ps | grep -E "(bash|sh|dropbear)" | grep -v grep | wc -l)
fi

# Analizza log recenti (ultimi 60 minuti)
if [[ -f "$LOG_FILE" ]]; then
    # Estrai timestamp e eventi
    while IFS= read -r line; do
        # Cerca pattern login SSH
        if echo "$line" | grep -qiE "(Accepted password|Accepted publickey).* for root"; then
            successful_logins=$((successful_logins + 1))
            ip=$(echo "$line" | grep -oE "([0-9]{1,3}\.){3}[0-9]{1,3}" | head -1)
            [[ -n "$ip" ]] && recent_ips+=("$ip")
        fi
        
        # Cerca tentativi falliti
        if echo "$line" | grep -qiE "(Failed password|authentication failure).* for root"; then
            failed_logins=$((failed_logins + 1))
        fi
    done < <(grep -E "sshd|dropbear|authpriv" "$LOG_FILE" 2>/dev/null | tail -500)
fi

# IPs univoci
unique_ips=$(printf '%s\n' "${recent_ips[@]}" | sort -u | wc -l)

# Determina stato
if [[ $failed_logins -ge $CRIT_FAILED_LOGINS ]]; then
    status=2
    status_text="CRITICAL - Troppi tentativi falliti ($failed_logins)"
elif [[ $failed_logins -ge $WARN_FAILED_LOGINS ]]; then
    status=1
    status_text="WARNING - Tentativi falliti: $failed_logins"
elif [[ $active_sessions -gt 2 ]]; then
    status=1
    status_text="WARNING - Troppe sessioni root attive: $active_sessions"
elif [[ $successful_logins -gt 0 || $active_sessions -gt 0 ]]; then
    status=0
    status_text="OK - Accessi: $successful_logins, Sessioni attive: $active_sessions"
else
    status=0
    status_text="OK - Nessun accesso recente"
fi

# Output CheckMK
echo "$status Root_Access sessions=$active_sessions;2;3;0 logins=$successful_logins failed=$failed_logins;$WARN_FAILED_LOGINS;$CRIT_FAILED_LOGINS;0 - $status_text | active_sessions=$active_sessions successful_logins=$successful_logins failed_logins=$failed_logins unique_ips=$unique_ips"

# Dettagli IPs (se ci sono accessi)
if [[ ${#recent_ips[@]} -gt 0 ]]; then
    ip_list=$(printf '%s\n' "${recent_ips[@]}" | sort -u | head -5 | tr '\n' ' ')
    echo "0 Root_Access_IPs - Recent IPs: $ip_list"
fi
