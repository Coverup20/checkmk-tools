#!/bin/bash
#
# Script per diagnosticare la connessione FRP → CheckMK Agent
#

echo "=== DIAGNOSTICA CONNESSIONE FRP ==="
echo ""

# 1. Verifica che frps sia in ascolto su porta 6045
echo "1. Verifica che FRP server sia in ascolto su porta 6045..."
netstat -tlnp 2>/dev/null | grep ":6045" || ss -tlnp 2>/dev/null | grep ":6045"
if [ $? -eq 0 ]; then
    echo "   ✓ FRP server in ascolto su porta 6045"
else
    echo "   ✗ FRP server NON in ascolto su porta 6045!"
    echo ""
    echo "Verifica il servizio frps:"
    systemctl status frps 2>/dev/null || service frps status 2>/dev/null
fi
echo ""

# 2. Test connessione diretta a localhost:6045
echo "2. Test connessione diretta a localhost:6045..."
timeout 5 bash -c 'echo "<<<check_mk>>>" | nc localhost 6045' > /tmp/frp_test.txt 2>&1
if [ -s /tmp/frp_test.txt ]; then
    echo "   ✓ Connessione riuscita! Output ricevuto:"
    head -10 /tmp/frp_test.txt
else
    echo "   ✗ Nessun output ricevuto da localhost:6045"
    echo "   Errore: $(cat /tmp/frp_test.txt 2>/dev/null || echo 'Timeout o connessione rifiutata')"
fi
echo ""

# 3. Verifica configurazione CheckMK per WS2022AD
echo "3. Verifica configurazione CheckMK per WS2022AD..."
su - monitoring -c "cmk -D WS2022AD" 2>&1 | grep -E "(IP|Port|Address|datasource_programs)" | head -20
echo ""

# 4. Test con cmk -d
echo "4. Test connessione CheckMK all'host..."
su - monitoring -c "cmk -d WS2022AD 2>&1" | head -30
echo ""

# 5. Verifica regole Agent port
echo "5. Verifica regole 'Agent port' configurate..."
su - monitoring -c "cd /omd/sites/monitoring/etc/check_mk/conf.d && grep -r 'tcp_connect_timeout\|agent.*port' ." 2>/dev/null
echo ""

# 6. Verifica frpc su WS2022AD sia connesso
echo "6. Verifica stato client FRP su WS2022AD..."
echo "   (Devi verificare manualmente su WS2022AD che frpc sia running)"
echo "   Comandi da eseguire su WS2022AD:"
echo "     Get-Service frpc"
echo "     netstat -ano | findstr 6556"
echo ""

echo "=== FINE DIAGNOSTICA ==="
