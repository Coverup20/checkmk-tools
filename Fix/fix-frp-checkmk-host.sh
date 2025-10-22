#!/bin/bash
#
# Script per configurare un host CheckMK che usa FRP proxy
# Questo script configura l'host per connettersi tramite localhost:PORT invece che IP:6556
#

SITE="monitoring"
HOST="WS2022AD"
FRP_PORT="6045"

echo "=== Configurazione Host CheckMK con FRP Proxy ==="
echo ""
echo "Host: $HOST"
echo "Proxy FRP: localhost:$FRP_PORT"
echo ""

# 1. Verifica configurazione attuale
echo "1. Configurazione attuale dell'host..."
echo ""
su - $SITE -c "cmk -d $HOST" 2>&1 | head -20
echo ""

# 2. Mostra come configurare l'host nella GUI
echo "=== ISTRUZIONI PER LA GUI DI CHECKMK ==="
echo ""
echo "1. Vai su: Setup → Hosts → Hosts"
echo "2. Cerca e clicca su: $HOST"
echo "3. Nella sezione 'Monitoring agents':"
echo "   - API integrations and monitoring agents: CheckMK agent"
echo "   - CheckMK agent connection mode: Direct connection"
echo ""
echo "4. Espandi 'Connection Settings' e configura:"
echo "   ┌─────────────────────────────────────────┐"
echo "   │ Host name:  127.0.0.1                   │"
echo "   │ Port:       6045                        │"
echo "   │                                         │"
echo "   │ [ ] Use encryption                      │"
echo "   │ [ ] Disable TLS certificate validation │"
echo "   └─────────────────────────────────────────┘"
echo ""
echo "5. Salva e vai su 'Activate changes'"
echo ""

# 3. Alternativa: configurazione tramite REST API (se hai le credenziali)
echo "=== ALTERNATIVA: Configurazione tramite REST API ==="
echo ""
echo "Se hai un automation user configurato, puoi usare questo comando:"
echo ""
cat << 'EOF'
# Sostituisci USER e PASSWORD con le tue credenziali automation
curl -X PUT \
  "http://localhost/monitoring/check_mk/api/1.0/objects/host_config/$HOST" \
  -H "Authorization: Bearer USER PASSWORD" \
  -H "Content-Type: application/json" \
  -d '{
    "attributes": {
      "ipaddress": "127.0.0.1",
      "tag_agent": "cmk-agent",
      "tag_snmp_ds": "no-snmp"
    },
    "update_attributes": {
      "ipaddress": "127.0.0.1"
    }
  }'
EOF
echo ""

# 4. Test dopo la configurazione
echo "=== TEST DOPO LA CONFIGURAZIONE ==="
echo ""
echo "Dopo aver salvato le modifiche, esegui:"
echo ""
echo "  su - $SITE -c 'cmk -d $HOST'"
echo ""
echo "Dovresti vedere l'output dell'agent invece di 'Connection refused'"
echo ""
echo "Poi esegui il service discovery:"
echo ""
echo "  su - $SITE -c 'cmk -IIv $HOST'"
echo ""

# 5. Verifica che FRP sia in ascolto
echo "=== VERIFICA FRP PROXY ==="
echo ""
echo "Verifico che FRP sia in ascolto sulla porta $FRP_PORT..."
netstat -tlnp 2>/dev/null | grep ":$FRP_PORT" || ss -tlnp 2>/dev/null | grep ":$FRP_PORT"
echo ""

# 6. Test diretto alla porta FRP
echo "Test connessione diretta a localhost:$FRP_PORT..."
timeout 3 bash -c "echo '<<<check_mk>>>' | nc localhost $FRP_PORT" 2>&1 | head -5
echo ""
echo "Se vedi output dall'agent, FRP funziona correttamente!"
echo ""
