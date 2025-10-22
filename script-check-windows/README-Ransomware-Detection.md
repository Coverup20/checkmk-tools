# Script di Rilevamento Ransomware per Windows Share

## Descrizione

Script PowerShell per CheckMK che monitora le share di rete Windows alla ricerca di attività sospette di ransomware. Implementa tecniche avanzate di rilevamento:

- **File sospetti**: Rileva file con estensioni tipiche di ransomware
- **Ransom Notes**: Identifica file con istruzioni per il riscatto
- **Canary Files**: File esca che rilevano modifiche non autorizzate
- **Attività massiva**: Rileva crittografia su larga scala
- **Pattern anomali**: Nome file strani, doppie estensioni, modifiche rapide

## Caratteristiche Principali

### 🛡️ Multi-Layer Detection

1. **Estensioni Ransomware**
   - Database di oltre 50 estensioni note (`.locked`, `.encrypted`, `.wannacry`, `.ryuk`, etc.)
   - Rilevamento doppia estensione (es: `.docx.encrypted`)

2. **Canary Files** (File Esca)
   - File nascosti creati automaticamente in ogni share
   - Alert immediato se modificati o eliminati
   - Attributi: Hidden + ReadOnly

3. **Ransom Notes Detection**
   - Pattern matching su nomi file (`README`, `DECRYPT`, `HOW_TO_RESTORE`)
   - Analisi contenuto per keyword (`ransom`, `bitcoin`, `decrypt`)
   - Rilevamento file HTML/HTA sospetti

4. **Mass Modification Analysis**
   - Soglia configurabile di file modificati
   - Analisi velocità di modifica (file/minuto)
   - Mappatura directory coinvolte

### 📊 Metriche CheckMK

Lo script genera metriche dettagliate per grafici e alerting:

```
suspicious_files=<count>     # File sospetti rilevati
ransom_notes=<count>         # Note di riscatto trovate
canary_alerts=<count>        # Canary file compromessi
shares_ok=<count>            # Share accessibili
```

### 🎯 Stati di Allerta

- **OK (0)**: Nessuna attività sospetta
- **WARNING (1)**: File sospetti rilevati (sotto soglia)
- **CRITICAL (2)**: Attività ransomware confermata
  - Canary file compromessi
  - Ransom notes presenti
  - Crittografia massiva in corso
- **UNKNOWN (3)**: Errore esecuzione o configurazione

## Installazione

### 1. Preparazione Directory

```powershell
# Crea directory per lo script
mkdir "C:\Program Files (x86)\check_mk\local"

# Copia lo script
copy check_ransomware_activity.ps1 "C:\Program Files (x86)\check_mk\local\"
copy ransomware_config.json "C:\Program Files (x86)\check_mk\local\"
```

### 2. Configurazione

Modifica `ransomware_config.json` con i tuoi percorsi:

```json
{
  "SharePaths": [
    "\\\\fileserver\\documents",
    "\\\\fileserver\\finance",
    "C:\\SharedData"
  ],
  "TimeWindowMinutes": 30,
  "AlertThreshold": 50,
  "EnableCanaryFiles": true,
  "MaxFilesToScan": 1000,
  "ExcludePaths": [
    "$RECYCLE.BIN",
    "System Volume Information"
  ]
}
```

### 3. Permessi

Lo script deve eseguire con un utente che ha:
- **Lettura** su tutte le share monitorate
- **Scrittura** nelle share (per canary files)
- Permessi locali per scrivere in `%TEMP%` (per state file)

```powershell
# Verifica accesso
Test-Path "\\fileserver\documents" -PathType Container
```

### 4. Configurazione CheckMK Agent

**Metodo 1: Local Check (Raccomandato)**

```powershell
# Copia nella directory local checks
$localDir = "C:\Program Files (x86)\check_mk\local"
Copy-Item check_ransomware_activity.ps1 $localDir
Copy-Item ransomware_config.json $localDir
```

**Metodo 2: Plugin con Scheduling**

```powershell
# Per esecuzione ogni 15 minuti
$pluginDir = "C:\Program Files (x86)\check_mk\plugins"
# Rinomina: check_ransomware_activity_900.ps1 (900 secondi = 15 min)
```

### 5. Test Manuale

```powershell
# Test base
.\check_ransomware_activity.ps1 -Debug

# Test con parametri custom
.\check_ransomware_activity.ps1 `
    -SharePaths @("\\server\share1", "\\server\share2") `
    -TimeWindowMinutes 60 `
    -AlertThreshold 100 `
    -Debug

# Verifica output CheckMK
.\check_ransomware_activity.ps1 | Select-String "<<<local>>>" -Context 0,10
```

## Uso

### Parametri CLI

```powershell
.\check_ransomware_activity.ps1 `
    [-SharePaths <string[]>] `
    [-TimeWindowMinutes <int>] `
    [-AlertThreshold <int>] `
    [-ConfigFile <string>] `
    [-StateFile <string>] `
    [-Debug]
```

| Parametro | Tipo | Default | Descrizione |
|-----------|------|---------|-------------|
| `SharePaths` | array | da config | Array di percorsi UNC o locali |
| `TimeWindowMinutes` | int | 30 | Finestra temporale analisi |
| `AlertThreshold` | int | 50 | File minimi per alert CRITICAL |
| `ConfigFile` | string | `ransomware_config.json` | File configurazione |
| `StateFile` | string | `%TEMP%\ransomware_state.json` | File di stato |
| `Debug` | switch | false | Abilita output debug |

### Esempi

```powershell
# Uso standard (legge da config file)
.\check_ransomware_activity.ps1

# Override shares specifiche
.\check_ransomware_activity.ps1 -SharePaths @("C:\Data", "\\srv\public")

# Analisi ultimi 60 minuti con soglia alta
.\check_ransomware_activity.ps1 -TimeWindowMinutes 60 -AlertThreshold 200

# Debug mode per troubleshooting
.\check_ransomware_activity.ps1 -Debug
```

## Output CheckMK

### Formato Standard

```
<<<local>>>
0 Ransomware_Detection suspicious_files=0|ransom_notes=0|canary_alerts=0|shares_ok=3 OK - Nessuna attività sospetta rilevata su 3/3 shares
0 Ransomware_Share_fileserver_documents suspicious=0|notes=0 OK
0 Ransomware_Share_fileserver_finance suspicious=0|notes=0 OK
```

### In Caso di Alert

```
<<<local>>>
2 Ransomware_Detection suspicious_files=87|ransom_notes=2|canary_alerts=1|shares_ok=3 ALERT: Canary file compromessi (1), ALERT: Ransom notes rilevate (2), ALERT: Attività di crittografia massiva rilevata (87 files) | Top files: document.pdf.locked (score: 10), report.xlsx.encrypted (score: 10)
2 Ransomware_Share_fileserver_documents suspicious=45|notes=1 CRIT - Suspicious files: 45
2 Ransomware_Share_fileserver_finance suspicious=42|notes=1 CRIT - Suspicious files: 42
```

## Configurazione Avanzata

### File ransomware_config.json

```json
{
  "SharePaths": [
    "\\\\fileserver\\documents",
    "\\\\fileserver\\finance",
    "\\\\backup\\critical",
    "C:\\SharedData"
  ],
  
  "TimeWindowMinutes": 30,
  
  "AlertThreshold": 50,
  
  "EnableCanaryFiles": true,
  
  "CanaryFileName": ".ransomware_canary_do_not_delete.txt",
  
  "EnableEntropyCheck": true,
  
  "MaxFilesToScan": 1000,
  
  "ExcludePaths": [
    "$RECYCLE.BIN",
    "System Volume Information",
    ".git",
    "node_modules",
    "Temp",
    "Cache"
  ],
  
  "NotificationEmail": "security@example.com",
  
  "HighRiskExtensions": [
    ".exe",
    ".dll",
    ".scr",
    ".bat",
    ".cmd",
    ".vbs",
    ".ps1"
  ],
  
  "ScanSchedule": {
    "IntervalMinutes": 15,
    "DeepScanHours": [2, 14]
  }
}
```

### Descrizione Parametri

- **SharePaths**: Array di percorsi da monitorare (UNC o locali)
- **TimeWindowMinutes**: Finestra temporale per analisi modifiche
- **AlertThreshold**: Numero minimo di file sospetti per CRITICAL
- **EnableCanaryFiles**: Abilita/disabilita canary files
- **CanaryFileName**: Nome del file esca (nascosto)
- **EnableEntropyCheck**: Abilita analisi entropia (richiede più risorse)
- **MaxFilesToScan**: Limite file per performance
- **ExcludePaths**: Directory da escludere dalla scansione
- **NotificationEmail**: Email per notifiche (future implementazioni)
- **HighRiskExtensions**: Estensioni eseguibili da monitorare
- **ScanSchedule**: Configurazione scheduling (future implementazioni)

## Canary Files

### Cosa Sono

I canary files sono file "esca" posizionati strategicamente nelle share per rilevare immediatamente attività di ransomware. Il principio è semplice:

1. Lo script crea un file nascosto in ogni share
2. Il file viene marcato come `Hidden` + `ReadOnly`
3. Il ransomware, nella sua attività indiscriminata, tenterà di crittografare anche questi file
4. Qualsiasi modifica/eliminazione genera alert immediato

### Gestione

```powershell
# I canary files sono creati automaticamente
# Percorso: <SharePath>\.ransomware_canary_do_not_delete.txt

# Per verificare manualmente
Get-ChildItem "\\server\share" -Hidden -Filter ".ransomware_canary*"

# Contenuto esempio
cat \\server\share\.ransomware_canary_do_not_delete.txt
```

### Best Practices

- ✅ Non eliminare manualmente i canary files
- ✅ Escluderli da backup automatici
- ✅ Documentare la loro presenza al team
- ✅ Verificare che l'antivirus non li quarantini
- ❌ Non modificarli o cambiar loro permessi

## Troubleshooting

### Share Non Accessibile

```
WARN - Share non accessibile: \\server\share
```

**Cause**:
- Permessi insufficienti
- Share offline
- Problemi di rete
- Credenziali scadute

**Soluzione**:
```powershell
# Verifica accesso
Test-Path "\\server\share"

# Verifica credenziali
net use \\server\share /user:DOMAIN\user

# Test dettagliato
Get-SmbConnection
Get-SmbMapping
```

### Performance Issues

Se lo script impiega troppo tempo:

1. **Riduci MaxFilesToScan**
   ```json
   "MaxFilesToScan": 500
   ```

2. **Aumenta TimeWindowMinutes**
   ```json
   "TimeWindowMinutes": 60
   ```

3. **Disabilita EntropyCheck**
   ```json
   "EnableEntropyCheck": false
   ```

4. **Aggiungi ExcludePaths**
   ```json
   "ExcludePaths": ["Temp", "Cache", "Logs", "Backup"]
   ```

### Falsi Positivi

**Scenario**: Operazioni legittime (backup, sync) generano alert

**Soluzioni**:

1. **Aumenta AlertThreshold**
   ```json
   "AlertThreshold": 100
   ```

2. **Escludi directory di lavoro**
   ```json
   "ExcludePaths": ["BackupTemp", "SyncFolder"]
   ```

3. **Pianifica eccezioni temporanee**
   ```powershell
   # Durante manutenzione programmata
   Rename-Item ransomware_config.json ransomware_config.json.disabled
   ```

### Debug Mode

```powershell
# Abilita output dettagliato
.\check_ransomware_activity.ps1 -Debug

# Output tipico
[DEBUG] === Avvio Check Ransomware Activity ===
[DEBUG] Configurazione caricata da: ransomware_config.json
[DEBUG] Controllo modifiche dal: 2025-10-22 10:30:00
[DEBUG] Analisi share: \\fileserver\documents
[DEBUG] Scansione share: \\fileserver\documents (modifiche da: 2025-10-22 10:30:00)
[DEBUG] File scansionati: 150, Sospetti: 0
[DEBUG] Ransom notes trovate: 0
[DEBUG] === Check completato con stato: 0 ===
```

## Integrazione CheckMK

### Discovery Service

Dopo l'installazione, i servizi appariranno automaticamente:

- `Ransomware_Detection` - Servizio principale
- `Ransomware_Share_<nome>` - Un servizio per ogni share

### Configurazione Alert

**Setup.py (WATO)**:

```python
# Regola di notifica per ransomware
{
    'description': 'Ransomware Alert - Security Team',
    'disabled': False,
    'contact_selection': ['security_team'],
    'conditions': {
        'match_services': ['Ransomware_Detection'],
        'match_servicestates': [2],  # CRITICAL only
    },
    'notification_method': ('mail', {
        'subject': 'CRITICAL: Ransomware Activity Detected',
        'body': 'Immediate action required!',
    })
}
```

### Dashboard Widget

```python
# Aggiungi al dashboard custom
dashlet_config = {
    'type': 'view',
    'title': 'Ransomware Monitoring',
    'name': 'ransomware_detection',
    'datasource': 'services',
    'filters': {
        'service': 'Ransomware_*',
    },
    'columns': [
        'service_state',
        'service_description',
        'service_metrics',
        'service_plugin_output',
    ]
}
```

### Grafici Performance

Le metriche generate permettono grafici storici:

- Suspicious files trend
- Ransom notes detection over time
- Share availability
- Canary file alerts

## Sicurezza

### Permessi Minimi Richiesti

```
Account di servizio per CheckMK Agent:
├── DOMAIN\svc_checkmk
    ├── Read: Tutte le share monitorate
    ├── Write: Radice delle share (per canary files)
    └── Local: SeServiceLogonRight
```

### Hardening

1. **Esegui con account dedicato**
   ```powershell
   # Non usare Domain Admin!
   # Crea account con permessi minimi
   ```

2. **Proteggi config file**
   ```powershell
   icacls ransomware_config.json /inheritance:r
   icacls ransomware_config.json /grant "NT AUTHORITY\SYSTEM:(F)"
   icacls ransomware_config.json /grant "DOMAIN\svc_checkmk:(R)"
   ```

3. **Monitora lo script stesso**
   ```powershell
   # Usa file integrity monitoring per
   # check_ransomware_activity.ps1
   ```

### Audit Log

Lo script mantiene uno state file in `%TEMP%\ransomware_state.json`:

```json
{
  "LastCheck": "2025-10-22T11:00:00",
  "LastAlertTime": null,
  "CanaryFilesCreated": [
    "\\\\fileserver\\documents\\.ransomware_canary_do_not_delete.txt",
    "\\\\fileserver\\finance\\.ransomware_canary_do_not_delete.txt"
  ]
}
```

## Best Practices

### 1. Configurazione Iniziale

- ✅ Testa su una share non critica prima
- ✅ Monitora i log per una settimana
- ✅ Aggiusta soglie per ridurre falsi positivi
- ✅ Documenta baseline normale

### 2. Manutenzione

- 🔄 Review mensile delle estensioni ransomware
- 🔄 Aggiornamento pattern ransom notes
- 🔄 Verifica integrità canary files
- 🔄 Audit log degli alert generati

### 3. Response Plan

In caso di alert CRITICAL:

1. **Verifica immediata**
   ```powershell
   # Controlla i file sospetti
   Get-Content $StateFile | ConvertFrom-Json
   ```

2. **Isolamento**
   ```powershell
   # Disconnetti share se confermato
   net share documents /delete
   ```

3. **Backup verification**
   ```powershell
   # Verifica integrità backup offline
   ```

4. **Forensics**
   - Preserva state file
   - Cattura memory dump
   - Log eventi Windows

### 4. Testing

```powershell
# Test simulato (NON in produzione!)
# Crea file con estensione ransomware

# Share di test
$testShare = "\\testserver\testshare"
New-Item "$testShare\test.docx.locked" -ItemType File

# Esegui check
.\check_ransomware_activity.ps1 -SharePaths @($testShare) -Debug

# Cleanup
Remove-Item "$testShare\test.docx.locked"
```

## Limitazioni

- ⚠️ **Performance**: Scansione di share molto grandi può richiedere tempo
- ⚠️ **False Positives**: Operazioni batch legittime possono generare alert
- ⚠️ **Zero-Day**: Non protegge da ransomware completamente nuovi
- ⚠️ **Encrypted Channels**: Non rileva ransomware che usa crittografia lenta

## Roadmap

Funzionalità pianificate:

- [ ] Integrazione Machine Learning per pattern detection
- [ ] Analisi entropia avanzata su campioni random
- [ ] Integrazione SIEM per correlation
- [ ] Auto-snapshot VSS al rilevamento
- [ ] Webhook notifications (Teams, Slack)
- [ ] Quarantena automatica file sospetti
- [ ] Behavioral analysis (velocità scrittura)

## Supporto

Per problemi o domande:

1. Verifica log con `-Debug`
2. Controlla permessi share
3. Valida configurazione JSON
4. Testa connectivity alle share

## Changelog

### v1.0 (2025-10-22)
- ✨ Rilascio iniziale
- ✨ Canary files detection
- ✨ Ransom notes detection
- ✨ Mass modification analysis
- ✨ CheckMK integration
- ✨ Configurazione JSON
- ✨ State persistence

## License

Script sviluppato per uso interno con CheckMK.

## Credits

- Ransomware extension database: ID Ransomware, No More Ransom Project
- CheckMK integration patterns
- PowerShell best practices

---

**⚠️ IMPORTANTE**: Questo script è uno strumento di rilevamento, NON una protezione completa. 
Implementa sempre una strategia di difesa a livelli:
- Backup offline regolari
- Antivirus/EDR aggiornati
- Patching sistematico
- Formazione utenti
- Network segmentation
- Least privilege access
