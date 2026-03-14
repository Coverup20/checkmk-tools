#!/bin/bash
# CheckMK plugin - Monitoraggio traffico interfacce firewall
# Mostra RX/TX bytes per interfaccia WAN e LAN

# Trova interfacce WAN e LAN
wan_ifaces=$(ubus list | grep '^network\.interface\.' | sed 's/network\.interface\.//' | grep -E '^(wan|wwan)')
lan_ifaces=$(ubus list | grep '^network\.interface\.' | sed 's/network\.interface\.//' | grep -E '^(lan|br-lan)')

# Funzione per ottenere device fisico da interfaccia logica
get_device() {
    local iface="$1"
    ubus call network.interface."$iface" status 2>/dev/null | jsonfilter -e '@.device' 2>/dev/null
}

# Funzione per leggere statistiche interfaccia
get_stats() {
    local device="$1"
    if [[ -d "/sys/class/net/$device" ]]; then
        rx_bytes=$(cat "/sys/class/net/$device/statistics/rx_bytes" 2>/dev/null || echo 0)
        tx_bytes=$(cat "/sys/class/net/$device/statistics/tx_bytes" 2>/dev/null || echo 0)
        rx_packets=$(cat "/sys/class/net/$device/statistics/rx_packets" 2>/dev/null || echo 0)
        tx_packets=$(cat "/sys/class/net/$device/statistics/tx_packets" 2>/dev/null || echo 0)
        rx_errors=$(cat "/sys/class/net/$device/statistics/rx_errors" 2>/dev/null || echo 0)
        tx_errors=$(cat "/sys/class/net/$device/statistics/tx_errors" 2>/dev/null || echo 0)
        
        echo "$rx_bytes $tx_bytes $rx_packets $tx_packets $rx_errors $tx_errors"
    else
        echo "0 0 0 0 0 0"
    fi
}

# Monitora WAN
for iface in $wan_ifaces; do
    device=$(get_device "$iface")
    if [[ -n "$device" ]]; then
        read -r rx_bytes tx_bytes rx_packets tx_packets rx_errors tx_errors < <(get_stats "$device")
        
        status=0
        if [[ $rx_errors -gt 100 || $tx_errors -gt 100 ]]; then
            status=1
        fi

        echo "$status ${iface}_traffic - RX: $rx_bytes bytes, TX: $tx_bytes bytes | rx_bytes=$rx_bytes tx_bytes=$tx_bytes rx_packets=$rx_packets tx_packets=$tx_packets rx_errors=$rx_errors tx_errors=$tx_errors"
    fi
done

# Monitora LAN
for iface in $lan_ifaces; do
    device=$(get_device "$iface")
    if [[ -n "$device" ]]; then
        read -r rx_bytes tx_bytes rx_packets tx_packets rx_errors tx_errors < <(get_stats "$device")
        
        status=0
        if [[ $rx_errors -gt 100 || $tx_errors -gt 100 ]]; then
            status=1
        fi

        echo "$status ${iface}_traffic - RX: $rx_bytes bytes, TX: $tx_bytes bytes | rx_bytes=$rx_bytes tx_bytes=$tx_bytes rx_packets=$rx_packets tx_packets=$tx_packets rx_errors=$rx_errors tx_errors=$tx_errors"
    fi
done
