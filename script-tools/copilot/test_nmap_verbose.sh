#!/bin/bash
echo "=== AS ROOT - verbose ==="
nmap -sn -n --reason 192.168.32.144 2>&1

echo ""
echo "=== AS MONITORING - verbose ==="
su - monitoring -c "nmap -sn -n --reason 192.168.32.144 2>&1"
