#!/bin/bash
echo "=== AS ROOT ==="
nmap -sn -n --reason 192.168.32.144 2>/dev/null | grep -E "Host is|scan report|Reason"

echo ""
echo "=== AS MONITORING ==="
su - monitoring -c "nmap -sn -n --reason 192.168.32.144 2>/dev/null | grep -E 'Host is|scan report|Reason'"
