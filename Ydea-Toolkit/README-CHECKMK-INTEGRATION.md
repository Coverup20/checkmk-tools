# 🎫 Integrazione CheckMK → Ydea Ticketing

Sistema completo per la gestione automatica di ticket Ydea da alert CheckMK con monitoraggio bidirezionale della disponibilità del servizio.

## 📋 Indice

- [Panoramica](#panoramica)
- [Componenti](#componenti)
- [Installazione](#installazione)
- [Configurazione CheckMK](#configurazione-checkmk)
- [Configurazione Cron](#configurazione-cron)
- [Test e Verifica](#test-e-verifica)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)

---

## 🎯 Panoramica

Questo sistema automatizza la gestione dei ticket Ydea per alert CheckMK con le seguenti funzionalità:

### **Alert CheckMK → Ydea Ticket**
- ✅ **Nuovo alert CRITICAL/DOWN** → Crea ticket automatico
- ✅ **Cambio stato** → Aggiunge nota privata (non visibile al cliente)
- ✅ **Rilevamento flapping** → Alert se servizio cambia stato frequentemente
- ✅ **Prevenzione duplicati** → Cache intelligente per evitare ticket multipli
- ✅ **Note sintetiche** → Tracking completo dei cambi stato

### **Monitoraggio Ydea**
- ✅ **Check periodico** (ogni 15 min) della disponibilità API Ydea
- ✅ **Notifica email** se Ydea non è raggiungibile
- ✅ **Recovery notification** quando servizio torna online

---

## 📦 Componenti

### 1. **`ydea_realip`** (in `script-notify-checkmk/`)
Script di notifica CheckMK che gestisce alert e crea/aggiorna ticket Ydea.

**Funzionalità:**
- Riceve variabili ambiente da CheckMK (`NOTIFY_*`)
- Identifica ticket univoco per IP/Hostname + Servizio
- Crea ticket su alert CRITICAL/DOWN
- Aggiunge note private su cambio stato
- Rileva flapping (5+ cambi in 10 minuti)
- Cache: `/tmp/ydea_checkmk_tickets.json`

### 2. **`ydea-health-monitor.sh`** (in `Ydea-Toolkit/`)
Monitor periodico della disponibilità Ydea API.

**Funzionalità:**
- Testa login Ydea ogni 15 minuti (via cron)
- Soglia 3 fallimenti prima di notificare
- Email alert se Ydea down
- Email recovery quando torna up
- State: `/tmp/ydea_health_state.json`

### 3. **`mail_ydea_down`** (in `script-notify-checkmk/`)
Script notifica email per Ydea offline.

**Funzionalità:**
- Email HTML professionale con dettagli
- Informazioni su impatto e azioni
- Usato da `ydea-health-monitor.sh`

---

## 🚀 Installazione

### **Prerequisiti**

1. **CheckMK** già installato e funzionante
2. **Ydea Toolkit** configurato in `/opt/ydea-toolkit/`
3. **Credenziali Ydea** (ID e API Key)

### **Passo 1: Copia Script**

```bash
# Dal repository su server CheckMK
cd /path/to/checkmk-tools

# Copia script notifica CheckMK
sudo cp script-notify-checkmk/ydea_realip \
   /omd/sites/monitoring/local/share/check_mk/notifications/

sudo cp script-notify-checkmk/mail_ydea_down \
   /omd/sites/monitoring/local/share/check_mk/notifications/

# Rendi eseguibili
sudo chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
sudo chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down

# Copia health monitor
sudo cp Ydea-Toolkit/ydea-health-monitor.sh /opt/ydea-toolkit/
sudo chmod +x /opt/ydea-toolkit/ydea-health-monitor.sh
```

### **Passo 2: Configura Credenziali**

```bash
# Modifica .env con le tue credenziali
sudo nano /opt/ydea-toolkit/.env
```

Inserisci:
```bash
export YDEA_ID="il_tuo_id_azienda"
export YDEA_API_KEY="la_tua_api_key"
export YDEA_ALERT_EMAIL="massimo.palazzetti@nethesis.it"
```

### **Passo 3: Test Iniziale**

```bash
# Test login Ydea
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
# Output atteso: ✅ Login effettuato (token valido ~1h)

# Test health monitor
./ydea-health-monitor.sh
# Output atteso: [timestamp] ✅ Ydea API raggiungibile
```

---

## ⚙️ Configurazione CheckMK

### **Setup Notifica Rule**

1. **Accedi a CheckMK** → **Setup** → **Notifications**

2. **Crea nuova regola**: "Ydea Ticketing"

3. **Configurazione:**

   **Contact Selection:**
   - Specificare utenti/gruppi che devono ricevere ticket

   **Conditions:**
   - **Match host/service labels:** `real_ip` (opzionale, se usi label)
   - **Match event type:** State changes
   - **Restrict to certain states:**
     - Host: DOWN
     - Service: CRITICAL, WARNING (opzionale)

   **Notification Method:**
   - Seleziona: **Custom notification script**
   - Script name: `ydea_realip`

4. **Salva** e **Activate Changes**

### **Esempio Configurazione Avanzata**

```python
# In WATO Rules → Notifications
{
  "description": "Ydea Ticketing - Alert Critici",
  "disabled": False,
  "comment": "Crea ticket Ydea per alert critici con gestione automatica note",
  
  # Match conditions
  "match_servicestate": ["CRIT", "WARN"],
  "match_hoststate": ["DOWN"],
  "match_event": "statechange",
  
  # Notification
  "notify_plugin": ("ydea_realip", {}),
  
  # Contact selection
  "contact_all": False,
  "contact_users": ["admin"],
}
```

---

## ⏰ Configurazione Cron

### **Setup Cron Job per Health Monitor**

```bash
# Edita crontab del sito CheckMK
sudo su - monitoring
crontab -e
```

Aggiungi:
```cron
# Ydea Health Monitor - ogni 15 minuti
*/15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /tmp/ydea_health.log 2>&1
```

Oppure come utente root:
```bash
sudo crontab -e
```

```cron
*/15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh >> /var/log/ydea_health.log 2>&1
```

### **Verifica Cron**

```bash
# Lista cron jobs
crontab -l

# Monitora log
tail -f /tmp/ydea_health.log
```

---

## 🧪 Test e Verifica

### **Test 1: Notifica Manuale CheckMK**

```bash
# Simula notifica SERVICE CRITICAL
sudo su - monitoring

export NOTIFY_WHAT="SERVICE"
export NOTIFY_HOSTNAME="test-server"
export NOTIFY_HOSTADDRESS="192.168.1.100"
export NOTIFY_SERVICEDESC="CPU Load"
export NOTIFY_SERVICESTATE="CRIT"
export NOTIFY_LASTSERVICESTATE="OK"
export NOTIFY_SERVICEOUTPUT="CPU load at 95%"
export NOTIFY_SERVICESTATETYPE="HARD"

/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Output atteso:**
```
[2025-11-13 14:30:00] SERVICE Alert: test-server (192.168.1.100) - CPU Load | OK -> CRIT
[2025-11-13 14:30:01] ✅ Ticket creato: #12345 per 192.168.1.100:CPU Load
```

### **Test 2: Cambio Stato (Nota Privata)**

```bash
# Simula rientro alert (CRIT → OK)
export NOTIFY_SERVICESTATE="OK"
export NOTIFY_LASTSERVICESTATE="CRIT"
export NOTIFY_SERVICEOUTPUT="CPU load normal at 35%"

/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
```

**Output atteso:**
```
[2025-11-13 14:35:00] SERVICE Alert: test-server (192.168.1.100) - CPU Load | CRIT -> OK
[2025-11-13 14:35:01] Ticket esistente trovato: #12345
[2025-11-13 14:35:02] Nota privata aggiunta al ticket #12345
```

### **Test 3: Health Monitor**

```bash
# Esegui manualmente
/opt/ydea-toolkit/ydea-health-monitor.sh

# Verifica stato
cat /tmp/ydea_health_state.json
```

### **Test 4: Verifica Cache**

```bash
# Mostra ticket in cache
cat /tmp/ydea_checkmk_tickets.json | jq .

# Esempio output:
{
  "192.168.1.100:CPU Load": {
    "ticket_id": "12345",
    "state": "OK",
    "created_at": "1699887000",
    "last_update": "1699887300"
  }
}
```

---

## 🔧 Troubleshooting

### **Problema: Ticket non viene creato**

**Verifica 1: Log CheckMK**
```bash
tail -f /omd/sites/monitoring/var/log/notify.log
```

**Verifica 2: Permessi script**
```bash
ls -la /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
# Deve essere: -rwxr-xr-x (eseguibile)
```

**Verifica 3: Credenziali Ydea**
```bash
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
```

**Verifica 4: Debug mode**
```bash
# Abilita debug in .env
export DEBUG_YDEA=1

# Riesegui notifica e controlla output
```

### **Problema: Email Ydea down non arriva**

**Verifica 1: Sendmail configurato**
```bash
echo "Test mail" | mail -s "Test" massimo.palazzetti@nethesis.it
```

**Verifica 2: Percorso script email**
```bash
ls -la /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down
```

**Verifica 3: Log health monitor**
```bash
tail -f /tmp/ydea_health.log
```

### **Problema: Troppi ticket duplicati**

**Causa:** Cache corrotta o non accessibile

**Soluzione:**
```bash
# Ripulisci cache
sudo rm /tmp/ydea_checkmk_tickets.json
sudo rm /tmp/ydea_checkmk_flapping.json

# Ricrea con permessi corretti
sudo touch /tmp/ydea_checkmk_tickets.json
sudo chmod 666 /tmp/ydea_checkmk_tickets.json
```

### **Problema: Flapping non rilevato**

**Verifica soglie:**
```bash
# In ydea_realip, controlla:
FLAPPING_THRESHOLD=5  # Numero cambi stato
FLAPPING_WINDOW=600   # Finestra 10 minuti
```

**Verifica cache flapping:**
```bash
cat /tmp/ydea_checkmk_flapping.json | jq .
```

---

## ❓ FAQ

### **Q: Posso cambiare il formato delle note private?**
**A:** Sì, modifica la sezione `NOTE=` nello script `ydea_realip` (circa linea 280-290).

### **Q: Come chiudo automaticamente i ticket quando l'alert rientra?**
**A:** Attualmente i ticket restano aperti con nota privata. Per chiusura automatica, modifica lo script aggiungendo:
```bash
if [[ "$STATE" == "OK" ]]; then
  "$YDEA_TOOLKIT" close "$TICKET_ID" "Alert rientrato automaticamente"
fi
```

### **Q: Posso filtrare quali servizi creano ticket?**
**A:** Sì, in CheckMK notification rule aggiungi condizioni su service name o labels.

### **Q: Come cambio l'intervallo del health monitor?**
**A:** Modifica il cron job (es: `*/5 * * * *` per ogni 5 minuti).

### **Q: Come vedo tutti i ticket creati automaticamente?**
**A:** 
```bash
cat /tmp/ydea_checkmk_tickets.json | jq 'to_entries | .[] | {service: .key, ticket: .value.ticket_id}'
```

### **Q: Il sistema funziona con CheckMK Raw Edition?**
**A:** Sì, compatibile con tutte le edizioni CheckMK (Raw, Enterprise, Cloud).

### **Q: Posso usare Telegram invece di email per Ydea down?**
**A:** Sì, modifica `ydea-health-monitor.sh` per chiamare uno script Telegram invece di `mail_ydea_down`.

---

## 📊 Manutenzione

### **Pulizia Periodica Cache**

```bash
# Script di pulizia (esegui settimanalmente)
#!/bin/bash
# cleanup-ydea-cache.sh

# Rimuovi ticket più vecchi di 30 giorni
NOW=$(date +%s)
MAX_AGE=$((30*24*3600))

jq --arg now "$NOW" --arg max "$MAX_AGE" '
  to_entries | 
  map(select(($now|tonumber) - (.value.created_at|tonumber) < ($max|tonumber))) | 
  from_entries
' /tmp/ydea_checkmk_tickets.json > /tmp/ydea_checkmk_tickets.json.tmp

mv /tmp/ydea_checkmk_tickets.json.tmp /tmp/ydea_checkmk_tickets.json
```

### **Backup Configurazione**

```bash
# Backup settimanale
tar czf ydea-integration-backup-$(date +%Y%m%d).tar.gz \
  /opt/ydea-toolkit/.env \
  /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip \
  /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down \
  /tmp/ydea_checkmk_tickets.json
```

---

## 📞 Supporto

Per problemi o domande:
1. Controlla i log: `/omd/sites/monitoring/var/log/notify.log`
2. Verifica cache: `/tmp/ydea_checkmk_tickets.json`
3. Test manuale degli script come mostrato sopra

---

## 🔄 Changelog

### v1.0.0 (2025-11-13)
- ✅ Prima release integrazione CheckMK → Ydea
- ✅ Gestione automatica ticket con note private
- ✅ Flapping detection
- ✅ Health monitoring Ydea con notifica email
- ✅ Prevenzione duplicati con cache intelligente

---

**Documentazione aggiornata:** 13 Novembre 2025  
**Autore:** Sistema Ydea-Toolkit  
**Repository:** checkmk-tools
