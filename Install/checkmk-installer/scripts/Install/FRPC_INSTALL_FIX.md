# Fix per Errori Configurazione FRPC - install-agent-interactive.ps1

## Problemi Identificati

### 1. **NSSM in uso durante l'installazione**
- Il file `nssm.exe` può essere bloccato da processi esistenti
- La rimozione/copia fallisce se il servizio è ancora attivo
- Timeout insufficienti tra stop e rimozione servizio

### 2. **Permessi directory configurazione**
- SYSTEM potrebbe non avere accesso alla directory `C:\ProgramData\frp`
- File TOML potrebbe non essere leggibile dal servizio

### 3. **Avvio servizio con timeout brevi**
- 5 secondi di attesa potrebbero non essere sufficienti
- Servizio potrebbe avviarsi ma poi crashare

### 4. **Path TOML con backslash**
- I path Windows con `\` nel TOML potrebbero essere interpretati come escape
- Mancano doppi backslash o conversione a forward slash

### 5. **Validazione configurazione assente**
- Nessuna verifica che il file TOML sia sintatticamente corretto
- Nessun test di connettività FRPC prima di creare il servizio

### 6. **Log non consultabili**
- I log di NSSM potrebbero non essere creati correttamente
- Difficile diagnosticare errori di avvio

## Soluzioni Implementate

### Fix 1: Gestione NSSM Robusta
```powershell
# Arresta TUTTI i servizi che potrebbero usare NSSM
Get-Service | Where-Object { $_.Status -eq 'Running' -and $_.Name -like '*frp*' } | Stop-Service -Force
Start-Sleep -Seconds 5

# Termina eventuali processi NSSM residui
Get-Process -Name "nssm" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# Rimuovi e ricrea la directory se necessario
if (Test-Path $nssmInstallPath) {
    takeown /F "$nssmInstallPath" /A
    icacls "$nssmInstallPath" /grant Administrators:F
    Remove-Item -Path $nssmInstallPath -Force
}
```

### Fix 2: Path TOML Corretti
```powershell
# Usa forward slash nei path per TOML
$tomlConfig = @"
[common]
server_addr = "$frpServer"
server_port = 7000
auth.method = "token"
auth.token  = "$authToken"
tls.enable = true
log.to = "$($FRPC_LOG_DIR -replace '\\', '/')/frpc.log"
log.level = "info"
log.maxDays = 3

[$frpcHostname]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $remotePort
"@
```

### Fix 3: Validazione Configurazione
```powershell
# Test sintassi TOML prima di creare servizio
Write-Host "`n[*] Validazione configurazione TOML..." -ForegroundColor Yellow
try {
    $testOutput = & "$frpcPath" verify -c "$tomlFile" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    [ERR] Configurazione TOML non valida:" -ForegroundColor Red
        Write-Host "    $testOutput" -ForegroundColor Yellow
        return $false
    }
    Write-Host "    [OK] Configurazione TOML valida" -ForegroundColor Green
}
catch {
    Write-Host "    [WARN] Impossibile validare TOML (frpc verify non disponibile)" -ForegroundColor Yellow
}
```

### Fix 4: Permessi Corretti
```powershell
# Imposta permessi completi su directory e file
$paths = @($FRPC_CONFIG_DIR, $FRPC_LOG_DIR, $FRPC_INSTALL_DIR)
foreach ($path in $paths) {
    if (Test-Path $path) {
        icacls "$path" /grant "SYSTEM:(OI)(CI)F" /T /C /Q
        icacls "$path" /grant "Administrators:(OI)(CI)F" /T /C /Q
    }
}

# Permessi specifici sul file TOML
icacls "$tomlFile" /grant "SYSTEM:F" /C /Q
```

### Fix 5: Avvio Servizio con Retry Robusto
```powershell
# Avvio con retry e diagnostica migliorata
$maxRetries = 10
$retryCount = 0
$serviceRunning = $false

While ($retryCount -lt $maxRetries -and -not $serviceRunning) {
    $retryCount++
    Write-Host "    [*] Tentativo avvio $retryCount/$maxRetries..." -ForegroundColor Yellow
    
    try {
        Start-Service -Name "frpc" -ErrorAction Stop
        Start-Sleep -Seconds 8
        
        $frpcService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($frpcService.Status -eq "Running") {
            # Verifica che il processo sia effettivamente attivo
            $frpcProcess = Get-Process -Name "frpc" -ErrorAction SilentlyContinue
            if ($frpcProcess) {
                Write-Host "    [OK] Servizio FRPC avviato (PID: $($frpcProcess.Id))" -ForegroundColor Green
                $serviceRunning = $true
            }
            else {
                Write-Host "    [WARN] Servizio running ma processo non trovato" -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "    [WARN] Servizio stato: $($frpcService.Status)" -ForegroundColor Yellow
            
            # Leggi log errori NSSM
            if (Test-Path "$FRPC_LOG_DIR\nssm-stderr.log") {
                $stderr = Get-Content "$FRPC_LOG_DIR\nssm-stderr.log" -Tail 10 -ErrorAction SilentlyContinue
                if ($stderr) {
                    Write-Host "    [DEBUG] Ultimi errori:" -ForegroundColor Gray
                    $stderr | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }
                }
            }
        }
    }
    catch {
        Write-Host "    [WARN] Errore: $_" -ForegroundColor Yellow
    }
    
    if (-not $serviceRunning -and $retryCount -lt $maxRetries) {
        Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }
}
```

### Fix 6: Diagnostica Avanzata
```powershell
function Show-FRPCDiagnostics {
    Write-Host "`n[INFO] Diagnostica FRPC:" -ForegroundColor Cyan
    
    # Verifica file configurazione
    if (Test-Path $tomlFile) {
        Write-Host "    ✓ File config: $tomlFile" -ForegroundColor Green
        $tomlSize = (Get-Item $tomlFile).Length
        Write-Host "      Dimensione: $tomlSize bytes" -ForegroundColor Gray
    }
    else {
        Write-Host "    ✗ File config non trovato!" -ForegroundColor Red
    }
    
    # Verifica eseguibile
    if (Test-Path $frpcPath) {
        Write-Host "    ✓ Eseguibile: $frpcPath" -ForegroundColor Green
        try {
            $version = & "$frpcPath" version 2>&1 | Select-Object -First 1
            Write-Host "      Versione: $version" -ForegroundColor Gray
        }
        catch {
            Write-Host "      Versione: non disponibile" -ForegroundColor Gray
        }
    }
    else {
        Write-Host "    ✗ Eseguibile non trovato!" -ForegroundColor Red
    }
    
    # Verifica servizio
    $service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "    ✓ Servizio: $($service.Status)" -ForegroundColor Green
        Write-Host "      StartType: $($service.StartType)" -ForegroundColor Gray
    }
    else {
        Write-Host "    ✗ Servizio non registrato!" -ForegroundColor Red
    }
    
    # Verifica permessi
    $acl = Get-Acl $FRPC_CONFIG_DIR -ErrorAction SilentlyContinue
    if ($acl) {
        $systemAccess = $acl.Access | Where-Object { $_.IdentityReference -like "*SYSTEM*" }
        if ($systemAccess) {
            Write-Host "    ✓ Permessi SYSTEM: $($systemAccess.FileSystemRights)" -ForegroundColor Green
        }
        else {
            Write-Host "    ✗ SYSTEM non ha permessi sulla directory!" -ForegroundColor Red
        }
    }
    
    # Mostra ultimi log se disponibili
    $logFile = "$FRPC_LOG_DIR\frpc.log"
    if (Test-Path $logFile) {
        Write-Host "`n    [LOG] Ultimi 15 righe di frpc.log:" -ForegroundColor Cyan
        Get-Content $logFile -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Host "      $_" -ForegroundColor Gray
        }
    }
    
    # Comandi utili
    Write-Host "`n    [INFO] Comandi diagnostici:" -ForegroundColor Cyan
    Write-Host "      Test manuale: & '$frpcPath' -c '$tomlFile'" -ForegroundColor Yellow
    Write-Host "      Verifica config: & '$frpcPath' verify -c '$tomlFile'" -ForegroundColor Yellow
    Write-Host "      Log servizio: Get-EventLog -LogName System -Source 'Service Control Manager' -Newest 10 | Where-Object { `$_.Message -like '*frpc*' }" -ForegroundColor Yellow
}
```

## Script di Fix Rapido

Crea un file `fix-frpc-config.ps1` con il seguente contenuto per applicare i fix:

```powershell
#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"
$FRPC_INSTALL_DIR = "C:\frp"
$FRPC_CONFIG_DIR = "C:\ProgramData\frp"
$FRPC_LOG_DIR = "C:\ProgramData\frp\logs"

Write-Host "`n[*] Fix Configurazione FRPC in corso...`n" -ForegroundColor Cyan

# 1. Arresta servizio
Write-Host "[*] Arresto servizio FRPC..." -ForegroundColor Yellow
Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

# 2. Termina processi residui
Get-Process -Name "frpc" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "nssm" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

# 3. Fix permessi
Write-Host "[*] Correzione permessi..." -ForegroundColor Yellow
$paths = @($FRPC_CONFIG_DIR, $FRPC_LOG_DIR, $FRPC_INSTALL_DIR)
foreach ($path in $paths) {
    if (Test-Path $path) {
        icacls "$path" /grant "SYSTEM:(OI)(CI)F" /T /C /Q | Out-Null
        icacls "$path" /grant "Administrators:(OI)(CI)F" /T /C /Q | Out-Null
        Write-Host "    [OK] Permessi aggiornati: $path" -ForegroundColor Green
    }
}

# 4. Fix path nel TOML
$tomlFile = "$FRPC_CONFIG_DIR\frpc.toml"
if (Test-Path $tomlFile) {
    Write-Host "[*] Correzione path nel file TOML..." -ForegroundColor Yellow
    $tomlContent = Get-Content $tomlFile -Raw
    
    # Sostituisci backslash con forward slash nei path
    $tomlContent = $tomlContent -replace '\\\\', '/'
    $tomlContent = $tomlContent -replace '\\', '/'
    
    Set-Content -Path $tomlFile -Value $tomlContent -Force
    Write-Host "    [OK] TOML corretto" -ForegroundColor Green
}

# 5. Ricrea directory log se mancante
if (-not (Test-Path $FRPC_LOG_DIR)) {
    New-Item -ItemType Directory -Path $FRPC_LOG_DIR -Force | Out-Null
    Write-Host "    [OK] Directory log ricreata" -ForegroundColor Green
}

# 6. Tenta avvio servizio
Write-Host "`n[*] Tentativo avvio servizio..." -ForegroundColor Yellow
try {
    Start-Service -Name "frpc" -ErrorAction Stop
    Start-Sleep -Seconds 8
    
    $service = Get-Service -Name "frpc"
    if ($service.Status -eq "Running") {
        Write-Host "    [OK] Servizio FRPC avviato correttamente!" -ForegroundColor Green
        
        # Mostra log
        Start-Sleep -Seconds 3
        if (Test-Path "$FRPC_LOG_DIR\frpc.log") {
            Write-Host "`n[LOG] Ultimi eventi:" -ForegroundColor Cyan
            Get-Content "$FRPC_LOG_DIR\frpc.log" -Tail 10 | ForEach-Object {
                Write-Host "    $_" -ForegroundColor Gray
            }
        }
    }
    else {
        Write-Host "    [WARN] Servizio non running: $($service.Status)" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "    [ERR] Errore avvio: $_" -ForegroundColor Red
    
    # Mostra log errori
    if (Test-Path "$FRPC_LOG_DIR\nssm-stderr.log") {
        Write-Host "`n[ERR] Log errori NSSM:" -ForegroundColor Red
        Get-Content "$FRPC_LOG_DIR\nssm-stderr.log" -Tail 20 | ForEach-Object {
            Write-Host "    $_" -ForegroundColor Yellow
        }
    }
}

Write-Host "`n[*] Fix completato. Verifica stato servizio con: Get-Service -Name 'frpc'`n" -ForegroundColor Cyan
```

## Test Manuale FRPC

Per testare FRPC senza servizio Windows:

```powershell
# Naviga nella directory
cd C:\frp

# Test configurazione
.\frpc.exe verify -c "C:\ProgramData\frp\frpc.toml"

# Test connessione (modalità interattiva - CTRL+C per uscire)
.\frpc.exe -c "C:\ProgramData\frp\frpc.toml"

# Se funziona in modalità interattiva ma non come servizio,
# il problema è nei permessi o nella configurazione NSSM
```

## Checklist Diagnostica

Quando l'installazione FRPC fallisce, verifica nell'ordine:

- [ ] **File configurazione esiste**: `Test-Path C:\ProgramData\frp\frpc.toml`
- [ ] **Eseguibile esiste**: `Test-Path C:\frp\frpc.exe`
- [ ] **Permessi SYSTEM**: `icacls C:\ProgramData\frp`
- [ ] **Servizio registrato**: `Get-Service -Name 'frpc'`
- [ ] **TOML sintatticamente corretto**: `.\frpc.exe verify -c "C:\ProgramData\frp\frpc.toml"`
- [ ] **Connettività server FRP**: `Test-NetConnection monitor.nethlab.it -Port 7000`
- [ ] **Test manuale funziona**: `.\frpc.exe -c "C:\ProgramData\frp\frpc.toml"` (deve rimanere in esecuzione)
- [ ] **Log NSSM**: `Get-Content C:\ProgramData\frp\logs\nssm-stderr.log -Tail 50`
- [ ] **Log FRPC**: `Get-Content C:\ProgramData\frp\logs\frpc.log -Tail 50`
- [ ] **Event Log Windows**: `Get-EventLog -LogName System -Source 'Service Control Manager' -Newest 20 | Where-Object { $_.Message -like '*frpc*' }`

## Errori Comuni e Soluzioni

### 1. "Impossibile avviare il servizio" (Error 1053)
**Causa**: Timeout avvio servizio troppo breve
**Soluzione**:
```powershell
sc.exe config frpc start= delayed-auto
sc.exe failure frpc reset= 86400 actions= restart/5000/restart/10000/restart/30000
```

### 2. "Access Denied" nei log
**Causa**: SYSTEM non ha permessi
**Soluzione**:
```powershell
icacls "C:\ProgramData\frp" /grant "SYSTEM:(OI)(CI)F" /T
```

### 3. "Config file not found"
**Causa**: Path con backslash non corretto
**Soluzione**: Usa forward slash nel TOML: `log.to = "C:/ProgramData/frp/logs/frpc.log"`

### 4. "Connection refused" o "dial tcp timeout"
**Causa**: Server FRP non raggiungibile o firewall
**Soluzione**:
```powershell
Test-NetConnection monitor.nethlab.it -Port 7000
netsh advfirewall firewall add rule name="FRPC Outbound" dir=out action=allow protocol=TCP remoteport=7000
```

### 5. Servizio si avvia e poi si ferma immediatamente
**Causa**: Errore nella configurazione TOML (token errato, porta in uso, etc.)
**Soluzione**: Esegui test manuale per vedere l'errore esatto:
```powershell
cd C:\frp
.\frpc.exe -c "C:\ProgramData\frp\frpc.toml"
```

## File Completo Aggiornato

Il file `install-agent-interactive-v1.2-FIXED.ps1` implementa tutte queste correzioni ed è pronto all'uso.
