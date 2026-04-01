# CheckMK Distributed Monitoring - Setup Guide
> **Categoria:** Operativo

## Architettura
```
VPS monitor01.nethlab.it (Central Master)
├── Site: monitoring
├── Livestatus TCP: porta 6557 (TLS)
└── Raccoglie dati dal remote site

Box Locale (Remote Site)
├── Site: monitoring
├── Si connette al central via HTTPS
└── Invia dati monitoraggio al central
```

## Fase 1: Configurazione Remote Site (Box Locale)

### 1.1 Esegui script di setup
```bash
cd /opt/checkmk-tools && git pull
sudo bash /opt/checkmk-tools/distributed-monitoring-setup.sh
```

Lo script:
-  Configura il site come remote
-  Crea automation user
-  Genera secret per connessione
-  Mostra le credenziali da usare

**Output atteso:**
```
════════════════════════════════════════════════════
Connection Information for Central Site:
════════════════════════════════════════════════════
Site ID: local-box
Site URL: https://monitor01.nethlab.it/monitoring/
Automation User: automation
Automation Secret: (secret string)
════════════════════════════════════════════════════
```

** IMPORTANTE:** Copia il secret, ti servirà dopo!

---

## Fase 2: Configurazione Central Site (VPS) via UI

### 2.1 Accedi alla UI di CheckMK
1. Apri browser: https://monitor01.nethlab.it/monitoring/
2. Login con le tue credenziali

### 2.2 Aggiungi Remote Site
1. Menu: **Setup → General → Distributed monitoring**
2. Click: **Add connection**

### 2.3 Configura Connection
Compila i campi:

**Basic settings:**
- **Site ID:** `local-box`
- **Alias:** `Local Monitoring Site` (o nome a piacere)

**Connection:**
- **Method:** `Connect to the remote site using Livestatus`
- **Protocol:** `Livestatus over HTTPS`
- **URL:** `https://<IP-BOX-LOCALE>/monitoring/check_mk/`
  -  Oppure se il box ha hostname: `https://hostname-box.locale/monitoring/check_mk/`
- **Port:** `443`

**Authentication:**
- **Username:** `automation`
- **Automation secret:** `<SECRET-COPIATO-PRIMA>`

**Advanced settings:**
-  Enable configuration replication
-  Replicate Event Console configuration
-  Sync with LDAP connections

**Status host:**
-  Create status host
- **Host name:** `Local-Box-Status`

### 2.4 Test Connection
1. Click: **Test connection**
2. Verifica che mostri:  **Connection successful**

### 2.5 Salva
1. Click: **Save**
2. Click: **Activate pending changes** (icona arancione in alto)

---

## Fase 3: Verifica Funzionamento

### 3.1 Verifica su Central (VPS)
1. Menu: **Setup → General → Distributed monitoring**
2. Controlla stato: dovrebbe essere  **Online**

### 3.2 Aggiungi host sul Remote Site
Sul box locale:
```bash
# Accedi al site
sudo -i -u monitoring
cd ~/
omd status

# Aggiungi un host locale (es: il box stesso)
# Via UI o via command line
```

### 3.3 Sincronizza configurazione
Sulla VPS UI:
1. Menu: **Setup → Hosts**
2. Dovresti vedere gli host del remote site
3. Click: **Activate pending changes**

### 3.4 Verifica Dashboard
1. Menu: **Monitor → Overview → Main Overview**
2. Dovresti vedere:
   - Host del central site
   - Host del remote site (con icona del sito)
   - Aggregazione totale

---

## Troubleshooting

### Problema: Connection failed
**Soluzione:**
```bash
# Sul box locale, verifica:
sudo omd status monitoring
sudo ss -tlnp | grep 6557

# Test connessione da VPS:
curl -k https://<IP-BOX-LOCALE>/monitoring/check_mk/
```

### Problema: Authentication failed
**Soluzione:**
```bash
# Sul box locale, rigenera secret:
sudo -i -u monitoring
cd ~/
cat var/check_mk/web/automation/automation.secret

# Aggiorna il secret nella UI del central
```

### Problema: Remote site shows as offline
**Soluzione:**
1. Verifica firewall sul box locale (porta 443 aperta?)
2. Verifica SSL certificate
3. Controlla log: `/omd/sites/monitoring/var/log/web.log`

---

## Note Importanti

###  Connessione
- Il remote site deve poter raggiungere il central su porta 6557
- Se il box locale è dietro NAT, considera FRP tunnel

###  Sicurezza
- La connessione usa TLS/SSL
- L'automation secret è sensibile, trattalo come una password

###  Performance
- I dati vengono aggregati in tempo reale
- Il central interroga il remote ogni 60 secondi di default

###  Configurazione
- Modifiche alla configurazione si fanno sul central
- Il central replica la config sui remote sites

---

## Comandi Utili

### Sul Remote Site
```bash
# Status site
sudo omd status monitoring

# Restart site
sudo omd restart monitoring

# View automation secret
sudo -u monitoring cat /omd/sites/monitoring/var/check_mk/web/automation/automation.secret

# Check Livestatus
echo "GET status" | unixcat /omd/sites/monitoring/tmp/run/live
```

### Sul Central Site
```bash
# Test connessione a remote
sudo -u monitoring lq "GET sites\nColumns: site_id name state"

# View remote site config
sudo -u monitoring cat /omd/sites/monitoring/etc/check_mk/multisite.d/wato/sites.mk
```

---

## Riferimenti

- [CheckMK Documentation - Distributed Monitoring](https://docs.checkmk.com/latest/en/distributed_monitoring.html)
- [Livestatus Protocol](https://docs.checkmk.com/latest/en/livestatus.html)
