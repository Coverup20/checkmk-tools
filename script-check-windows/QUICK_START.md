# Quick Start Guide - Ransomware Detection

## Setup Rapido (5 minuti)

### 1. Configurazione Base

```powershell
# Vai alla directory dello script
cd "c:\Users\Marzio\Desktop\CheckMK\Script\script-check-windows\nopolling"

# Copia e modifica il file di configurazione
copy ransomware_config.json ransomware_config_custom.json
notepad ransomware_config_custom.json
```

### 2. Modifica Share da Monitorare

Modifica `ransomware_config_custom.json`:

```json
{
  "SharePaths": [
    "\\\\tuo-server\\documents",
    "\\\\tuo-server\\shared",
    "C:\\DatiCondivisi"
  ],
  "TimeWindowMinutes": 30,
  "AlertThreshold": 50
}
```

### 3. Test Iniziale

```powershell
# Test con debug per verificare
.\check_ransomware_activity.ps1 `
    -ConfigFile "ransomware_config_custom.json" `
    -Debug

# Se tutto OK, verifica output CheckMK
.\check_ransomware_activity.ps1 `
    -ConfigFile "ransomware_config_custom.json"
```

### 4. Deploy su CheckMK Agent

**Windows con CheckMK Agent installato:**

```powershell
# Directory CheckMK Agent (versiona in base alla tua installazione)
$agentDir = "C:\Program Files (x86)\checkmk\service"

# Se usi local checks
$localDir = "$agentDir\local"

# Copia i file
Copy-Item check_ransomware_activity.ps1 $localDir\
Copy-Item ransomware_config_custom.json $localDir\ransomware_config.json

# Riavvia agent per forzare discovery
Restart-Service CheckMkService
```

### 5. Verifica in CheckMK

1. Vai su CheckMK Web UI
2. Setup → Hosts → `<tuo-host>` → Services
3. Click "Run service discovery"
4. Dovresti vedere:
   - `Ransomware_Detection`
   - `Ransomware_Share_<nome>` per ogni share

5. Click "Accept all"

### 6. Test Alert

```powershell
# Esegui suite di test completa
.\test_ransomware_detection.ps1 -TestScenario All

# Verifica che gli alert funzionino
# Poi pulisci l'ambiente di test quando richiesto
```

## Esempi Configurazione

### Scenario 1: File Server Piccolo

```json
{
  "SharePaths": ["\\\\fileserver\\shared"],
  "TimeWindowMinutes": 15,
  "AlertThreshold": 20,
  "MaxFilesToScan": 500
}
```

### Scenario 2: File Server Grande

```json
{
  "SharePaths": [
    "\\\\fileserver01\\documents",
    "\\\\fileserver01\\finance",
    "\\\\fileserver02\\engineering"
  ],
  "TimeWindowMinutes": 60,
  "AlertThreshold": 100,
  "MaxFilesToScan": 2000,
  "ExcludePaths": ["Temp", "Cache", "Logs", "$RECYCLE.BIN"]
}
```

### Scenario 3: High Security

```json
{
  "SharePaths": ["\\\\critical-data\\finance"],
  "TimeWindowMinutes": 10,
  "AlertThreshold": 10,
  "EnableCanaryFiles": true,
  "MaxFilesToScan": 5000
}
```

## Troubleshooting Rapido

### Problema: Share non accessibile

```powershell
# Verifica accesso
Test-Path "\\server\share"

# Se fallisce, verifica credenziali
net use \\server\share /user:DOMAIN\username
```

### Problema: Script non produce output

```powershell
# Verifica ExecutionPolicy
Get-ExecutionPolicy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verifica sintassi
powershell.exe -File check_ransomware_activity.ps1 -Debug
```

### Problema: Troppi falsi positivi

```json
{
  "AlertThreshold": 100,
  "TimeWindowMinutes": 60,
  "ExcludePaths": ["BackupTemp", "SyncFolder", "Temp"]
}
```

## Comandi Utili

```powershell
# Test veloce
.\check_ransomware_activity.ps1 -SharePaths @("\\server\share") -Debug

# Verifica canary files
Get-ChildItem "\\server\share" -Hidden -Filter ".ransomware_canary*"

# Verifica stato
Get-Content "$env:TEMP\ransomware_state.json" | ConvertFrom-Json

# Cleanup state (per ricominciare da zero)
Remove-Item "$env:TEMP\ransomware_state.json" -Force

# Test completo
.\test_ransomware_detection.ps1
```

## Monitoraggio Continuo

### Opzione 1: CheckMK Local Check (Raccomandato)

Lo script viene eseguito ad ogni check dell'agent (di solito ogni 60 secondi).

```powershell
# Copia in local directory
Copy-Item check_ransomware_activity.ps1 "C:\Program Files (x86)\checkmk\service\local\"
```

### Opzione 2: Scheduled Task

Per esecuzione ogni 15 minuti:

```powershell
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" `
    -Argument "-File `"C:\Scripts\check_ransomware_activity.ps1`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "RansomwareMonitoring" `
    -Action $action -Trigger $trigger `
    -User "SYSTEM" -RunLevel Highest
```

## Prossimi Passi

1. ✅ Configurazione base
2. ✅ Test funzionamento
3. ✅ Deploy su CheckMK
4. 📧 Configura notifiche email per CRITICAL
5. 📊 Crea dashboard CheckMK
6. 📝 Documenta procedure di response
7. 🔄 Schedule review mensile

## Checklist Post-Deploy

- [ ] Script funziona senza errori
- [ ] Canary files creati in tutte le share
- [ ] Servizi visibili in CheckMK
- [ ] Test alert con file simulato
- [ ] Notifiche configurate
- [ ] Team informato su alert possibili
- [ ] Procedure di response documentate
- [ ] Backup verificati e offline

---

**Note di Sicurezza:**

⚠️ Questo è uno strumento di **rilevamento**, non di prevenzione
⚠️ Mantieni sempre backup offline aggiornati
⚠️ Implementa difesa a livelli (antivirus, firewall, segmentation)
⚠️ Forma gli utenti a riconoscere phishing e minacce
