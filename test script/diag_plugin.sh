#!/bin/bash
echo "=== Test plugin come viene chiamato da CheckMK (utente monitoring, path completo) ==="
su - monitoring -c "/omd/sites/monitoring/local/lib/nagios/plugins/check_windows_alive -H 192.168.32.144"
echo "EXIT: $?"

echo ""
echo "=== Verifica sudo funziona come monitoring ==="
su - monitoring -c "sudo /usr/bin/nmap -sn -n 192.168.32.144 2>&1 | grep -E 'Host is|scan report'"
echo "EXIT nmap: $?"

echo ""
echo "=== Verifica check_nagios_alive chiama sudo correttamente ==="
su - monitoring -c "which sudo && sudo -l 2>&1 | grep nmap"
