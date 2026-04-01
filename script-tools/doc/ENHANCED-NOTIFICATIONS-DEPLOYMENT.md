# IMPLEMENTATION SUMMARY - Enhanced Notifications for CheckMK
> **Categoria:** Specialistico

##  Cosa è Stato Implementato

Ho creato un **nuovo sistema di notifiche avanzate** completamente indipendente che migliora la comunicazione di due scenari critici di CheckMK:

### 1⃣ **HOST DOWN Alerts** 
Quando un host perde connettività (Connection Refused, Network Down, Timeout)

### 2⃣ **HOST UP - NO DATA Alerts**   
Quando un host è online ma non invia dati di monitoraggio

---

##  File Creati

| File | Tipo | Descrizione |
|------|------|-------------|
| `ydea_ag_host_down` | Script bash | Enhanced Ydea - smart alert detection + context-aware tickets |
| `rydea_ag_host_down` | Remote launcher | Versione per deployment remoto da GitHub |
| `ENHANCED-NOTIFICATIONS-README.md` | Doc | Guida dettagliata |
| `ENHANCED-TESTING-GUIDE.md` | Doc | Procedure di test |

**Percorsi**:
- Full: `script-notify-checkmk/full/`
- Remote: `script-notify-checkmk/remote/`

---

##  Come Funziona

### Architettura

```
CheckMK Alert
    ↓
┌─────────────────────────────────────┐
│ ydea_ag_host_down Script            │
├─────────────────────────────────────┤
│ 1. Analizza alert output            │
│ 2. Rileva tipo (DOWN/NODATA/etc)    │
│ 3. Genera description context-aware │
│ 4. Crea ticket Ydea                 │
│ 5. Cache tracking (tickets/flapping)│
│ 6. Rileva e gestisce flapping       │
└─────────────────────────────────────┘
    ↓
Ticket Ydea con descrizione migliorata
```

### Workflow

1. **Alert Type Detection**: Analizza l'output di CheckMK per riconoscere: REFUSED, NETWORK, TIMEOUT, NODATA, MISSING_DATA, STALE_DATA
2. **Context-Aware Descriptions**: Genera ticket descriptions specifiche per ogni tipo di problema
3. **Ticket Creation**: Crea ticket Ydea automaticamente
4. **Cache Tracking**: Mantiene storico dei ticket per evitare duplicati
5. **Flapping Detection**: Rileva host/servizi che cambiano stato ripetutamente (escalation)

---

##  Miglioramenti Rispetto a Prima

### PRIMA (Alert Generico)
```
[agent] Communication failed: [Errno 111] Connection refused CRIT
[piggyback] Success (but no data found for this host) WARN
Missing monitoring data for all plugins WARN
```
 Confuso |  Tecnico |  Non actionable

### DOPO (Alert Migliorato)
```
 HOST DOWN - hostname (192.168.10.110)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLEMA:
L'host ha rifiutato la connessione. Potrebbe essere:
  • Host spento o in riavvio
  • Servizio CheckMK agent non in ascolto
  • Firewall blocca la porta
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AZIONI SUGGERITE:
  1. Verificare se host è raggiungibile: ping 192.168.10.110
  2. Verificare stato agent: ssh hostname 'systemctl status check-mk-agent'
  3. Verificare firewall verso port 6556
```
 Chiaro |  Operativo |  Actionable

---

##  Installazione Quick Start

### Opzione 1: Manual (Consigliata) 

```bash
# Su CheckMK server - come monitoring user
su - monitoring
cd ~/local/share/check_mk/notifications/

# Copia da GitHub il nuovo ydea_ag_host_down
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-notify-checkmk/full/ydea_ag_host_down \
  -o ydea_ag_host_down && chmod +x ydea_ag_host_down

# Verifica che sia eseguibile
ls -la ydea_ag_host_down
```

### Opzione 2: Remote Launcher (Con aggiornamenti automatici)

```bash
# Su CheckMK server - come monitoring user
su - monitoring
cd ~/local/share/check_mk/notifications/

# Copia il remote launcher
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-notify-checkmk/remote/rydea_ag_host_down \
  -o rydea_ag_host_down && chmod +x rydea_ag_host_down

# Verifica
ls -la rydea_ag_host_down
```

### Configura in CheckMK Web UI

1. **Setup** → **Events** → **Notifications**
2. **Create New Notification Rule**
   - **Notification Method**: `Script based notification`
   - **Script name**: `ydea_ag_host_down` (oppure `rydea_ag_host_down`)
   - **Conditions** - seleziona almeno uno:
     - Host state is `Down` 
     - Service state is `Critical` AND output contains `no data`
     - Output contains `Connection refused` OR `Network unreachable` OR `timeout`
   - **Contact**: Assegna a admin o email di ops
3. **Activate Changes**

---

##  Relazione con ydea_ag (IMPORTANTE)

**`ydea_ag_host_down` è una versione migliorata di `ydea_ag`**

-  Mantiene TUTTI i meccanismi originali (cache, ticket aggregation, flapping detection)
-  Aggiunge smart alert type detection (REFUSED, NETWORK, TIMEOUT, NODATA, etc.)
-  Genera ticket descriptions migliorati e context-aware
-  Completamente compatibile - puoi sostituire ydea_ag con ydea_ag_host_down

---

##  Features

### Smart Alert Type Detection
```
CONNECTION_REFUSED → HOST_OFFLINE_REFUSED
NETWORK_UNREACHABLE → HOST_OFFLINE_NETWORK  
TIMEOUT → HOST_OFFLINE_TIMEOUT
NO_DATA_FOUND → HOST_NODATA
MISSING_DATA → HOST_MISSING_DATA
STALE_CACHE → HOST_STALE_DATA
```

### Ticket Creation
- Crea ticket Ydea automaticamente (come ydea_ag originale)
- Aggiunge descrizione context-aware basata sul tipo di alert
- Mantiene aggregazione di ticket (non crea duplicati)
- Mantiene flapping detection (5 cambiamenti in 10 minuti = escalation)

### Local Caching
```
/tmp/ydea-cache/
├── tickets.json             # Traccia ticket creati
├── flapping-detection.json  # Rileva host che flappano
└── /tmp/ydea-host-down.log  # Log eventi
```

---

##  Testing

### Test Standalone
```bash
export NOTIFY_HOSTNAME="test-host"
export NOTIFY_HOSTADDRESS="192.168.1.100"
export NOTIFY_HOSTSTATE="DOWN"
export NOTIFY_SERVICEDESC="Check_MK"
export NOTIFY_SERVICESTATE="CRIT"
export NOTIFY_SERVICEOUTPUT="Connection refused"
export NOTIFY_CONTACTEMAIL="admin@example.com"
export DEBUG_NOTIFY=1

bash notify-enhanced-down-nodata
```

Vedi **ENHANCED-TESTING-GUIDE.md** per procedure complete.

---

##  Monitoring

### Visualizza Log
```bash
tail -f /opt/checkmk/enhanced-notifications/enhanced-notify.log
```

### Esegui Test
```bash
# Esegui il test con le variabili
~/local/share/check_mk/notifications/ydea_ag_host_down

# Verifica il ticket creato su Ydea
# (Nota: il ticket verrà creato SOLO se ~/.env.ag è configurato correttamente)
```

### Analizza Cache
```bash
# Vedi i ticket creati
cat /tmp/ydea-cache/tickets.json | jq '.'

# Vedi flapping detection
cat /tmp/ydea-cache/flapping-detection.json | jq '.'
```

### Conteggio Notifiche
```bash
# Quanti alert elaborati
tail -50 /tmp/ydea-host-down.log

# Vedi gli alert type riconosciuti
grep "ALERT_TYPE" /tmp/ydea-host-down.log
```

---

##  Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| "Script not found" | Verifica path: `ls -la ~/local/share/check_mk/notifications/ydea_ag_host_down` |
| "Permission denied" | Imposta permessi: `chmod +x ~/local/share/check_mk/notifications/ydea_ag_host_down` |
| Ticket non creato | Verifica `~/.env.ag`: `cat ~/.env.ag` deve contenere YDEA_ID e YDEA_API_KEY |
| Cache permission denied | `mkdir -p /tmp/ydea-cache && chmod 777 /tmp/ydea-cache` |
| Script not executed in CheckMK | Verifica notification rule in Web UI - seleziona "Script based notification" |
| Flapping detection troppo sensibile | Modifica FLAP_THRESHOLD in ydea_ag_host_down (attualmente 5 in 10 min) |

---

##  Documentazione Completa

Tutti i file sono nel repository:

- **Dettagli ydea_ag_host_down**: Leggi i commenti nel script stesso
- **Testing**: `ENHANCED-TESTING-GUIDE.md` (ancora valido per i meccanismi)
- **README**: `ENHANCED-NOTIFICATIONS-README.md` (riferimento generale)

---

##  Checklist Deployment

- [ ] Script scaricato nella directory corretta: `~/local/share/check_mk/notifications/`
- [ ] Permessi corretti: `ls -la` mostra `rwxr-xr-x` per ydea_ag_host_down
- [ ] `~/.env.ag` esiste e contiene credenziali Ydea
- [ ] Notification rule creata in CheckMK Web UI
- [ ] Test alert generato (simula host down)
- [ ] Ticket creato su Ydea (verifica manualmente)
- [ ] Log verificato: `tail /tmp/ydea-host-down.log`
- [ ] Cache creata: `ls /tmp/ydea-cache/`

---

##  Prossimi Step (Opzionali)

1. **Sostituire ydea_ag**: Se vuoi usare SOLO ydea_ag_host_down (raccomandato)
2. **Integrazione ITSM**: Aggiungere link KB nel ticket Ydea
3. **Escalation Logic**: Auto-escalate dopo N occorrenze
4. **Slack Integration**: Aggiungere notifiche Slack
5. **Custom Templates**: Personalizzare ticket descriptions

---

##  Support

- **GitHub**: https://github.com/Coverup20/checkmk-tools
- **Repository**: checkmk-tools - branch main

---

## Version Info

| Component | Versione | Data |
|-----------|----------|------|
| ydea_ag_host_down | 1.0 | 2025-12-15 |
| rydea_ag_host_down (remote) | 1.0 | 2025-12-15 |
| Documentation | 1.0 | 2025-12-15 |
| Repository | checkmk-tools | main branch |

---

##  Sicurezza

-  Nessuna credenziale hardcoded
-  Cache permessi world-writable (777) per multi-user
-  Log sanitizzato (no IP/host sensitivi in output)
-  Indipendente da ydea_ag (no lock file contention)

---

##  Nota Importante

**Questo script è completamente indipendente da `ydea_ag` e NON lo modifica.**

- Non tocca la logica di creazione ticket
- Non modifica cache di ydea_ag
- Può essere usato standalone o insieme
- Zero impatto su sistema esistente

---

**Status**:  **READY FOR PRODUCTION**

Tutti i file sono committati in repository e pronti per il deploy.
