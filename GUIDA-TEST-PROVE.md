# 🧪 Guida Test - Integrazione CheckMK → Ydea

## 📋 Prerequisiti per i Test

Prima di iniziare le prove, assicurati di avere:
- ✅ Accesso SSH al server CheckMK
- ✅ Credenziali Ydea (ID e API Key)
- ✅ Permessi sudo sul server
- ✅ Repository appena pushato su GitHub

---

## 🚀 FASE 1: Deploy su Server CheckMK

### **1.1 Connessione al Server**
```bash
ssh user@checkmk-server.nethlab.it
```

### **1.2 Clone Repository**
```bash
cd /opt
sudo git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools
```

### **1.3 Verifica File Scaricati**
```bash
ls -la Ydea-Toolkit/
ls -la script-notify-checkmk/ydea_realip
```

---

## 🔧 FASE 2: Installazione

### **2.1 Esegui Installer Automatico**
```bash
cd /opt/checkmk-tools
sudo chmod +x Ydea-Toolkit/install-ydea-checkmk-integration.sh
sudo ./Ydea-Toolkit/install-ydea-checkmk-integration.sh
```

L'installer farà:
- ✅ Verifica prerequisiti (CheckMK, dipendenze)
- ✅ Copia script nelle directory corrette
- ✅ Setup file .env
- ✅ Crea cache files
- ✅ Configura cron job
- ✅ Test connessione Ydea

### **2.2 Configura Credenziali Ydea**
```bash
sudo nano /opt/ydea-toolkit/.env
```

**Modifica queste righe:**
```bash
export YDEA_ID="IL_TUO_ID_AZIENDA"
export YDEA_API_KEY="LA_TUA_API_KEY_LUNGA"
export YDEA_ALERT_EMAIL="massimo.palazzetti@nethesis.it"
```

Salva: `Ctrl+O`, `Enter`, `Ctrl+X`

---

## 🧪 FASE 3: Test Base

### **3.1 Test Login Ydea**
```bash
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
```

**Output atteso:**
```
✅ Login effettuato (token valido ~1h)
```

❌ **Se fallisce:** Verifica credenziali in `.env`

### **3.2 Test Lista Ticket Esistenti**
```bash
./ydea-toolkit.sh list 5
```

Dovresti vedere gli ultimi 5 ticket in formato JSON.

### **3.3 Esegui Suite Test Completa**
```bash
cd /opt/ydea-toolkit
sudo chmod +x test-ydea-integration.sh
sudo ./test-ydea-integration.sh
```

Questo eseguirà 10+ test automatici:
- ✅ Verifica file e permessi
- ✅ Configurazione .env
- ✅ Connessione Ydea
- ✅ Cache files
- ✅ Dipendenze sistema
- ✅ Cron job
- ✅ (Opzionale) Test simulazione notifica

**Tutti i test devono passare prima di procedere!**

---

## 🎯 FASE 4: Test Notifica Manuale

### **4.1 Test Creazione Ticket da Alert CRITICAL**

Diventa utente CheckMK:
```bash
sudo su - monitoring
```

Simula alert SERVICE CRITICAL:
```bash
export NOTIFY_WHAT="SERVICE"
export NOTIFY_HOSTNAME="test-server-demo"
export NOTIFY_HOSTADDRESS="192.168.99.99"
export NOTIFY_SERVICEDESC="Test CPU Load"
export NOTIFY_SERVICESTATE="CRIT"
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_SERVICEOUTPUT="CPU load at 98% - Critical threshold exceeded"
export NOTIFY_SERVICESTATETYPE="HARD"

/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Output atteso:**
```
[2025-11-13 HH:MM:SS] SERVICE Alert: test-server-demo (192.168.99.99) - Test CPU Load | OK -> CRIT
[2025-11-13 HH:MM:SS] Nuovo problema CRITICAL: creazione ticket
[2025-11-13 HH:MM:SS] ✅ Ticket creato: #12345 per 192.168.99.99:Test CPU Load
```

### **4.2 Verifica Ticket Creato**

**Opzione A - Via API:**
```bash
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh list 5 | jq '.data[] | select(.title | contains("192.168.99.99"))'
```

**Opzione B - Verifica Cache:**
```bash
cat /tmp/ydea_checkmk_tickets.json | jq '."192.168.99.99:Test CPU Load"'
```

Dovresti vedere:
```json
{
  "ticket_id": "12345",
  "state": "CRIT",
  "created_at": "1699887000",
  "last_update": "1699887000"
}
```

**Opzione C - Web Ydea:**
Vai su https://my.ydea.cloud e verifica che il ticket sia presente.

### **4.3 Test Cambio Stato (Nota Privata)**

Simula rientro allarme (CRIT → OK):
```bash
export NOTIFY_SERVICESTATE="OK"
export NOTIFY_LASTSERVICESTATE="CRIT"
export NOTIFY_SERVICEOUTPUT="CPU load normalized at 35%"

/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Output atteso:**
```
[2025-11-13 HH:MM:SS] SERVICE Alert: test-server-demo (192.168.99.99) - Test CPU Load | CRIT -> OK
[2025-11-13 HH:MM:SS] Ticket esistente trovato: #12345
[2025-11-13 HH:MM:SS] Nota privata aggiunta al ticket #12345
```

**Verifica su Ydea Web:**
- Apri ticket #12345
- Controlla che ci sia una nota privata tipo:
  ```
  🔄 [13/11/25 14:32] 🔴CRIT→🟢OK | ✅ Allarme rientrato | Output: CPU load normalized at 35%
  ```

### **4.4 Test Flapping**

Simula 5 cambi stato rapidi:
```bash
# Cambio 1: OK → CRIT
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_SERVICESTATE="CRIT"
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip

# Cambio 2: CRIT → OK
export NOTIFY_LASTSERVICESTATE="CRIT"
export NOTIFY_SERVICESTATE="OK"
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip

# Cambio 3: OK → CRIT
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_SERVICESTATE="CRIT"
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip

# Cambio 4: CRIT → WARN
export NOTIFY_LASTSERVICESTATE="CRIT"
export NOTIFY_SERVICESTATE="WARN"
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip

# Cambio 5: WARN → CRIT
export NOTIFY_LASTSERVICESTATE="WARN"
export NOTIFY_SERVICESTATE="CRIT"
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Output atteso al 5° cambio:**
```
[...] ⚠️ FLAPPING (5 cambi in 10min)
```

**Verifica cache flapping:**
```bash
cat /tmp/ydea_checkmk_flapping.json | jq '."192.168.99.99:Test CPU Load"'
```

---

## 💊 FASE 5: Test Health Monitor

### **5.1 Test Manuale Health Monitor**
```bash
exit  # Esci da utente monitoring
sudo /opt/ydea-toolkit/ydea-health-monitor.sh
```

**Output atteso (se Ydea UP):**
```
[2025-11-13 HH:MM:SS] Controllo disponibilità Ydea API...
[2025-11-13 HH:MM:SS] ✅ Ydea API raggiungibile
```

### **5.2 Test Ydea Down (Simulazione)**

**Opzione A - Credenziali Errate Temporanee:**
```bash
sudo nano /opt/ydea-toolkit/.env
# Cambia temporaneamente API_KEY in valore errato
export YDEA_API_KEY="FAKE_KEY_FOR_TEST"
# Salva

sudo /opt/ydea-toolkit/ydea-health-monitor.sh
```

**Output atteso:**
```
[...] ❌ Ydea API non raggiungibile (tentativi falliti: 1/3)
```

Esegui altre 2 volte per raggiungere soglia:
```bash
sudo /opt/ydea-toolkit/ydea-health-monitor.sh  # 2/3
sudo /opt/ydea-toolkit/ydea-health-monitor.sh  # 3/3 → invia email!
```

**Controlla email:** Massimo dovrebbe ricevere email con:
- Subject: `🚨 [ALERT] Ydea API - Servizio Non Raggiungibile`
- Corpo HTML con dettagli

**IMPORTANTE:** Ripristina credenziali corrette:
```bash
sudo nano /opt/ydea-toolkit/.env
# Rimetti API_KEY corretta
```

### **5.3 Verifica Cron Job**
```bash
crontab -l | grep ydea
```

Dovresti vedere:
```
*/15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1
```

**Monitora log real-time:**
```bash
sudo tail -f /var/log/ydea_health.log
```

Aspetta 15 minuti e verifica che venga eseguito automaticamente.

---

## 🎛️ FASE 6: Configurazione CheckMK GUI

### **6.1 Crea Notification Rule**

1. Accedi a CheckMK: `https://monitor.nethlab.it/monitoring`

2. **Setup → Notifications**

3. **Add rule**

4. **Configurazione:**
   - **Description:** `Ydea Ticketing - Alert Critici`
   - **Notification Method:** Seleziona `ydea_realip`
   
5. **Conditions:**
   - **Match service states:** CRIT, WARN (opzionale)
   - **Match host states:** DOWN
   - **Restrict to hosts:** (opzionale, filtra per label/tag)

6. **Contact Selection:**
   - Seleziona utenti/gruppi che devono ricevere ticket

7. **Save**

8. **Activate Changes** (pulsante in alto)

### **6.2 Test con Alert Reale**

Crea un alert di test su un servizio reale:

**Opzione A - Alert Disco Pieno (sicuro):**
```bash
# Su un host monitorato, riempi temporaneamente /tmp
sudo dd if=/dev/zero of=/tmp/testfile bs=1M count=1000
```

Aspetta che CheckMK rilevi il problema e verifica:
1. Log notifiche: `tail -f /omd/sites/monitoring/var/log/notify.log`
2. Ticket creato su Ydea

**RICORDA:** Pulisci dopo il test:
```bash
sudo rm /tmp/testfile
```

---

## 📊 FASE 7: Monitoraggio e Verifica

### **7.1 Log da Monitorare**

**Log notifiche CheckMK:**
```bash
sudo tail -f /omd/sites/monitoring/var/log/notify.log | grep ydea
```

**Log health monitor:**
```bash
sudo tail -f /var/log/ydea_health.log
```

**Cache ticket:**
```bash
watch -n 5 'cat /tmp/ydea_checkmk_tickets.json | jq "."'
```

### **7.2 Comandi Utili Debug**

```bash
# Conta ticket in cache
cat /tmp/ydea_checkmk_tickets.json | jq 'length'

# Lista tutti i servizi tracciati
cat /tmp/ydea_checkmk_tickets.json | jq 'keys'

# Cerca ticket specifico
cat /tmp/ydea_checkmk_tickets.json | jq '."192.168.99.99:Test CPU Load"'

# Verifica ultimo stato health monitor
cat /tmp/ydea_health_state.json | jq '.'

# Ultimi 50 eventi flapping
cat /tmp/ydea_checkmk_flapping.json | jq '.'
```

---

## ✅ Checklist Completamento Test

- [ ] Installer eseguito con successo
- [ ] Credenziali Ydea configurate
- [ ] Test login Ydea OK
- [ ] Suite test automatici passata (10/10)
- [ ] Test notifica manuale → ticket creato
- [ ] Ticket visibile su Ydea web
- [ ] Test cambio stato → nota privata aggiunta
- [ ] Nota privata visibile su Ydea
- [ ] Test flapping → rilevato correttamente
- [ ] Health monitor eseguito manualmente
- [ ] Test simulazione Ydea down → email ricevuta
- [ ] Cron job configurato e funzionante
- [ ] Notification rule CheckMK configurata
- [ ] Test con alert reale CheckMK → ticket OK
- [ ] Log monitoraggio funzionanti

---

## 🐛 Troubleshooting Rapido

### **Problema: Script non eseguibile**
```bash
sudo chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
sudo chmod +x /opt/ydea-toolkit/ydea-health-monitor.sh
```

### **Problema: Cache corrotta**
```bash
sudo rm /tmp/ydea_checkmk_tickets.json
echo '{}' | sudo tee /tmp/ydea_checkmk_tickets.json
sudo chmod 666 /tmp/ydea_checkmk_tickets.json
```

### **Problema: Login Ydea fallisce**
```bash
# Verifica credenziali
cat /opt/ydea-toolkit/.env | grep YDEA_

# Test con debug
cd /opt/ydea-toolkit
export YDEA_DEBUG=1
./ydea-toolkit.sh login
```

### **Problema: Email non arriva**
```bash
# Test sendmail
echo "Test" | mail -s "Test Ydea" massimo.palazzetti@nethesis.it

# Verifica log mail
tail -f /var/log/mail.log
```

---

## 📚 Documentazione Completa

- **Setup dettagliato:** `/opt/ydea-toolkit/README-CHECKMK-INTEGRATION.md`
- **Comandi rapidi:** `/opt/ydea-toolkit/QUICK-REFERENCE.md`
- **Riepilogo progetto:** `/opt/checkmk-tools/INTEGRAZIONE-CHECKMK-YDEA-SUMMARY.md`

---

## 🎉 Completamento

Una volta completati tutti i test, il sistema è **PRONTO PER LA PRODUZIONE**! 🚀

Monitora i primi giorni per verificare:
- Ticket creati correttamente
- Note private aggiunte
- Email health monitor funzionanti
- Nessun duplicato
- Performance cache OK

**Buone prove!** 🧪✨
