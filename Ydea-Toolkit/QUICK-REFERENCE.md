# 🚀 Quick Reference - Integrazione CheckMK → Ydea

## 📦 Installazione Rapida

```bash
# Clone repository
cd /tmp
git clone https://github.com/Coverup20/checkmk-tools.git

# Esegui installer
cd checkmk-tools
sudo chmod +x Ydea-Toolkit/install-ydea-checkmk-integration.sh
sudo ./Ydea-Toolkit/install-ydea-checkmk-integration.sh

# Configura credenziali
sudo nano /opt/ydea-toolkit/.env
# → Inserisci YDEA_ID e YDEA_API_KEY

# Test
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
```

---

## 🔧 Comandi Utili

### **Test Notifica Manuale**
```bash
# Simula SERVICE CRITICAL
export NOTIFY_WHAT="SERVICE"
export NOTIFY_HOSTNAME="server-test"
export NOTIFY_HOSTADDRESS="192.168.1.50"
export NOTIFY_SERVICEDESC="Disk /var"
export NOTIFY_SERVICESTATE="CRIT"
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_SERVICEOUTPUT="Disk usage 95%"
export NOTIFY_SERVICESTATETYPE="HARD"

sudo su - monitoring -c '/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip'
```

### **Verifica Cache Ticket**
```bash
# Mostra tutti i ticket attivi
cat /tmp/ydea_checkmk_tickets.json | jq .

# Count ticket
cat /tmp/ydea_checkmk_tickets.json | jq 'length'

# Cerca ticket specifico
cat /tmp/ydea_checkmk_tickets.json | jq '."192.168.1.50:Disk /var"'
```

### **Verifica Flapping**
```bash
# Mostra eventi flapping
cat /tmp/ydea_checkmk_flapping.json | jq .

# Count cambi stato per servizio
cat /tmp/ydea_checkmk_flapping.json | jq '.["192.168.1.50:CPU"] | length'
```

### **Monitor Health Check**
```bash
# Esegui manualmente
/opt/ydea-toolkit/ydea-health-monitor.sh

# Verifica stato
cat /tmp/ydea_health_state.json | jq .

# Log real-time
tail -f /var/log/ydea_health.log
```

### **Pulizia Cache**
```bash
# Reset cache ticket
sudo rm /tmp/ydea_checkmk_tickets.json
echo '{}' | sudo tee /tmp/ydea_checkmk_tickets.json

# Reset cache flapping
sudo rm /tmp/ydea_checkmk_flapping.json
echo '{}' | sudo tee /tmp/ydea_checkmk_flapping.json

# Reset health state
sudo rm /tmp/ydea_health_state.json
```

---

## 📊 Log e Debug

### **Log CheckMK Notifiche**
```bash
# Tutte le notifiche
tail -f /omd/sites/monitoring/var/log/notify.log

# Solo Ydea
tail -f /omd/sites/monitoring/var/log/notify.log | grep ydea

# Filtra per host
tail -f /omd/sites/monitoring/var/log/notify.log | grep "192.168.1.50"
```

### **Debug Mode**
```bash
# Abilita debug in .env
echo "export DEBUG_YDEA=1" | sudo tee -a /opt/ydea-toolkit/.env

# Testa con debug
export DEBUG_YDEA=1
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

### **Log Health Monitor**
```bash
# Ultimi 50 controlli
tail -50 /var/log/ydea_health.log

# Solo errori
grep "ERROR" /var/log/ydea_health.log

# Ultimi fallimenti
grep "non raggiungibile" /var/log/ydea_health.log | tail -10
```

---

## 🎯 Configurazione CheckMK GUI

### **Notification Rule - Base**
```
Setup → Notifications → Add rule

Nome: "Ydea Ticketing"
Notification Method: ydea_realip
Conditions:
  - Match service states: CRIT
  - Match host states: DOWN
Contact selection: All users
```

### **Notification Rule - Avanzata (solo servizi critici)**
```
Setup → Notifications → Add rule

Nome: "Ydea Ticketing - Critici"
Description: "Ticket automatici solo per alert critici con IP reale"

Conditions:
  - Match host labels: real_ip (se usi label FRP)
  - Match service states: CRIT
  - Match host states: DOWN
  - Restrict to certain services: (opzionale)
      Pattern: CPU|Memory|Disk|Network
      
Notification Method: 
  Plugin: ydea_realip
  
Contact Selection:
  All users (o specifici gruppi)
```

---

## 🔍 Troubleshooting Veloce

### **Ticket non creato**
```bash
# 1. Verifica permessi script
ls -la /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
# Deve essere: -rwxr-xr-x

# 2. Test login Ydea
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login

# 3. Verifica notification rule in CheckMK
# → Setup → Notifications → Check se rule è attiva

# 4. Check log
tail -20 /omd/sites/monitoring/var/log/notify.log
```

### **Email Ydea down non arriva**
```bash
# 1. Test sendmail
echo "Test" | mail -s "Test Ydea" massimo.palazzetti@nethesis.it

# 2. Verifica script email
ls -la /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down

# 3. Test health monitor manualmente
/opt/ydea-toolkit/ydea-health-monitor.sh

# 4. Check cron
crontab -l | grep ydea
```

### **Troppi ticket duplicati**
```bash
# Verifica cache integra
cat /tmp/ydea_checkmk_tickets.json | jq . | head -20

# Se corrotta, ripulisci
sudo rm /tmp/ydea_checkmk_tickets.json
echo '{}' | sudo tee /tmp/ydea_checkmk_tickets.json
sudo chmod 666 /tmp/ydea_checkmk_tickets.json
```

---

## 📝 Esempi Configurazione

### **Cron - Diverse Frequenze**
```bash
# Ogni 5 minuti (più frequente)
*/5 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1

# Ogni 15 minuti (default)
*/15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1

# Ogni 30 minuti (meno frequente)
*/30 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1

# Solo orari lavorativi (8-18, lun-ven)
*/15 8-18 * * 1-5 /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1
```

### **Configurazione .env Completa**
```bash
# Credenziali Ydea
export YDEA_ID="la_tua_company_id"
export YDEA_API_KEY="la_tua_api_key_lunga"

# URL e percorsi
export YDEA_BASE_URL="https://my.ydea.cloud/app_api_v2"
export YDEA_TOKEN_FILE="/tmp/.ydea_token.json"

# Health monitoring
export YDEA_ALERT_EMAIL="massimo.palazzetti@nethesis.it"
export YDEA_FAILURE_THRESHOLD=3  # Fallimenti prima di notificare

# Debug (0=off, 1=on)
export DEBUG_YDEA=0
export YDEA_DEBUG=0
```

---

## 🔄 Manutenzione Programmata

### **Script Pulizia Settimanale**
```bash
#!/bin/bash
# /opt/ydea-toolkit/cleanup-cache.sh

# Rimuovi ticket cache > 30 giorni
NOW=$(date +%s)
MAX_AGE=$((30*24*3600))

jq --arg now "$NOW" --arg max "$MAX_AGE" '
  to_entries | 
  map(select(($now|tonumber) - (.value.created_at|tonumber) < ($max|tonumber))) | 
  from_entries
' /tmp/ydea_checkmk_tickets.json > /tmp/ydea_checkmk_tickets.json.tmp

mv /tmp/ydea_checkmk_tickets.json.tmp /tmp/ydea_checkmk_tickets.json

# Ruota log
if [ -f /var/log/ydea_health.log ] && [ $(stat -f%z /var/log/ydea_health.log) -gt 10485760 ]; then
  mv /var/log/ydea_health.log /var/log/ydea_health.log.old
  touch /var/log/ydea_health.log
fi

echo "Pulizia completata: $(date)"
```

**Aggiungi a cron:**
```bash
# Ogni domenica alle 3am
0 3 * * 0 /opt/ydea-toolkit/cleanup-cache.sh >> /var/log/ydea_cleanup.log 2>&1
```

---

## 📞 Contatti Rapidi

**Documentazione completa:** `/opt/ydea-toolkit/README-CHECKMK-INTEGRATION.md`

**File importanti:**
- Config: `/opt/ydea-toolkit/.env`
- Ticket cache: `/tmp/ydea_checkmk_tickets.json`
- Flapping cache: `/tmp/ydea_checkmk_flapping.json`
- Health state: `/tmp/ydea_health_state.json`
- Log notifiche: `/omd/sites/monitoring/var/log/notify.log`
- Log health: `/var/log/ydea_health.log`

**Script principali:**
- Notifica: `/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip`
- Health monitor: `/opt/ydea-toolkit/ydea-health-monitor.sh`
- Ydea toolkit: `/opt/ydea-toolkit/ydea-toolkit.sh`

---

**Aggiornato:** 13 Novembre 2025  
**Versione:** 1.0.0
