#!/bin/bash
echo "monitoring ALL=(root) NOPASSWD: /usr/bin/nmap" > /etc/sudoers.d/monitoring-nmap
chmod 440 /etc/sudoers.d/monitoring-nmap
visudo -c
echo "SUDOERS_OK"
echo "=== Test sudo nmap as monitoring ==="
su - monitoring -c "sudo nmap -sn -n --reason 192.168.32.144 2>&1"
