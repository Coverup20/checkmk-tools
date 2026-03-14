#!/bin/bash
# CheckMK plugin - Monitoraggio connessioni OpenVPN Host-to-Net
# Controlla client connessi, traffico, durata connessioni

# Directory status OpenVPN
STATUS_DIR="/var/run/openvpn"
STATUS_FILES=()

# Verifica directory status
if [[ ! -d "$STATUS_DIR" ]]; then
    echo "0 OVPN_HostToNet - OpenVPN non configurato o non in esecuzione"
    exit 0
fi

# Trova file status
while IFS= read -r file; do
    STATUS_FILES+=("$file")
done < <(find "$STATUS_DIR" -name "*.status" 2>/dev/null)

# Se nessun file status trovato
if [[ ${#STATUS_FILES[@]} -eq 0 ]]; then
    echo "0 OVPN_HostToNet - Nessun server OpenVPN host-to-net attivo"
    exit 0
fi

# Variabili contatori
total_clients=0
total_servers=0
client_list=()
client_details=()

# Analizza ogni file status
for status_file in "${STATUS_FILES[@]}"; do
    server_name=$(basename "$status_file" .status)
    total_servers=$((total_servers + 1))
    
    # Conta client connessi (righe CLIENT_LIST)
    if [[ -f "$status_file" ]]; then
        client_count=0
        
        # Leggi righe CLIENT_LIST
        while IFS=',' read -r type common_name real_address virtual_address bytes_received bytes_sent connected_since; do
            if [[ "$type" == "CLIENT_LIST" ]]; then
                client_count=$((client_count + 1))
                total_clients=$((total_clients + 1))
                
                # Estrai informazioni client
                client_ip=$(echo "$real_address" | cut -d: -f1)
                vpn_ip=$(echo "$virtual_address" | cut -d: -f1)
                
                # Calcola durata connessione
                if [[ -n "$connected_since" ]]; then
                    conn_timestamp=$(date -d "$connected_since" +%s 2>/dev/null || echo 0)
                    current_timestamp=$(date +%s)
                    duration_sec=$((current_timestamp - conn_timestamp))
                    duration_min=$((duration_sec / 60))
                else
                    duration_min=0
                fi
                
                # Converti bytes in MB
                bytes_rx_mb=$((bytes_received / 1048576))
                bytes_tx_mb=$((bytes_sent / 1048576))
                
                # Aggiungi a lista
                client_list+=("$common_name")
                client_details+=("$common_name($vpn_ip):${duration_min}m,RX:${bytes_rx_mb}MB,TX:${bytes_tx_mb}MB")
            fi
        done < "$status_file"
        
        # Se nessun client su questo server, annotalo
        if [[ $client_count -eq 0 ]]; then
            client_details+=("${server_name}:0_clients")
        fi
    fi
done

# Determina stato
status=0
status_text="OK"

if [[ $total_servers -eq 0 ]]; then
    status=1
    status_text="WARNING - Nessun server OpenVPN configurato"
elif [[ $total_clients -eq 0 ]]; then
    status=0
    status_text="OK - $total_servers server attivi, nessun client connesso"
elif [[ $total_clients -ge 50 ]]; then
    status=1
    status_text="WARNING - Molti client connessi: $total_clients"
else
    status=0
    status_text="OK - $total_clients client connessi su $total_servers server"
fi

# Output CheckMK principale
echo "$status OVPN_HostToNet clients=$total_clients;50;100;0 servers=$total_servers - $status_text | total_clients=$total_clients total_servers=$total_servers"

# Dettagli server
if [[ $total_servers -gt 0 ]]; then
    server_list=""
    for status_file in "${STATUS_FILES[@]}"; do
        server_name=$(basename "$status_file" .status)
        server_list="$server_list$server_name "
    done
    echo "0 OVPN_Servers - Active servers: $server_list"
fi

# Dettagli client connessi (max 10 per non appesantire)
if [[ ${#client_list[@]} -gt 0 ]]; then
    unique_clients=$(printf '%s\n' "${client_list[@]}" | sort -u | wc -l)
    echo "0 OVPN_Connected_Clients count=$unique_clients - Unique clients: $unique_clients"
    
    # Lista primi 10 client con dettagli
    if [[ ${#client_details[@]} -le 10 ]]; then
        details=$(printf '%s, ' "${client_details[@]}" | sed 's/, $//')
        echo "0 OVPN_Client_Details - $details"
    else
        details=$(printf '%s, ' "${client_details[@]:0:10}" | sed 's/, $//')
        remaining=$((${#client_details[@]} - 10))
        echo "0 OVPN_Client_Details - $details ... (+$remaining more)"
    fi
fi

# Verifica processo OpenVPN running
openvpn_processes=$(ps | grep -c "[o]penvpn" || echo 0)
if [[ $openvpn_processes -eq 0 ]]; then
    echo "2 OVPN_Process - CRITICAL - Nessun processo OpenVPN in esecuzione"
else
    echo "0 OVPN_Process - OK - $openvpn_processes processi OpenVPN attivi"
fi
