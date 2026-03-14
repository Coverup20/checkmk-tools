#!/bin/bash
# CheckMK plugin - Monitoraggio regole firewall
# Conta regole attive e verifica firewall running

# Verifica che iptables sia running
if ! command -v iptables >/dev/null 2>&1; then
    echo "2 Firewall_Rules - iptables non trovato"
    exit 0
fi # Conta regole per chaininput_rules=$(iptables -L INPUT -n 2>/dev/null | grep -c "^[A-Z]")forward_rules=$(iptables -L FORWARD -n 2>/dev/null | grep -c "^[A-Z]")output_rules=$(iptables -L OUTPUT -n 2>/dev/null | grep -c "^[A-Z]")total_rules=$((input_rules + forward_rules + output_rules))
# Conta regole NATnat_rules=$(iptables -t nat -L -n 2>/dev/null | grep -c "^[A-Z]")
# Verifica policy defaultinput_policy=$(iptables -L INPUT -n | head -1 | grep -o "policy [A-Z]*" | awk '{print $2}')forward_policy=$(iptables -L FORWARD -n | head -1 | grep -o "policy [A-Z]*" | awk '{print $2}')
# Stato in base a regole attive
if [[ $total_rules -eq 0 ]]; then
    status=2    status_text="CRITICAL - Nessuna regola attiva"
elif [[ $total_rules -lt 5 ]]; then
    status=1    status_text="WARNING - Poche regole attive"
else    status=0    status_text="OK"
fi
echo "$status Firewall_Rules - INPUT:$input_rules FORWARD:$forward_rules OUTPUT:$output_rules NAT:$nat_rules - Policy: INPUT=$input_policy FORWARD=$forward_policy - $status_text | input=$input_rules forward=$forward_rules output=$output_rules nat=$nat_rules total=$total_rules"
