#!/bin/bash
# CheckMK plugin - Test risoluzione DNS
# Verifica che il DNS locale risponda correttamente

# Domini da testare
test_domains=("google.com" "cloudflare.com" "dns.google")
dns_server="127.0.0.1"
successful=0
failed=0
total=${#test_domains[@]}
response_times=()

for domain in "${test_domains[@]}"; do
    # Test risoluzione con timeout
    start_time=$(date +%s%N)
    result=$(nslookup "$domain" "$dns_server" 2>/dev/null | grep -A1 "Name:" | tail -1 | grep "Address")
    end_time=$(date +%s%N)
    
    if [[ -n "$result" ]]; then
        successful=$((successful + 1))
        response_time=$(( (end_time - start_time) / 1000000 )) # ms
        response_times+=($response_time)
    else
        failed=$((failed + 1))
    fi
done

# Calcola tempo medio
if [[ ${#response_times[@]} -gt 0 ]]; then
    avg_time=0
    for time in "${response_times[@]}"; do
        avg_time=$((avg_time + time))
    done
    avg_time=$((avg_time / ${#response_times[@]}))
else
    avg_time=0
fi

# Determina stato
if [[ $failed -eq $total ]]; then
    status=2
    status_text="CRITICAL - DNS non risponde"
elif [[ $failed -gt 0 ]]; then
    status=1
    status_text="WARNING - Alcuni test falliti"
elif [[ $avg_time -gt 1000 ]]; then
    status=1
    status_text="WARNING - DNS lento"
else
    status=0
    status_text="OK"
fi

echo "$status DNS_Resolution response_time=${avg_time}ms;500;1000 Test: $successful/$total OK, tempo medio: ${avg_time}ms - $status_text | successful=$successful failed=$failed total=$total avg_time_ms=$avg_time"
