# CheckMK Host Labels Configuration Template
# Template per configurare i label 'real_ip' negli host CheckMK

## 🎯 OBIETTIVO
Configurare il label 'real_ip' negli host CheckMK per abilitare 
l'uso dell'IP reale nelle email invece di 127.0.0.1

## 📋 PREREQUISITI
- Accesso amministrativo a CheckMK Web UI
- Conoscere l'IP pubblico/reale del server CheckMK
- Permessi per modificare configurazione host

## 🔧 CONFIGURAZIONE VIA WEB UI

### Metodo 1: Configurazione Singolo Host

1. **Accedere a CheckMK Web UI**
   ```
   URL: https://YOUR_CHECKMK_SERVER/YOUR_SITE/
   ```

2. **Navigare alla configurazione host**
   ```
   Setup → Hosts → [Selezionare host del server CheckMK]
   ```

3. **Aggiungere label 'real_ip'**
   ```
   Sezione: Host tags
   → Effective host tags
   → Host labels
   → Add new label
   
   Label key: real_ip
   Label value: YOUR_REAL_IP_ADDRESS
   ```

4. **Esempi di configurazione**
   ```
   Label key: real_ip
   Label value: 192.168.1.100    # IP LAN
   
   Label key: real_ip  
   Label value: 203.0.113.50     # IP pubblico
   
   Label key: real_ip
   Label value: example.com      # FQDN (se risolve correttamente)
   ```

5. **Salvare e attivare**
   ```
   → Save & go to folder
   → Activate affected
   → Activate changes
   ```

### Metodo 2: Configurazione via File (Avanzato)

1. **Accedere al server CheckMK**
   ```bash
   ssh user@checkmk-server
   su - SITENAME
   ```

2. **Modificare configurazione host**
   ```bash
   # Trovare il file di configurazione host
   find etc/check_mk/conf.d/ -name "*.mk" -exec grep -l "YOUR_HOSTNAME" {} \;
   
   # Modificare il file trovato
   vi etc/check_mk/conf.d/wato/hosts.mk
   ```

3. **Aggiungere label nella configurazione**
   ```python
   # Esempio di configurazione host con label
   all_hosts += [
       "your-checkmk-server|host|wato|/",
   ]
   
   # Aggiungere label
   host_labels.update({
       "your-checkmk-server": {
           "real_ip": "192.168.1.100",
       },
   })
   ```

4. **Attivare modifiche**
   ```bash
   cmk -R
   # Oppure via Web UI: Activate changes
   ```

## 🧪 VERIFICA CONFIGURAZIONE

### Test via Web UI
1. **Verificare label applicato**
   ```
   Monitoring → Hosts → [Selezionare host]
   → Scheda "Properties"
   → Verificare presenza label "real_ip"
   ```

### Test via Command Line
```bash
# Su server CheckMK
su - SITENAME

# Verificare label host
cmk --debug -v YOUR_HOSTNAME | grep -i label

# Test variabili notifica
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100"
echo $NOTIFY_HOSTLABEL_real_ip
```

### Test Script Notifica
```bash
# Test con script mail_realip_graphs
export NOTIFY_CONTACTEMAIL="test@domain.com"
export NOTIFY_HOSTNAME="your-server"
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100"
export NOTIFY_WHAT="HOST"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"

# Eseguire script per test
./local/share/check_mk/notifications/mail_realip_graphs
```

## 📊 ESEMPI CONFIGURAZIONE

### Esempio 1: Server con IP Statico LAN
```
Host: checkmk-prod
Real IP: 192.168.10.50
Label: real_ip = 192.168.10.50

Risultato email:
- Link: https://192.168.10.50/monitoring/check_mk/...
- Grafici: Generati con IP 192.168.10.50
```

### Esempio 2: Server con IP Pubblico
```
Host: monitoring.company.com  
Real IP: 203.0.113.100
Label: real_ip = 203.0.113.100

Risultato email:
- Link: https://203.0.113.100/monitoring/check_mk/...
- Grafici: Accessibili pubblicamente
```

### Esempio 3: Server con FQDN
```
Host: internal-monitoring
Real IP: monitoring.internal.company.com
Label: real_ip = monitoring.internal.company.com

Risultato email:
- Link: https://monitoring.internal.company.com/site/check_mk/...
- Grafici: Risoluzione DNS automatica
```

## ⚠️ ATTENZIONE

### Considerazioni di Sicurezza
- **IP Pubblici**: Assicurarsi che CheckMK sia accessibile pubblicamente solo se necessario
- **Firewall**: Configurare adeguatamente le regole firewall
- **SSL/TLS**: Usare sempre HTTPS per accesso pubblico

### Considerazioni di Rete
- **Risoluzione DNS**: Se usi FQDN, assicurati che risolva correttamente
- **Raggiungibilità**: L'IP/FQDN deve essere raggiungibile dai client email
- **Certificati**: Per HTTPS, certificati devono essere validi per l'IP/FQDN usato

## 🔧 TROUBLESHOOTING

### Problema: Label non applicato
```bash
# Verificare syntax file configurazione
cmk --check-config

# Riavviare servizi CheckMK
cmk -R
systemctl restart checkmk-SITENAME
```

### Problema: Script non trova real_ip
```bash
# Verificare variabili ambiente notifica
env | grep NOTIFY_HOSTLABEL

# Debug script
python3 -c "
import os
real_ip = os.environ.get('NOTIFY_HOSTLABEL_real_ip')
print(f'Real IP trovato: {real_ip}')
"
```

### Problema: Email ancora con 127.0.0.1
- Verificare che script mail_realip_graphs sia utilizzato
- Controllare regole notifica attive
- Verificare label host configurato correttamente

## ✅ CHECKLIST CONFIGURAZIONE

- [ ] Label 'real_ip' aggiunto all'host
- [ ] Valore label corretto (IP/FQDN raggiungibile)
- [ ] Modifiche attivate in CheckMK
- [ ] Script mail_realip_graphs installato
- [ ] Regola notifica configurata per usare nuovo script
- [ ] Test notifica inviato e verificato
- [ ] Email ricevute mostrano real IP invece di 127.0.0.1
- [ ] Grafici funzionanti e accessibili tramite real IP

---

**📝 Note**: Questa configurazione è fondamentale per il corretto 
funzionamento del sistema email con real IP e grafici abilitati.