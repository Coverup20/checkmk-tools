#!/usr/bin/env powershell
# ============================================================
# Fix Rapido Configurazione FRPC
# Corregge problemi comuni di permessi, path e avvio servizio
# Version: 1.0 - 2025-11-14
# ============================================================

#Requires -RunAsAdministrator
#Requires -Version 5.0

$ErrorActionPreference = "Continue"

# Configuration
$FRPC_INSTALL_DIR = "C:\frp"
$FRPC_CONFIG_DIR = "C:\ProgramData\frp"
$FRPC_LOG_DIR = "C:\ProgramData\frp\logs"
$tomlFile = "$FRPC_CONFIG_DIR\frpc.toml"
$frpcPath = "$FRPC_INSTALL_DIR\frpc.exe"

Write-Host "`n====================================================================" -ForegroundColor Cyan
Write-Host "FIX CONFIGURAZIONE FRPC" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

# =====================================================
# Verifica Administrator
# =====================================================
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "`n[ERR] Questo script deve essere eseguito come Administrator" -ForegroundColor Red
    exit 1
}

# =====================================================
# 1. Arresta servizio e processi
# =====================================================
Write-Host "`n[*] Step 1: Arresto servizio e processi..." -ForegroundColor Yellow

$service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
if ($service) {
    if ($service.Status -eq "Running") {
        Write-Host "    [*] Arresto servizio FRPC..." -ForegroundColor Cyan
        Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 5
        Write-Host "    [OK] Servizio arrestato" -ForegroundColor Green
    }
    else {
        Write-Host "    [OK] Servizio già arrestato" -ForegroundColor Green
    }
}
else {
    Write-Host "    [WARN] Servizio FRPC non trovato" -ForegroundColor Yellow
}

# Termina processi residui
Write-Host "    [*] Terminazione processi residui..." -ForegroundColor Cyan
$frpcProcesses = Get-Process -Name "frpc" -ErrorAction SilentlyContinue
if ($frpcProcesses) {
    $frpcProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "    [OK] Processi FRPC terminati" -ForegroundColor Green
}

$nssmProcesses = Get-Process -Name "nssm" -ErrorAction SilentlyContinue
if ($nssmProcesses) {
    $nssmProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "    [OK] Processi NSSM terminati" -ForegroundColor Green
}

Start-Sleep -Seconds 2

# =====================================================
# 2. Verifica file esistenti
# =====================================================
Write-Host "`n[*] Step 2: Verifica file e directory..." -ForegroundColor Yellow

$allFilesExist = $true

if (Test-Path $frpcPath) {
    Write-Host "    [OK] Eseguibile trovato: $frpcPath" -ForegroundColor Green
}
else {
    Write-Host "    [ERR] Eseguibile non trovato: $frpcPath" -ForegroundColor Red
    $allFilesExist = $false
}

if (Test-Path $tomlFile) {
    Write-Host "    [OK] File configurazione trovato: $tomlFile" -ForegroundColor Green
}
else {
    Write-Host "    [ERR] File configurazione non trovato: $tomlFile" -ForegroundColor Red
    $allFilesExist = $false
}

if (-not $allFilesExist) {
    Write-Host "`n[ERR] File necessari mancanti. Esegui prima l'installazione completa." -ForegroundColor Red
    exit 1
}

# Verifica/crea directory log
if (-not (Test-Path $FRPC_LOG_DIR)) {
    Write-Host "    [*] Creazione directory log..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $FRPC_LOG_DIR -Force | Out-Null
    Write-Host "    [OK] Directory log creata" -ForegroundColor Green
}
else {
    Write-Host "    [OK] Directory log esistente" -ForegroundColor Green
}

# =====================================================
# 3. Correzione permessi
# =====================================================
Write-Host "`n[*] Step 3: Correzione permessi..." -ForegroundColor Yellow

$paths = @($FRPC_CONFIG_DIR, $FRPC_LOG_DIR, $FRPC_INSTALL_DIR)
foreach ($path in $paths) {
    if (Test-Path $path) {
        Write-Host "    [*] Aggiornamento permessi: $path" -ForegroundColor Cyan
        
        try {
            # Usa icacls per permessi completi a SYSTEM e Administrators
            icacls "$path" /grant "SYSTEM:(OI)(CI)F" /T /C /Q 2>&1 | Out-Null
            icacls "$path" /grant "Administrators:(OI)(CI)F" /T /C /Q 2>&1 | Out-Null
            Write-Host "    [OK] Permessi aggiornati: $path" -ForegroundColor Green
        }
        catch {
            Write-Host "    [WARN] Errore permessi su $path : $_" -ForegroundColor Yellow
        }
    }
}

# Permessi specifici sul file TOML
if (Test-Path $tomlFile) {
    try {
        icacls "$tomlFile" /grant "SYSTEM:F" /C /Q 2>&1 | Out-Null
        Write-Host "    [OK] Permessi file TOML aggiornati" -ForegroundColor Green
    }
    catch {
        Write-Host "    [WARN] Errore permessi TOML: $_" -ForegroundColor Yellow
    }
}

# =====================================================
# 4. Correzione path nel file TOML
# =====================================================
Write-Host "`n[*] Step 4: Correzione path nel file TOML..." -ForegroundColor Yellow

if (Test-Path $tomlFile) {
    try {
        $tomlContent = Get-Content $tomlFile -Raw -ErrorAction Stop
        $originalContent = $tomlContent
        
        # Sostituisci backslash doppi con forward slash
        $tomlContent = $tomlContent -replace '\\\\', '/'
        # Sostituisci backslash singoli con forward slash
        $tomlContent = $tomlContent -replace '\\(?![\\/])', '/'
        
        # Verifica se ci sono stati cambiamenti
        if ($tomlContent -ne $originalContent) {
            # Backup del file originale
            $backupFile = "$tomlFile.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
            Copy-Item -Path $tomlFile -Destination $backupFile -Force
            Write-Host "    [OK] Backup creato: $backupFile" -ForegroundColor Green
            
            # Salva il file corretto
            Set-Content -Path $tomlFile -Value $tomlContent -Force -ErrorAction Stop
            Write-Host "    [OK] Path nel TOML corretti (backslash -> forward slash)" -ForegroundColor Green
        }
        else {
            Write-Host "    [OK] Path nel TOML già corretti" -ForegroundColor Green
        }
        
        # Mostra preview della configurazione
        Write-Host "`n    [INFO] Preview configurazione:" -ForegroundColor Cyan
        $tomlContent -split "`n" | Select-Object -First 12 | ForEach-Object {
            Write-Host "      $_" -ForegroundColor Gray
        }
    }
    catch {
        Write-Host "    [ERR] Errore correzione TOML: $_" -ForegroundColor Red
    }
}

# =====================================================
# 5. Validazione configurazione TOML
# =====================================================
Write-Host "`n[*] Step 5: Validazione configurazione..." -ForegroundColor Yellow

if (Test-Path $frpcPath) {
    try {
        # Verifica se frpc supporta il comando verify
        $verifyOutput = & "$frpcPath" verify -c "$tomlFile" 2>&1
        $verifyExitCode = $LASTEXITCODE
        
        if ($verifyExitCode -eq 0) {
            Write-Host "    [OK] Configurazione TOML valida" -ForegroundColor Green
        }
        else {
            Write-Host "    [WARN] Validazione TOML ha riportato errori:" -ForegroundColor Yellow
            $verifyOutput | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        }
    }
    catch {
        Write-Host "    [WARN] Comando verify non supportato (versione FRPC potrebbe non supportarlo)" -ForegroundColor Yellow
    }
}

# =====================================================
# 6. Verifica connettività server FRP
# =====================================================
Write-Host "`n[*] Step 6: Verifica connettività server FRP..." -ForegroundColor Yellow

if (Test-Path $tomlFile) {
    try {
        $tomlContent = Get-Content $tomlFile -Raw
        
        # Estrai server_addr dalla configurazione
        if ($tomlContent -match 'server_addr\s*=\s*"([^"]+)"') {
            $frpServer = $matches[1]
            
            # Estrai server_port
            $frpPort = 7000
            if ($tomlContent -match 'server_port\s*=\s*(\d+)') {
                $frpPort = [int]$matches[1]
            }
            
            Write-Host "    [*] Test connessione a $frpServer`:$frpPort ..." -ForegroundColor Cyan
            
            try {
                $connection = Test-NetConnection -ComputerName $frpServer -Port $frpPort -WarningAction SilentlyContinue
                
                if ($connection.TcpTestSucceeded) {
                    Write-Host "    [OK] Server FRP raggiungibile ($frpServer`:$frpPort)" -ForegroundColor Green
                }
                else {
                    Write-Host "    [WARN] Server FRP non raggiungibile - verifica firewall o connettività" -ForegroundColor Yellow
                }
            }
            catch {
                Write-Host "    [WARN] Impossibile testare connettività: $_" -ForegroundColor Yellow
            }
        }
    }
    catch {
        Write-Host "    [WARN] Impossibile leggere configurazione server" -ForegroundColor Yellow
    }
}

# =====================================================
# 7. Configurazione avanzata servizio
# =====================================================
Write-Host "`n[*] Step 7: Configurazione avanzata servizio..." -ForegroundColor Yellow

if ($service) {
    try {
        # Imposta avvio automatico ritardato
        Write-Host "    [*] Configurazione avvio automatico ritardato..." -ForegroundColor Cyan
        sc.exe config frpc start= delayed-auto 2>&1 | Out-Null
        Write-Host "    [OK] Avvio automatico ritardato configurato" -ForegroundColor Green
        
        # Configura azioni su fallimento (restart automatico)
        Write-Host "    [*] Configurazione azioni su fallimento..." -ForegroundColor Cyan
        sc.exe failure frpc reset= 86400 actions= restart/5000/restart/10000/restart/30000 2>&1 | Out-Null
        Write-Host "    [OK] Restart automatico configurato" -ForegroundColor Green
    }
    catch {
        Write-Host "    [WARN] Impossibile configurare opzioni avanzate: $_" -ForegroundColor Yellow
    }
}

# =====================================================
# 8. Tentativo avvio servizio
# =====================================================
Write-Host "`n[*] Step 8: Avvio servizio FRPC..." -ForegroundColor Yellow

if ($service) {
    $maxRetries = 3
    $retryCount = 0
    $serviceStarted = $false
    
    while ($retryCount -lt $maxRetries -and -not $serviceStarted) {
        $retryCount++
        Write-Host "    [*] Tentativo $retryCount/$maxRetries ..." -ForegroundColor Cyan
        
        try {
            Start-Service -Name "frpc" -ErrorAction Stop
            Start-Sleep -Seconds 10
            
            $service = Get-Service -Name "frpc" -ErrorAction Stop
            
            if ($service.Status -eq "Running") {
                # Verifica che il processo sia effettivamente attivo
                $frpcProcess = Get-Process -Name "frpc" -ErrorAction SilentlyContinue
                
                if ($frpcProcess) {
                    Write-Host "    [OK] Servizio FRPC avviato con successo! (PID: $($frpcProcess.Id))" -ForegroundColor Green
                    $serviceStarted = $true
                }
                else {
                    Write-Host "    [WARN] Servizio running ma processo non trovato" -ForegroundColor Yellow
                }
            }
            else {
                Write-Host "    [WARN] Servizio stato: $($service.Status)" -ForegroundColor Yellow
            }
        }
        catch {
            Write-Host "    [WARN] Errore avvio: $_" -ForegroundColor Yellow
        }
        
        if (-not $serviceStarted -and $retryCount -lt $maxRetries) {
            Write-Host "    [*] Arresto e retry..." -ForegroundColor Cyan
            Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
    }
    
    if (-not $serviceStarted) {
        Write-Host "    [ERR] Impossibile avviare il servizio automaticamente" -ForegroundColor Red
        Write-Host "    [INFO] Consultare i log per dettagli (vedi sezione 9)" -ForegroundColor Cyan
    }
}
else {
    Write-Host "    [ERR] Servizio FRPC non trovato - esegui prima l'installazione completa" -ForegroundColor Red
}

# =====================================================
# 9. Diagnostica e log
# =====================================================
Write-Host "`n[*] Step 9: Diagnostica finale..." -ForegroundColor Yellow

# Stato servizio
$service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "`n    [INFO] Stato servizio:" -ForegroundColor Cyan
    Write-Host "      Stato:     $($service.Status)" -ForegroundColor $(if ($service.Status -eq 'Running') { 'Green' } else { 'Yellow' })
    Write-Host "      StartType: $($service.StartType)" -ForegroundColor Gray
}

# Processi attivi
$frpcProcess = Get-Process -Name "frpc" -ErrorAction SilentlyContinue
if ($frpcProcess) {
    Write-Host "`n    [INFO] Processo FRPC:" -ForegroundColor Cyan
    Write-Host "      PID:       $($frpcProcess.Id)" -ForegroundColor Gray
    Write-Host "      CPU:       $($frpcProcess.CPU)" -ForegroundColor Gray
    Write-Host "      Memory:    $([math]::Round($frpcProcess.WorkingSet64 / 1MB, 2)) MB" -ForegroundColor Gray
}

# Mostra ultimi log
Write-Host "`n    [INFO] Ultimi log FRPC:" -ForegroundColor Cyan

$logFile = "$FRPC_LOG_DIR\frpc.log"
if (Test-Path $logFile) {
    Write-Host "      File: $logFile" -ForegroundColor Gray
    $logLines = Get-Content $logFile -Tail 15 -ErrorAction SilentlyContinue
    if ($logLines) {
        $logLines | ForEach-Object {
            if ($_ -match 'error|failed|fatal') {
                Write-Host "      $_" -ForegroundColor Red
            }
            elseif ($_ -match 'warn') {
                Write-Host "      $_" -ForegroundColor Yellow
            }
            elseif ($_ -match 'success|start|login') {
                Write-Host "      $_" -ForegroundColor Green
            }
            else {
                Write-Host "      $_" -ForegroundColor Gray
            }
        }
    }
    else {
        Write-Host "      [WARN] Log file vuoto o non leggibile" -ForegroundColor Yellow
    }
}
else {
    Write-Host "      [WARN] Log file non trovato: $logFile" -ForegroundColor Yellow
}

# Log errori NSSM
$stderrLog = "$FRPC_LOG_DIR\nssm-stderr.log"
if (Test-Path $stderrLog) {
    $stderrLines = Get-Content $stderrLog -Tail 10 -ErrorAction SilentlyContinue
    if ($stderrLines -and ($stderrLines | Where-Object { $_.Trim() -ne '' })) {
        Write-Host "`n    [WARN] Errori NSSM rilevati:" -ForegroundColor Yellow
        Write-Host "      File: $stderrLog" -ForegroundColor Gray
        $stderrLines | Where-Object { $_.Trim() -ne '' } | ForEach-Object {
            Write-Host "      $_" -ForegroundColor Red
        }
    }
}

# =====================================================
# 10. Riepilogo e comandi utili
# =====================================================
Write-Host "`n====================================================================" -ForegroundColor Cyan
Write-Host "FIX COMPLETATO" -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

Write-Host "`n[INFO] Comandi utili per diagnostica:" -ForegroundColor Cyan
Write-Host "  - Stato servizio:       Get-Service -Name 'frpc' | Format-List" -ForegroundColor Yellow
Write-Host "  - Restart servizio:     Restart-Service -Name 'frpc'" -ForegroundColor Yellow
Write-Host "  - Log FRPC:             Get-Content '$FRPC_LOG_DIR\frpc.log' -Tail 50" -ForegroundColor Yellow
Write-Host "  - Log errori NSSM:      Get-Content '$FRPC_LOG_DIR\nssm-stderr.log' -Tail 50" -ForegroundColor Yellow
Write-Host "  - Test manuale FRPC:    & '$frpcPath' -c '$tomlFile'" -ForegroundColor Yellow
Write-Host "  - Verifica config:      & '$frpcPath' verify -c '$tomlFile'" -ForegroundColor Yellow
Write-Host "  - Test connettivita:    Test-NetConnection monitor.nethlab.it -Port 7000" -ForegroundColor Yellow
Write-Host "  - Event log servizio:   Get-EventLog -LogName System -Source 'Service Control Manager' -Newest 20 | Where-Object { `$_.Message -like '*frpc*' }" -ForegroundColor Yellow

Write-Host "`n[INFO] Se il servizio ancora non si avvia, prova il test manuale:" -ForegroundColor Cyan
Write-Host "  cd $FRPC_INSTALL_DIR" -ForegroundColor Yellow
Write-Host "  .\frpc.exe -c '$tomlFile'" -ForegroundColor Yellow
Write-Host "  (Premi CTRL+C per uscire)" -ForegroundColor Gray

$service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
if ($service -and $service.Status -eq "Running") {
    Write-Host "`n[OK] Servizio FRPC operativo!" -ForegroundColor Green
}
else {
    Write-Host "`n[WARN] Servizio non in esecuzione - consulta i log per dettagli" -ForegroundColor Yellow
}

Write-Host ""
