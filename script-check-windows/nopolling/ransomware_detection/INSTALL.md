# File da Copiare sul Windows Server

## 📁 Tutti i File Necessari

Nella directory `script-check-windows\nopolling\ransomware_detection\` trovi:

### Versione Locale (consigliata per ambienti senza Internet)
1. **`check_ransomware_activity.ps1`** - Script principale PowerShell
2. **`ransomware_config.json`** - File di configurazione

### Versione Remote (consigliata per aggiornamenti automatici)
1. **`rcheck_ransomware_activity.ps1`** - Wrapper che scarica l'ultima versione da GitHub
2. **`ransomware_config.json`** - File di configurazione

> 💡 **La versione Remote** scarica sempre l'ultima versione dello script da GitHub con cache di 1 ora, ideale per mantenere aggiornato il controllo senza deployment manuale.

## 🚀 Installazione Rapida - Versione Remote (Raccomandata)

### Sul Windows Server (come Amministratore):

**Opzione A - Versione Remote (aggiornamenti automatici da GitHub):**
```powershell
# 1. Copia solo 2 file nella directory CheckMK Agent
$dest = "C:\ProgramData\checkmk\agent\local"

# Scarica direttamente da GitHub
$remoteUrl = "https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-check-windows/nopolling/ransomware_detection/rcheck_ransomware_activity.ps1"
$configUrl = "https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-check-windows/nopolling/ransomware_detection/ransomware_config.json"

Invoke-WebRequest -Uri $remoteUrl -OutFile "$dest\rcheck_ransomware_activity.ps1" -UseBasicParsing
Invoke-WebRequest -Uri $configUrl -OutFile "$dest\ransomware_config.json" -UseBasicParsing

# 2. Configura le tue share
notepad "$dest\ransomware_config.json"
# Modifica "SharePaths": ["\\\\TUO-SERVER\\tua-share"]

# 3. Test
cd $dest
.\rcheck_ransomware_activity.ps1

# 4. Riavvia CheckMK Agent
Restart-Service CheckMkService
```

**Opzione B - Versione Locale (per server senza Internet):**
```powershell
# 1. Copia i file dalla tua workstation
$dest = "C:\ProgramData\checkmk\agent\local"

Copy-Item "check_ransomware_activity.ps1" $dest
Copy-Item "ransomware_config.json" $dest

# 2. Modifica la configurazione con le tue share
notepad "$dest\ransomware_config.json"

# 3. Test manuale
cd $dest
.\check_ransomware_activity.ps1

# 4. Riavvia CheckMK Agent
Restart-Service CheckMkService
```

## 📋 Oppure Usa l'Installazione Automatica

Dalla directory principale `script-check-windows\`:

```cmd
REM Esegui come Amministratore
install_ransomware_detection.bat
```

Lo script automatico:
- ✅ Trova automaticamente CheckMK Agent
- ✅ Copia tutti i file necessari
- ✅ Ti chiede se configurare le share
- ✅ Testa il funzionamento
- ✅ Riavvia il servizio

## ⚙️ Configurazione Share

Modifica `ransomware_config.json`:

```json
{
  "SharePaths": [
    "\\\\WS2022AD\\test00",
    "\\\\fileserver\\documents",
    "\\\\backup\\critical"
  ],
  "TimeWindowMinutes": 30,
  "AlertThreshold": 50,
  "EnableCanaryFiles": true
}
```

**IMPORTANTE:** 
- NON mettere virgola dopo l'ultimo elemento dell'array
- Usa doppie backslash `\\\\` per i path UNC

## ✅ Verifica Funzionamento

```powershell
# Test output
cd "C:\ProgramData\checkmk\agent\local"
.\check_ransomware.bat

# Output atteso:
# <<<local>>>
# 0 Ransomware_Detection suspicious_files=0|ransom_notes=0...
```

## 🌐 Discovery in CheckMK

1. **Setup → Hosts** → [tuo-host] → **"Services"**
2. **"Full service scan"**
3. Rimuovi eventuali servizi vecchi in stato UNKNOWN
4. **"Accept all"** per i nuovi servizi
5. **"Activate changes"**

Dopo 2-3 minuti dovresti vedere:
- 🟢 `Ransomware_Detection` - OK
- 🟢 `Ransomware_Share_...` - OK

## 🐛 Troubleshooting

### Servizio resta UNKNOWN
```powershell
# Pulisci cache e riavvia
Stop-Service CheckMkService
Remove-Item "C:\ProgramData\checkmk\agent\cache\*" -Force -Recurse -ErrorAction SilentlyContinue
Start-Service CheckMkService
```

### Script non si esegue
```powershell
# Verifica ExecutionPolicy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine -Force

# Usa il wrapper BAT (raccomandato)
.\check_ransomware.bat
```

### JSON non valido
- Rimuovi virgole finali negli array
- Usa `\\\\` per path UNC
- Verifica sintassi su https://jsonlint.com/

---

**Tutto pronto!** Copia questi 3 file sul server e segui i passaggi sopra. 🚀
