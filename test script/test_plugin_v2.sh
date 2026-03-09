#!/bin/bash
echo "=== Test plugin su 192.168.32.144 (host presente in nmap) ==="
su - monitoring -c "/omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive -H 192.168.32.144"
echo "Exit: $?"

echo ""
echo "=== Test plugin su host sicuramente DOWN ==="
su - monitoring -c "/omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive -H 192.168.32.99"
echo "Exit: $?"
