# Esempi Pratici - Ransomware Detection

## Scenario 1: Setup Base per File Server

### Configurazione

**File:** `ransomware_config.json`

```json
{
  "SharePaths": [
    "\\\\fileserver\\documents",
    "\\\\fileserver\\shared"
  ],
  "TimeWindowMinutes": 30,
  "AlertThreshold": 50,
  "EnableCanaryFiles": true,
  "MaxFilesToScan": 1000
}
```

### Test

```powershell
# Test esecuzione
.\check_ransomware_activity.ps1 -Debug

# Output atteso
[DEBUG] === Avvio Check Ransomware Activity ===
[DEBUG] Configurazione caricata da: ransomware_config.json
[DEBUG] Analisi share: \\fileserver\documents
[DEBUG] Canary file creato: \\fileserver\documents\.ransomware_canary_do_not_delete.txt
[DEBUG] File scansionati: 245, Sospetti: 0
[DEBUG] === Check completato con stato: 0 ===

<<<local>>>
0 Ransomware_Detection suspicious_files=0|ransom_notes=0|canary_alerts=0|shares_ok=2 OK - Nessuna attività sospetta rilevata su 2/2 shares
0 Ransomware_Share_fileserver_documents suspicious=0|notes=0 OK
0 Ransomware_Share_fileserver_shared suspicious=0|notes=0 OK
```

---

## Scenario 2: Alert Reale - File Crittografati

### Simulazione (SOLO AMBIENTE TEST!)

```powershell
# ATTENZIONE: Eseguire SOLO in test environment!

# Crea directory test
$testShare = "C:\TestShare"
New-Item -Path $testShare -ItemType Directory -Force

# Simula file crittografati
1..60 | ForEach-Object {
    $filename = "document_$_.pdf.locked"
    "Encrypted content" | Set-Content "$testShare\$filename"
}

# Esegui check
.\check_ransomware_activity.ps1 -SharePaths @($testShare) -AlertThreshold 50
```

### Output Atteso

```
<<<local>>>
2 Ransomware_Detection suspicious_files=60|ransom_notes=0|canary_alerts=0|shares_ok=1 ALERT: Attività di crittografia massiva rilevata (60 files) | Top files: document_1.pdf.locked (score: 10), document_2.pdf.locked (score: 10), document_3.pdf.locked (score: 10)
2 Ransomware_ShareC_TestShare suspicious=60|notes=0 CRIT - Suspicious files: 60
```

### Azioni Immediate

1. **Verifica in CheckMK:**
   - Servizio diventa CRITICAL (rosso)
   - Notifica inviata a security team

2. **Investigazione:**
   ```powershell
   # Controlla stato dettagliato
   Get-Content "$env:TEMP\ransomware_state.json" | ConvertFrom-Json | Format-List
   ```

3. **Response:**
   - Isola il sistema dalla rete
   - Preserva le evidenze
   - Notifica IR team
   - Verifica backup offline

---

## Scenario 3: Canary File Compromesso

### Cosa Succede

Il ransomware, nella sua attività indiscriminata, modifica/elimina il canary file nascosto:

```
\\fileserver\documents\.ransomware_canary_do_not_delete.txt
```

### Detection

```powershell
# Script rileva automaticamente
.\check_ransomware_activity.ps1
```

### Output

```
<<<local>>>
2 Ransomware_Detection suspicious_files=0|ransom_notes=0|canary_alerts=1|shares_ok=2 ALERT: Canary file compromessi (1)
2 Ransomware_Share_fileserver_documents suspicious=0|notes=0 CRIT - Canary file modified
```

### Verifica Manuale

```powershell
# Verifica esistenza canary
$canary = "\\fileserver\documents\.ransomware_canary_do_not_delete.txt"
Get-Item $canary -Force | Format-List FullName, LastWriteTime, Attributes

# Se manca o modificato recentemente = ALERT!
```

---

## Scenario 4: Ransom Note Rilevata

### Simulazione Test

```powershell
# SOLO TEST ENVIRONMENT!
$testShare = "C:\TestShare"

# Crea ransom note tipica
@"
YOUR FILES HAVE BEEN ENCRYPTED!

All your important files have been encrypted with military-grade cryptography.
To decrypt your files you need to purchase the decryption key.

Price: 0.5 Bitcoin (BTC)
Payment address: bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh

After payment, contact us at: ransomware@darkweb.onion

Don't try to decrypt files yourself - you will damage them permanently!
"@ | Set-Content "$testShare\README_DECRYPT.txt"

# Esegui check
.\check_ransomware_activity.ps1 -SharePaths @($testShare)
```

### Output

```
<<<local>>>
2 Ransomware_Detection suspicious_files=0|ransom_notes=1|canary_alerts=0|shares_ok=1 ALERT: Ransom notes rilevate (1)
2 Ransomware_ShareC_TestShare suspicious=0|notes=1 CRIT - Ransom notes: 1
```

---

## Scenario 5: Monitoraggio Multi-Share Enterprise

### Configurazione Avanzata

```json
{
  "SharePaths": [
    "\\\\fs01\\documents",
    "\\\\fs01\\finance",
    "\\\\fs02\\engineering",
    "\\\\fs02\\hr",
    "\\\\backup\\critical",
    "C:\\SharedData"
  ],
  "TimeWindowMinutes": 15,
  "AlertThreshold": 100,
  "EnableCanaryFiles": true,
  "MaxFilesToScan": 2000,
  "ExcludePaths": [
    "$RECYCLE.BIN",
    "System Volume Information",
    "Temp",
    "Cache",
    "BackupTemp",
    ".git"
  ]
}
```

### Esecuzione

```powershell
# Check tutte le share
.\check_ransomware_activity.ps1
```

### Output Tipico (tutto OK)

```
<<<local>>>
0 Ransomware_Detection suspicious_files=0|ransom_notes=0|canary_alerts=0|shares_ok=6 OK - Nessuna attività sospetta rilevata su 6/6 shares
0 Ransomware_Share_fs01_documents suspicious=0|notes=0 OK
0 Ransomware_Share_fs01_finance suspicious=0|notes=0 OK
0 Ransomware_Share_fs02_engineering suspicious=0|notes=0 OK
0 Ransomware_Share_fs02_hr suspicious=0|notes=0 OK
0 Ransomware_Share_backup_critical suspicious=0|notes=0 OK
0 Ransomware_ShareC_SharedData suspicious=0|notes=0 OK
```

### Dashboard CheckMK

Crea widget custom per overview:

- **Status Overview:** Tutti i servizi Ransomware_*
- **Metrics Graph:** suspicious_files trend
- **Alert Count:** ransom_notes + canary_alerts

---

## Scenario 6: Performance Tuning per Share Grande

### Problema

Share con milioni di file, script troppo lento:

```powershell
Measure-Command { .\check_ransomware_activity.ps1 }
# Output: TotalMinutes: 5.2  ← TROPPO LENTO!
```

### Soluzione 1: Limita File Scansionati

```json
{
  "MaxFilesToScan": 500,
  "TimeWindowMinutes": 60
}
```

### Soluzione 2: Escludi Directory Non Critiche

```json
{
  "ExcludePaths": [
    "Archives",
    "Old_Data",
    "Temp",
    "Logs",
    "Cache",
    "Downloads"
  ]
}
```

### Verifica Performance

```powershell
Measure-Command { .\check_ransomware_activity.ps1 }
# Output: TotalMinutes: 0.5  ← OK!
```

---

## Scenario 7: Falsi Positivi - Backup Notturno

### Problema

Backup automatico notturno modifica molti file:

```
02:15 - ALERT: Attività di crittografia massiva rilevata (250 files)
```

Ma è solo il backup legittimo!

### Soluzione 1: Esclusione Directory Backup

```json
{
  "ExcludePaths": [
    "BackupTemp",
    "VeeamBackup",
    "ShadowCopy"
  ]
}
```

### Soluzione 2: Soglia Più Alta di Notte

Script avanzato con scheduling:

```powershell
# In check_ransomware_activity.ps1, aggiungi:

$hour = (Get-Date).Hour

# Soglia variabile per ora del giorno
if ($hour -ge 22 -or $hour -le 6) {
    # Notte: soglia più alta (backup in corso)
    $AlertThreshold = 500
} else {
    # Giorno: soglia normale
    $AlertThreshold = 50
}
```

---

## Scenario 8: Integrazione con Incident Response

### Workflow Completo

**1. Detection (Automatico)**
```
CheckMK rileva → Ransomware_Detection = CRITICAL
```

**2. Alert (Automatico)**
```
Telegram → Security Team
Email → IT Admins, Management
```

**3. Response (Manuale)**

```powershell
# A. Genera report dettagliato
.\generate_ransomware_report.ps1 -OutputFormat HTML -OutputFile "C:\IR\ransomware_report_$(Get-Date -Format 'yyyyMMdd_HHmmss').html"

# B. Preserva evidenze
Copy-Item "$env:TEMP\ransomware_state.json" "C:\IR\evidence\"

# C. Isola sistema (se confermato)
# Disabilita share
Get-SmbShare | Where-Object { $_.Name -notin @('ADMIN$', 'C$', 'IPC$') } | Remove-SmbShare -Force

# Disconnetti da rete (estrema urgenza)
Disable-NetAdapter -Name "Ethernet" -Confirm:$false
```

**4. Investigation**

```powershell
# Analizza file sospetti
Get-ChildItem "\\fileserver\documents" -Recurse -File |
    Where-Object { $_.Extension -in @('.locked', '.encrypted') } |
    Select-Object FullName, LastWriteTime, Length |
    Export-Csv "C:\IR\suspicious_files.csv"

# Timeline eventi
Get-WinEvent -LogName Security -MaxEvents 1000 |
    Where-Object { $_.TimeCreated -gt (Get-Date).AddHours(-2) } |
    Export-Csv "C:\IR\security_events.csv"
```

**5. Recovery**

- Verifica backup offline
- Ripristina da backup pre-infezione
- Re-scan con antivirus aggiornato
- Cambio password tutti gli account

---

## Scenario 9: Test Completo Pre-Deploy

### Checklist

```powershell
# 1. Installazione
.\install_ransomware_detection.bat

# 2. Configurazione
notepad "C:\Program Files (x86)\checkmk\service\local\ransomware_config.json"

# 3. Test funzionalità base
cd "C:\Program Files (x86)\checkmk\service\local"
.\check_ransomware_activity.ps1 -Debug

# 4. Test suite completa
.\test_ransomware_detection.ps1 -TestScenario All

# 5. Verifica canary files
Get-ChildItem "\\fileserver\*" -Hidden -Recurse -Filter ".ransomware_canary*"

# 6. Test alert (simula CRITICAL)
# Modifica temporaneamente un canary file
$canary = "\\fileserver\documents\.ransomware_canary_do_not_delete.txt"
$file = Get-Item $canary -Force
$file.Attributes = 'Normal'
"MODIFIED" | Add-Content $canary
.\check_ransomware_activity.ps1

# 7. Verifica in CheckMK
# - Service discovery
# - Stato servizi
# - Grafici metriche

# 8. Test notifiche
# - Telegram inviato?
# - Email ricevuta?
# - Alert visibile in dashboard?

# 9. Cleanup test
# Ripristina canary file
# Verifica stato OK

# 10. Documentazione
# - Procedure IR aggiornate?
# - Team informato?
# - Contatti verificati?
```

---

## Troubleshooting Comune

### Problema: Share non accessibile

```powershell
# Diagnosi
Test-Path "\\fileserver\documents"  # False

# Fix: Verifica credenziali
net use \\fileserver\documents /user:DOMAIN\svc_checkmk

# Verifica permanente
Get-SmbMapping
```

### Problema: Script non produce output

```powershell
# Verifica esecuzione
powershell.exe -ExecutionPolicy Bypass -File check_ransomware_activity.ps1 -Debug

# Verifica encoding
Get-Content check_ransomware_activity.ps1 -Raw | Format-Hex | Select-Object -First 20

# Fix encoding se necessario
Get-Content check_ransomware_activity.ps1 | Set-Content -Encoding UTF8 check_ransomware_activity_fixed.ps1
```

### Problema: Troppi falsi positivi

```powershell
# Analizza pattern
Get-Content "$env:TEMP\ransomware_state.json" | ConvertFrom-Json

# Adatta configurazione
# Aumenta AlertThreshold
# Aggiungi ExcludePaths
# Aumenta TimeWindowMinutes
```

---

**Fine Esempi Pratici**

Per ulteriori informazioni:
- `README-Ransomware-Detection.md` - Documentazione completa
- `QUICK_START.md` - Setup rapido
- `test_ransomware_detection.ps1` - Suite di test
