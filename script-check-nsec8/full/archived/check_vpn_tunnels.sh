#!/bin/bash
# CheckMK plugin - Monitoraggio tunnel VPN (OpenVPN/WireGuard/IPSec)
# Controlla stato tunnel VPN attivi

total_tunnels=0
active_tunnels=0
inactive_tunnels=0
tunnel_details=()

# Controlla OpenVPN
if [[ -d /var/run/openvpn ]]; then
    for status_file in /var/run/openvpn/*.status; do
        if [[ -f "$status_file" ]]; then
            tunnel_name=$(basename "$status_file" .status)
            total_tunnels=$((total_tunnels + 1))
            
            # Verifica se ci sono client connessi
            client_count=$(grep -c "^CLIENT_LIST" "$status_file" 2>/dev/null || echo 0)
            
            if [[ $client_count -gt 0 ]]; then
                active_tunnels=$((active_tunnels + 1))
                tunnel_details+=(\"OpenVPN_${tunnel_name}: ${client_count} client\")
            else
                inactive_tunnels=$((inactive_tunnels + 1))
                tunnel_details+=(\"OpenVPN_${tunnel_name}: no clients\")
            fi
        fi
    done
fi
# Controlla WireGuard
if command -v wg >/dev/null 2>&1; then
    wg_interfaces=$(wg show interfaces 2>/dev/null)
    for iface in $wg_interfaces; do
        total_tunnels=$((total_tunnels + 1))
        
        peer_count=$(wg show "$iface" peers 2>/dev/null | wc -l)
        active_peers=$(wg show "$iface" latest-handshakes 2>/dev/null | awk '{if ($2 > systime() - 180) print $1}' | wc -l)
        
        if [[ $active_peers -gt 0 ]]; then
            active_tunnels=$((active_tunnels + 1))
            tunnel_details+=("WireGuard_${iface}: ${active_peers}/${peer_count} peers active")
        else
            inactive_tunnels=$((inactive_tunnels + 1))
            tunnel_details+=("WireGuard_${iface}: no active peers")
        fi
    done
fi
# Controlla IPSec (strongswan)
if command -v ipsec >/dev/null 2>&1; then
    ipsec_status=$(ipsec status 2>/dev/null)
    if [[ -n "$ipsec_status" ]]; then
        established=$(echo "$ipsec_status" | grep -c "ESTABLISHED")
        total_tunnels=$((total_tunnels + established))
        active_tunnels=$((active_tunnels + established))
        
        if [[ $established -gt 0 ]]; then
            tunnel_details+=("IPSec: $established tunnels established")
        fi
    fi
fi

# Determina stato
if [[ $total_tunnels -eq 0 ]]; then
    status=0
    status_text="No VPN configured"
elif [[ $active_tunnels -eq 0 ]]; then
    status=2
    status_text="CRITICAL - All VPN down"
elif [[ $active_tunnels -lt $total_tunnels ]]; then
    status=1
    status_text="WARNING - Some VPN down"
else
    status=0
    status_text="OK - All VPN active"
fi

# Output
details_str=$(IFS=', '; echo "${tunnel_details[*]}")

echo "$status VPN_Tunnels active=${active_tunnels};0;0;0;${total_tunnels} Total:$total_tunnels Active:$active_tunnels - $status_text | total=$total_tunnels active=$active_tunnels inactive=$inactive_tunnels"

if [[ -n "$details_str" ]]; then
    echo "0 VPN_Details - $details_str"
fi 