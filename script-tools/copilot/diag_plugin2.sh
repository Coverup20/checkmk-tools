#!/bin/bash
echo "=== Test sudo senza TTY (come Nagios) ==="
su - monitoring -c "sudo -n /usr/bin/nmap -sn -n 192.168.32.144 2>&1"
echo "EXIT: $?"

echo ""
echo "=== Log Nagios per check_windows_alive ==="
grep -r "check_windows_alive" /omd/sites/monitoring/var/log/ 2>/dev/null | tail -5

echo ""
echo "=== Ultimo output del check raw ==="
su - monitoring -c "python3 -c \"
import socket
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/omd/sites/monitoring/tmp/run/live')
q = b'GET hosts\nFilter: name = WKS-11settembre.ad.studiopaci.info\nColumns: name state plugin_output check_command last_check\nOutputFormat: csv\nSeparator: 59\n\n'
sock.sendall(q)
sock.shutdown(socket.SHUT_WR)
d = b''
while True:
    c = sock.recv(4096)
    if not c: break
    d += c
sock.close()
print(d.decode())
\""
