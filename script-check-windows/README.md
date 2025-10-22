# Script di Monitoraggio CheckMK per Windows

Collezione di script PowerShell per il monitoraggio di host Windows tramite CheckMK.

## 📁 Struttura

```
script-check-windows/
├── nopolling/           # Script eseguiti ad ogni check dell'agent
│   ├── check_ransomware_activity.ps1
│   ├── ransomware_config.json
│   ├── test_ransomware_detection.ps1
│   └── generate_ransomware_report.ps1
├── polling/             # Script con intervalli specifici (future)
├── README-Ransomware-Detection.md
└── QUICK_START.md
```

## 🛡️ Script Disponibili

### 1. Ransomware Detection ⭐ NEW

**Descrizione:** Sistema di rilevamento attività ransomware su share di rete

**File:**
- `check_ransomware_activity.ps1` - Script principale di monitoraggio
- `ransomware_config.json` - File di configurazione
- `test_ransomware_detection.ps1` - Suite di test completa
- `generate_ransomware_report.ps1` - Generatore report HTML/JSON

**Caratteristiche:**
- ✅ Rilevamento file con estensioni ransomware (50+ varianti)
- ✅ Canary files (file esca per detection immediata)
- ✅ Identificazione ransom notes
- ✅ Analisi crittografia massiva
- ✅ Metriche dettagliate per CheckMK
- ✅ Report HTML per incident response

**Quick Start:**
```powershell
# Vedi QUICK_START.md per setup completo
cd nopolling
.\check_ransomware_activity.ps1 -Debug

# Test completo
.\test_ransomware_detection.ps1 -TestScenario All
```

**Documentazione:** [README-Ransomware-Detection.md](./README-Ransomware-Detection.md)

## 📋 Roadmap Script Futuri

### In Sviluppo

- [ ] **check_windows_updates.ps1** - Monitoraggio Windows Updates
- [ ] **check_windows_services.ps1** - Stato servizi critici
- [ ] **check_windows_eventlog.ps1** - Analisi event log per security events
- [ ] **check_windows_disk_health.ps1** - SMART status e disk health
- [ ] **check_windows_firewall.ps1** - Stato e regole firewall Windows
- [ ] **check_windows_defender.ps1** - Stato Windows Defender
- [ ] **check_active_directory.ps1** - Monitoraggio AD (DC, replication)
- [ ] **check_iis_sites.ps1** - Monitoraggio IIS application pools
- [ ] **check_sql_server.ps1** - Monitoraggio SQL Server
- [ ] **check_exchange_server.ps1** - Monitoraggio Exchange
- [ ] **check_certificate_expiry.ps1** - Scadenza certificati
- [ ] **check_backup_status.ps1** - Verifica backup Windows Server

### Pianificati

- [ ] **check_network_shares.ps1** - Disponibilità e performance share
- [ ] **check_user_sessions.ps1** - Sessioni RDP e login anomali
- [ ] **check_process_monitor.ps1** - Processi sospetti e resource usage
- [ ] **check_scheduled_tasks.ps1** - Task pianificati e loro stato
- [ ] **check_printer_status.ps1** - Stato stampanti di rete
- [ ] **check_dhcp_scope.ps1** - DHCP scope utilization
- [ ] **check_dns_zones.ps1** - Stato zone DNS
- [ ] **check_hyper_v.ps1** - Monitoraggio VM Hyper-V

## 🚀 Come Contribuire

### Aggiungere un Nuovo Script

1. **Crea lo script** in `nopolling/` o `polling/`
2. **Segui il template:**

```powershell
#!/usr/bin/env powershell
<#
.SYNOPSIS
    CheckMK Local Check - [Descrizione]
    
.DESCRIPTION
    [Descrizione dettagliata]
    
.NOTES
    Author: [Nome]
    Date: [Data]
    Version: 1.0
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [switch]$Debug
)

# Output CheckMK
Write-Host "<<<local>>>"
Write-Host "0 Service_Name metric1=value|metric2=value Details message"
```

3. **Crea file di test**
4. **Aggiungi documentazione** (README dedicato)
5. **Aggiorna questo README** con il nuovo script

### Standard di Codice

- ✅ Output formato CheckMK: `<<<local>>>`
- ✅ Stati: 0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN
- ✅ Metriche con pipe: `metric=value|metric2=value`
- ✅ Parametro `-Debug` per troubleshooting
- ✅ Gestione errori con try/catch
- ✅ Commenti e documentazione completa

## 📖 Convenzioni Naming

### File Script

- **Formato:** `check_<nome>_<categoria>.ps1`
- **Esempi:**
  - `check_ransomware_activity.ps1`
  - `check_windows_updates.ps1`
  - `check_iis_sites.ps1`

### Servizi CheckMK

- **Formato:** `<Categoria>_<Nome>`
- **Esempi:**
  - `Ransomware_Detection`
  - `Windows_Updates`
  - `IIS_AppPool_DefaultAppPool`

### Metriche

- **Formato:** `<nome_snake_case>=<valore>`
- **Esempi:**
  - `suspicious_files=10`
  - `pending_updates=5`
  - `pool_requests_per_sec=1250`

## 🔧 Installazione Generica

### CheckMK Agent su Windows

1. **Directory Agent:**
   ```
   C:\Program Files (x86)\checkmk\service\
   ├── local\      # Script eseguiti ad ogni check
   └── plugins\    # Script con scheduling
   ```

2. **Deploy Script:**
   ```powershell
   # Per local check (esecuzione continua)
   Copy-Item check_*.ps1 "C:\Program Files (x86)\checkmk\service\local\"
   
   # Per plugin con intervallo (es: ogni 5 min = 300 sec)
   Copy-Item check_*.ps1 "C:\Program Files (x86)\checkmk\service\plugins\300\"
   ```

3. **Riavvia Agent:**
   ```powershell
   Restart-Service CheckMkService
   ```

4. **Discovery in CheckMK:**
   - Setup → Hosts → [host] → Services
   - Run service discovery
   - Accept new services

## 📊 Best Practices

### Performance

- ⚡ Limita scan a max 1000-2000 file
- ⚡ Usa `-ErrorAction SilentlyContinue` per robustezza
- ⚡ Implementa timeout per operazioni lunghe
- ⚡ Cache risultati quando possibile

### Sicurezza

- 🔒 Esegui con least privilege possibile
- 🔒 Non hardcodare credenziali
- 🔒 Usa file di configurazione esterni
- 🔒 Valida input dei parametri

### Affidabilità

- ✅ Gestisci sempre le eccezioni
- ✅ Fornisci output anche in caso di errore
- ✅ Usa stato UNKNOWN per errori critici
- ✅ Log dettagliato in modalità debug

### Manutenibilità

- 📝 Documenta ogni funzione
- 📝 Usa nomi variabili descrittivi
- 📝 Mantieni funzioni piccole e focused
- 📝 Separa logica da presentazione

## 🧪 Testing

### Test Locale

```powershell
# Test singolo script
.\check_script_name.ps1 -Debug

# Verifica output CheckMK
.\check_script_name.ps1 | Select-String "<<<local>>>"

# Test performance
Measure-Command { .\check_script_name.ps1 }
```

### Test Suite

Ogni script dovrebbe avere un `test_*.ps1` corrispondente:

```powershell
# Esegui test completo
.\test_script_name.ps1 -TestScenario All

# Test specifico
.\test_script_name.ps1 -TestScenario Basic

# Cleanup
.\test_script_name.ps1 -Cleanup
```

## 📚 Risorse

### CheckMK Documentation

- [Local Checks](https://docs.checkmk.com/latest/en/localchecks.html)
- [Windows Agent](https://docs.checkmk.com/latest/en/agent_windows.html)
- [Plugin API](https://docs.checkmk.com/latest/en/devel_check_plugins.html)

### PowerShell

- [Best Practices](https://docs.microsoft.com/powershell/scripting/developer/cmdlet/cmdlet-development-guidelines)
- [Error Handling](https://docs.microsoft.com/powershell/scripting/learn/deep-dives/everything-about-exceptions)
- [Performance Tips](https://docs.microsoft.com/powershell/scripting/dev-cross-plat/performance/script-authoring-considerations)

## 🐛 Troubleshooting

### Script non appare in CheckMK

```powershell
# Verifica permissions
icacls "C:\Program Files (x86)\checkmk\service\local\check_*.ps1"

# Verifica execution policy
Get-ExecutionPolicy -List

# Test manuale
& "C:\Program Files (x86)\checkmk\service\local\check_script.ps1"
```

### Output non corretto

```powershell
# Verifica formato
.\check_script.ps1 | Format-Hex

# Debug mode
.\check_script.ps1 -Debug 2>&1 | Tee-Object -FilePath debug.log
```

### Performance lenta

```powershell
# Profile script
Measure-Command { .\check_script.ps1 } | Format-Table

# Identifica colli di bottiglia
# Aggiungi timestamp in debug mode
```

## 📞 Supporto

Per problemi o domande:

1. Controlla la documentazione dello script specifico
2. Esegui in modalità `-Debug`
3. Verifica i log di CheckMK Agent
4. Controlla i permessi e le configurazioni

## 📄 License

Script sviluppati per uso interno con CheckMK.

## ✨ Contributors

- Marzio - Initial work

---

**Ultimo aggiornamento:** 2025-10-22  
**Versione:** 1.0  
**Script attivi:** 1 (Ransomware Detection)
