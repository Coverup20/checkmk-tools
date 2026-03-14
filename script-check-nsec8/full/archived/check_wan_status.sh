#!/bin/bash
# CheckMK plugin per monitoraggio stato WAN su NSecFirewall8 (OpenWrt)
# Controlla stato interfacce WAN e connettività

# Funzione per ottenere lo stato di un'interfaccia via ubus
get_interface_status() {
    local iface="$1"
    local status_json
    
    status_json=$(ubus call network.interface."$iface" status 2>/dev/null)
    if [[ $? -ne 0 || -z "$status_json" ]]; then
        echo "unknown"
        return 1
    fi
    
    # Estrae lo stato up/down
    echo "$status_json" | jsonfilter -e '@.up' 2>/dev/null || echo "unknown"
}

# Funzione per verificare connettività
check_connectivity() {
    local target="$1"
    local count="${2:-2}"
    
    ping -c "$count" -W 2 "$target" >/dev/null 2>&1
    return $?
}

# Funzione per ottenere gateway
get_gateway() {
    local iface="$1"
    local status_json
    
    status_json=$(ubus call network.interface."$iface" status 2>/dev/null)
    if [[ $? -ne 0 || -z "$status_json" ]]; then
        echo ""
        return 1
    fi
    
    # Estrae il primo gateway dalla lista route
    echo "$status_json" | jsonfilter -e '@.route[0].nexthop' 2>/dev/null || echo ""
}

# Trova tutte le interfacce WAN configurate
find_wan_interfaces() {
    # Lista interfacce via ubus
    ubus list | grep '^network\.interface\.' | sed 's/network\.interface\.//' | grep -E '^(wan|wwan|vwan)'
}

# Main
wan_interfaces=$(find_wan_interfaces)

if [[ -z "$wan_interfaces" ]]; then
    echo "0 WAN_Status status=ERROR No WAN interfaces found"
    exit 0
fi

overall_status=0
status_messages=()
details=()

# Controlla ogni interfaccia WAN
for iface in $wan_interfaces; do
    status=$(get_interface_status "$iface")
    gateway=$(get_gateway "$iface")
    
    if [[ "$status" == "true" || "$status" == "1" ]]; then
        # Interfaccia UP - verifica connettività
        if [[ -n "$gateway" ]]; then
            if check_connectivity "$gateway"; then
                details+=("$iface: UP (gateway $gateway reachable)")
                status_messages+=("$iface=OK")
            else
                details+=("$iface: UP but gateway $gateway unreachable")
                status_messages+=("$iface=DEGRADED")
                overall_status=1
            fi
        else
            # UP ma senza gateway
            # Prova DNS pubblici
            if check_connectivity "8.8.8.8" || check_connectivity "1.1.1.1"; then
                details+=("$iface: UP (internet reachable)")
                status_messages+=("$iface=OK")
            else
                details+=("$iface: UP but no connectivity")
                status_messages+=("$iface=DEGRADED")
                overall_status=1
            fi
        fi
    elif [[ "$status" == "false" || "$status" == "0" ]]; then
        # Interfaccia DOWN
        details+=("$iface: DOWN")
        status_messages+=("$iface=DOWN")
        overall_status=2
    else
        # Stato sconosciuto
        details+=("$iface: UNKNOWN")
        status_messages+=("$iface=UNKNOWN")
        overall_status=1
    fi
done

# Determina stato finale
if [[ $overall_status -eq 0 ]]; then
    final_status="OK"
elif [[ $overall_status -eq 1 ]]; then
    final_status="WARNING"
else
    final_status="CRITICAL"
fi

# Output CheckMK
status_line="${status_messages[*]}"
detail_line=$(IFS=', '; echo "${details[*]}")

echo "$overall_status WAN_Status status=$final_status $status_line - $detail_line"

# Metriche aggiuntive (opzionale)
wan_count=$(echo "$wan_interfaces" | wc -l)
wan_up=$(echo "${status_messages[@]}" | grep -o "=OK" | wc -l)
wan_down=$(echo "${status_messages[@]}" | grep -o "=DOWN" | wc -l)
wan_degraded=$(echo "${status_messages[@]}" | grep -o "=DEGRADED" | wc -l)

echo "0 WAN_Metrics - Total=$wan_count Up=$wan_up Down=$wan_down Degraded=$wan_degraded | total=$wan_count up=$wan_up down=$wan_down degraded=$wan_degraded"
