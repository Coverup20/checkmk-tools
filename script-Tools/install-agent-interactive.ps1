#!/usr/bin/env powershell
# ============================================================
# Installazione Interattiva CheckMK Agent + FRPC per Windows
# Compatibile con: Windows 10, 11, Server 2019, 2022
# Version: 1.1 - 2025-11-07
# ============================================================

#Requires -RunAsAdministrator
#Requires -Version 5.0

Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force -ErrorAction SilentlyContinue

# Global error handling
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# Configuration
$CHECKMK_VERSION = "2.4.0p14"
$FRP_VERSION = "0.64.0"
$FRP_URL = "https://github.com/fatedier/frp/releases/download/v$FRP_VERSION/frp_$FRP_VERSION`_windows_amd64.zip"
# Try multiple CheckMK URLs (fallback if one fails)
$CHECKMK_MSI_URLS = @(
    "https://download.checkmk.com/checkmk/$CHECKMK_VERSION/check-mk-agent-$CHECKMK_VERSION-1_all.msi",
    "https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent-$CHECKMK_VERSION-1_all.msi"
)
$CHECKMK_MSI_URL = $CHECKMK_MSI_URLS[0]  # Primary URL

$DOWNLOAD_DIR = "$env:TEMP\CheckMK-Setup"
$AGENT_INSTALL_DIR = "C:\Program Files (x86)\checkmk\service"
$FRPC_INSTALL_DIR = "C:\Program Files\frp"
$FRPC_CONFIG_DIR = "C:\ProgramData\frp"
$FRPC_LOG_DIR = "C:\ProgramData\frp\logs"

# =====================================================
# Funzione: Mostra utilizzo
# =====================================================
function Show-Usage {
    Write-Host @"
Uso: .\install-agent-interactive.ps1 [opzioni]

Opzioni:
  (nessun parametro)         Installa CheckMK Agent + prompt per FRPC
  --uninstall-frpc          Disinstalla solo FRPC
  --uninstall-agent         Disinstalla solo CheckMK Agent
  --uninstall               Disinstalla tutto (Agent + FRPC)
  --help, -h                Mostra questo messaggio

Esempi:
  .\install-agent-interactive.ps1
  .\install-agent-interactive.ps1 --uninstall
  .\install-agent-interactive.ps1 --uninstall-frpc
"@
}

# =====================================================
# Funzione: Verifica Administrator
# =====================================================
function Test-Administrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

# =====================================================
# Funzione: Rileva SO Windows
# =====================================================
function Get-WindowsInfo {
    $osInfo = Get-WmiObject -Class Win32_OperatingSystem
    $version = $osInfo.Version
    $caption = $osInfo.Caption
    $arch = $osInfo.OSArchitecture
    
    if ($caption -like "*Windows 11*") {
        $osName = "Windows 11"
    }
    elseif ($caption -like "*Windows 10*") {
        $osName = "Windows 10"
    }
    elseif ($caption -like "*Server 2022*") {
        $osName = "Windows Server 2022"
    }
    elseif ($caption -like "*Server 2019*") {
        $osName = "Windows Server 2019"
    }
    else {
        $osName = $caption
    }
    
    $architecture = if ($arch -like "*64-bit*") { "x64" } else { "x86" }
    
    return @{
        Name = $osName
        Version = $version
        Architecture = $architecture
    }
}

# =====================================================
# Funzione: Disinstalla FRPC
# =====================================================
function Remove-FRPCService {
    Write-Host "`n`n====================================================================`n" -ForegroundColor Red
    Write-Host "DISINSTALLAZIONE FRPC CLIENT" -ForegroundColor Red
    Write-Host "`n====================================================================" -ForegroundColor Red
    Write-Host "`nRimozione FRPC in corso...`n" -ForegroundColor Yellow
    
    try {
        # Ferma servizio
        $service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($service) {
            Write-Host "[*] Arresto servizio FRPC..." -ForegroundColor Yellow
            Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
        
        # Rimuovi servizio
        if ($service) {
            Write-Host "[*] Rimozione servizio Windows..." -ForegroundColor Yellow
            sc.exe delete frpc 2>$null | Out-Null
            Start-Sleep -Seconds 1
        }
        
        # Termina processi
        Write-Host "[*] Terminazione processi FRPC..." -ForegroundColor Yellow
        Get-Process -Name "frpc" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        
        # Rimuovi directory
        if (Test-Path $FRPC_INSTALL_DIR) {
            Write-Host "[*] Rimozione directory installazione..." -ForegroundColor Yellow
            Remove-Item -Path $FRPC_INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        if (Test-Path $FRPC_CONFIG_DIR) {
            Write-Host "[*] Rimozione directory configurazione..." -ForegroundColor Yellow
            Remove-Item -Path $FRPC_CONFIG_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        Write-Host "`n[OK] FRPC disinstallato completamente" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERR] Errore durante disinstallazione FRPC: $_" -ForegroundColor Red
    }
}

# =====================================================
# Funzione: Disinstalla CheckMK Agent
# =====================================================
function Remove-CheckMKAgentService {
    Write-Host "`n`n====================================================================" -ForegroundColor Red
    Write-Host "DISINSTALLAZIONE CHECKMK AGENT" -ForegroundColor Red
    Write-Host "`n====================================================================" -ForegroundColor Red
    Write-Host "`nRimozione CheckMK Agent in corso...`n" -ForegroundColor Yellow
    
    try {
        # Ferma servizio
        $agentService = Get-Service -Name "CheckMK Agent" -ErrorAction SilentlyContinue
        if ($agentService) {
            Write-Host "[*] Arresto servizio CheckMK Agent..." -ForegroundColor Yellow
            Stop-Service -Name "CheckMK Agent" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
        
        # Disinstalla MSI
        Write-Host "[*] Disinstallazione pacchetto MSI..." -ForegroundColor Yellow
        $uninstallString = Get-WmiObject -Class Win32_Product -ErrorAction SilentlyContinue | Where-Object {$_.Name -like "*CheckMK*"} | Select-Object -ExpandProperty IdentifyingNumber
        
        if ($uninstallString) {
            msiexec.exe /x $uninstallString /qn /norestart 2>$null | Out-Null
            Start-Sleep -Seconds 3
        }
        
        # Rimuovi directory
        if (Test-Path $AGENT_INSTALL_DIR) {
            Write-Host "[*] Rimozione directory installazione..." -ForegroundColor Yellow
            Remove-Item -Path $AGENT_INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        $configPath = "C:\ProgramData\checkmk"
        if (Test-Path $configPath) {
            Write-Host "[*] Rimozione directory configurazione..." -ForegroundColor Yellow
            Remove-Item -Path $configPath -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        Get-Process -Name "check_mk_agent" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        
        Write-Host "`n[OK] CheckMK Agent disinstallato completamente" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERR] Errore durante disinstallazione Agent: $_" -ForegroundColor Red
    }
}

# =====================================================
# Funzione: Installa CheckMK Agent
# =====================================================
function Install-CheckMKAgent {
    Write-Host "`n`n====================================================================" -ForegroundColor Cyan
    Write-Host "INSTALLAZIONE CHECKMK AGENT PER WINDOWS" -ForegroundColor Cyan
    Write-Host "`n====================================================================" -ForegroundColor Cyan
    
    if (-not (Test-Path $DOWNLOAD_DIR)) {
        New-Item -ItemType Directory -Path $DOWNLOAD_DIR -Force | Out-Null
    }
    
    $msiFile = "$DOWNLOAD_DIR\check-mk-agent-$CHECKMK_VERSION-1_all.msi"
    
    Write-Host "`n[*] Download CheckMK Agent v$CHECKMK_VERSION..." -ForegroundColor Yellow
    
    # Try multiple URLs with fallback
    $downloadSuccess = $false
    foreach ($url in $CHECKMK_MSI_URLS) {
        try {
            if (-not (Test-Path $msiFile)) {
                Write-Host "    Tentativo download da: $url" -ForegroundColor Gray
                [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
                (New-Object Net.WebClient).DownloadFile($url, $msiFile)
                $downloadSuccess = $true
                break
            }
            else {
                $downloadSuccess = $true
                break
            }
        }
        catch {
            Write-Host "    [WARN] URL fallito: $($_.Exception.Message)" -ForegroundColor Yellow
            Continue
        }
    }
    
    if (-not $downloadSuccess -or -not (Test-Path $msiFile) -or (Get-Item $msiFile).Length -eq 0) {
        Write-Host "[ERR] Errore: Nessun URL disponibile per il download" -ForegroundColor Red
        return $false
    }
    
    $sizeMB = [math]::Round((Get-Item $msiFile).Length / 1048576, 2)
    Write-Host "    [OK] Download completato ($sizeMB MB)" -ForegroundColor Green
    
    # Installa MSI
    Write-Host "`n[*] Installazione in corso..." -ForegroundColor Yellow
    try {
        $msiLog = "$DOWNLOAD_DIR\checkmk-install.log"
        $installArgs = @("/i", $msiFile, "/qn", "/norestart", "/l*v", $msiLog)
        
        $process = Start-Process -FilePath "msiexec.exe" -ArgumentList $installArgs -Wait -PassThru
        
        if ($process.ExitCode -eq 0 -or $process.ExitCode -eq 3010) {
            Write-Host "    [OK] Installazione completata" -ForegroundColor Green
            
            Start-Sleep -Seconds 2
            $agentService = Get-Service -Name "CheckMK Agent" -ErrorAction SilentlyContinue
            if ($agentService) {
                if ($agentService.Status -ne "Running") {
                    Start-Service -Name "CheckMK Agent"
                }
                Write-Host "    [OK] Servizio CheckMK Agent avviato" -ForegroundColor Green
            }
            
            return $true
        }
        else {
            Write-Host "[ERR] Errore installazione (Exit code: $($process.ExitCode))" -ForegroundColor Red
            return $false
        }
    }
    catch {
        Write-Host "[ERR] Errore durante installazione: $_" -ForegroundColor Red
        return $false
    }
}

# =====================================================
# Funzione: Installa FRPC
# =====================================================
function Install-FRPCService {
    Write-Host "`n`n====================================================================" -ForegroundColor Blue
    Write-Host "INSTALLAZIONE FRPC CLIENT PER WINDOWS" -ForegroundColor Blue
    Write-Host "`n====================================================================" -ForegroundColor Blue
    
    if (-not (Test-Path $DOWNLOAD_DIR)) {
        New-Item -ItemType Directory -Path $DOWNLOAD_DIR -Force | Out-Null
    }
    
    $zipFile = "$DOWNLOAD_DIR\frp_$FRP_VERSION`_windows_amd64.zip"
    
    Write-Host "`n[*] Download FRPC v$FRP_VERSION..." -ForegroundColor Yellow
    
    try {
        if (-not (Test-Path $zipFile)) {
            Write-Host "    Scaricamento in corso..." -ForegroundColor Cyan
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            (New-Object Net.WebClient).DownloadFile($FRP_URL, $zipFile)
        }
        
        if (-not (Test-Path $zipFile) -or (Get-Item $zipFile).Length -eq 0) {
            Write-Host "[ERR] Errore: File ZIP non valido" -ForegroundColor Red
            return $false
        }
        
        $sizeMB = [math]::Round((Get-Item $zipFile).Length / 1MB, 2)
        Write-Host "    [OK] Download completato ($sizeMB MB)" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERR] Errore durante download: $_" -ForegroundColor Red
        return $false
    }
    
    # Estrai ZIP
    Write-Host "`n[*] Estrazione archivio..." -ForegroundColor Yellow
    try {
        if (-not (Test-Path $FRPC_INSTALL_DIR)) {
            New-Item -ItemType Directory -Path $FRPC_INSTALL_DIR -Force | Out-Null
        }
        
        Expand-Archive -Path $zipFile -DestinationPath $DOWNLOAD_DIR -Force
        
        $extractedDir = Get-ChildItem "$DOWNLOAD_DIR" -Directory | Where-Object {$_.Name -like "frp_*"} | Select-Object -First 1
        if ($extractedDir) {
            $frpcExe = Join-Path $extractedDir.FullName "frpc.exe"
            if (Test-Path $frpcExe) {
                Copy-Item -Path $frpcExe -Destination "$FRPC_INSTALL_DIR\frpc.exe" -Force
                Write-Host "    [OK] frpc.exe copiato" -ForegroundColor Green
            }
        }
        
        if (-not (Test-Path "$FRPC_INSTALL_DIR\frpc.exe")) {
            Write-Host "[ERR] Errore: frpc.exe non trovato" -ForegroundColor Red
            return $false
        }
    }
    catch {
        Write-Host "[ERR] Errore durante estrazione: $_" -ForegroundColor Red
        return $false
    }
    
    # Configura FRPC
    Write-Host "`n[*] Configurazione FRPC..." -ForegroundColor Yellow
    
    if (-not (Test-Path $FRPC_CONFIG_DIR)) {
        New-Item -ItemType Directory -Path $FRPC_CONFIG_DIR -Force | Out-Null
    }
    
    $computerName = $env:COMPUTERNAME
    Write-Host "`nInserisci le informazioni per la configurazione FRPC:`n" -ForegroundColor Yellow
    
    $frpcHostname = Read-Host "Nome host [default: $computerName]"
    $frpcHostname = if ([string]::IsNullOrEmpty($frpcHostname)) { $computerName } else { $frpcHostname }
    
    $frpServer = Read-Host "Server FRP remoto [default: monitor.nethlab.it]"
    $frpServer = if ([string]::IsNullOrEmpty($frpServer)) { "monitor.nethlab.it" } else { $frpServer }
    
    $remotePort = $null
    while ([string]::IsNullOrEmpty($remotePort)) {
        $remotePort = Read-Host "Porta remota (es: 20001)"
    }
    
    $authToken = Read-Host "Token di sicurezza [default: conduit-reenact-talon-macarena-demotion-vaguely]"
    $authToken = if ([string]::IsNullOrEmpty($authToken)) { "conduit-reenact-talon-macarena-demotion-vaguely" } else { $authToken }
    
    # Crea configurazione TOML
    $tomlConfig = @"
[common]
server_addr = "$frpServer"
server_port = 7000
auth.method = "token"
auth.token  = "$authToken"
tls.enable = true
log.to = "$FRPC_LOG_DIR\frpc.log"
log.level = "debug"

[$frpcHostname]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $remotePort
"@
    
    $tomlFile = "$FRPC_CONFIG_DIR\frpc.toml"
    Set-Content -Path $tomlFile -Value $tomlConfig
    
    Write-Host "`n[OK] Configurazione salvata" -ForegroundColor Green
    
    # Crea servizio Windows
    Write-Host "`n[*] Creazione servizio Windows..." -ForegroundColor Yellow
    
    try {
        $existingService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($existingService) {
            Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
            sc.exe delete frpc 2>$null | Out-Null
            Start-Sleep -Seconds 1
        }
        
        $frpcPath = "$FRPC_INSTALL_DIR\frpc.exe"
        sc.exe create frpc binPath= "$frpcPath -c $tomlFile" start= auto displayname= "FRP Client Service" 2>$null | Out-Null
        
        Start-Service -Name "frpc" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        
        $frpcService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($frpcService -and $frpcService.Status -eq "Running") {
            Write-Host "    [OK] Servizio FRPC avviato" -ForegroundColor Green
        }
        else {
            Write-Host "    [WARN] Servizio creato ma non avviato" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "    [ERR] Errore creazione servizio: $_" -ForegroundColor Red
    }
    
    Write-Host "`n[OK] FRPC Configurazione:" -ForegroundColor Green
    Write-Host "    Server:        $frpServer`:7000"
    Write-Host "    Tunnel:        $frpcHostname"
    Write-Host "    Porta remota:  $remotePort"
    Write-Host "    Porta locale:  6556"
    
    return $true
}

# =====================================================
# MAIN
# =====================================================

try {
    Write-Host "`n"
    Write-Host "====================================================================" -ForegroundColor Cyan
    Write-Host "Installazione Interattiva CheckMK Agent + FRPC per Windows" -ForegroundColor Cyan
    Write-Host "Version: 1.1 - 2025-11-07" -ForegroundColor Cyan
    Write-Host "====================================================================" -ForegroundColor Cyan
    
    # Verifica Administrator
    if (-not (Test-Administrator)) {
        Write-Host "`n[ERR] Questo script deve essere eseguito come Administrator" -ForegroundColor Red
        exit 1
    }
    
    # Gestione parametri
    $MODE = "install"
    if ($args.Count -gt 0) {
        switch ($args[0]) {
            "--help" { Show-Usage; exit 0 }
            "-h" { Show-Usage; exit 0 }
            "--uninstall-frpc" { $MODE = "uninstall-frpc" }
            "--uninstall-agent" { $MODE = "uninstall-agent" }
            "--uninstall" { $MODE = "uninstall-all" }
            default {
                Write-Host "[ERR] Parametro non valido: $($args[0])" -ForegroundColor Red
                Show-Usage
                exit 1
            }
        }
    }
    
    # Modalita' disinstallazione
    if ($MODE -eq "uninstall-frpc") {
        Remove-FRPCService
        exit 0
    }
    elseif ($MODE -eq "uninstall-agent") {
        Remove-CheckMKAgentService
        exit 0
    }
    elseif ($MODE -eq "uninstall-all") {
        Write-Host "`n[WARN] DISINSTALLAZIONE COMPLETA`n" -ForegroundColor Red
        $confirm = Read-Host "Sei sicuro di voler rimuovere tutto? [s/N]"
        if ($confirm -match "^[sS]$") {
            Remove-FRPCService
            Write-Host ""
            Remove-CheckMKAgentService
            Write-Host "`n[OK] Disinstallazione completa terminata!`n" -ForegroundColor Green
        }
        else {
            Write-Host "`n[CANCEL] Operazione annullata`n" -ForegroundColor Cyan
        }
        exit 0
    }
    
    # Modalita' installazione
    Write-Host "`n[*] Rilevamento Sistema Operativo..." -ForegroundColor Cyan
    $osInfo = Get-WindowsInfo
    
    Write-Host "`n====================================================================" -ForegroundColor Cyan
    Write-Host "RILEVAMENTO SISTEMA OPERATIVO" -ForegroundColor Cyan
    Write-Host "`n====================================================================" -ForegroundColor Cyan
    
    Write-Host "`n[INFO] Sistema Rilevato:" -ForegroundColor Yellow
    Write-Host "    OS:            $($osInfo.Name)"
    Write-Host "    Versione:      $($osInfo.Version)"
    Write-Host "    Architettura:  $($osInfo.Architecture)"
    
    Write-Host "`n[INFO] Questa installazione utilizzeray:" -ForegroundColor Yellow
    Write-Host "    - CheckMK Agent (plain TCP on port 6556)"
    Write-Host "    - Servizio Windows: CheckMK Agent"
    
    Write-Host "`n====================================================================" -ForegroundColor Yellow
    $confirmSystem = Read-Host "Procedi con l'installazione? [s/N]"
    Write-Host "====================================================================" -ForegroundColor Yellow
    
    if ($confirmSystem -notmatch "^[sS]$") {
        Write-Host "`n[CANCEL] Installazione annullata`n" -ForegroundColor Cyan
        exit 0
    }
    
    Write-Host "`n[OK] Procedendo con l'installazione...`n" -ForegroundColor Green
    
    # Installa Agent
    if (Install-CheckMKAgent) {
        Write-Host "`n[OK] CheckMK Agent installato con successo" -ForegroundColor Green
    }
    else {
        Write-Host "`n[ERR] Errore nell'installazione di CheckMK Agent" -ForegroundColor Red
        exit 1
    }
    
    # Chiedi FRPC
    Write-Host "`n====================================================================" -ForegroundColor Yellow
    $installFRPC = Read-Host "Vuoi installare anche FRPC? [s/N]"
    Write-Host "====================================================================" -ForegroundColor Yellow
    
    if ($installFRPC -match "^[sS]$") {
        if (-not (Install-FRPCService)) {
            Write-Host "`n[WARN] FRPC non installato, ma Agent e operativo" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "`n[SKIP] Installazione FRPC saltata" -ForegroundColor Yellow
    }
    
    # Riepilogo finale
    Write-Host "`n`n====================================================================" -ForegroundColor Green
    Write-Host "INSTALLAZIONE COMPLETATA" -ForegroundColor Green
    Write-Host "`n====================================================================" -ForegroundColor Green
    Write-Host "`n[OK] CheckMK Agent installato (TCP 6556)" -ForegroundColor Green
    Write-Host "[OK] Servizio Windows attivo: CheckMK Agent" -ForegroundColor Green
    
    if ($installFRPC -match "^[sS]$") {
        Write-Host "[OK] FRPC Client installato e configurato" -ForegroundColor Green
        Write-Host "[OK] Servizio Windows attivo: frpc" -ForegroundColor Green
    }
    
    Write-Host "`n[INFO] Comandi utili PowerShell:" -ForegroundColor Cyan
    Write-Host "    Get-Service -Name 'CheckMK Agent' | Format-List" -ForegroundColor Yellow
    Write-Host "    Restart-Service -Name 'CheckMK Agent'" -ForegroundColor Yellow
    
    if ($installFRPC -match "^[sS]$") {
        Write-Host "    Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 50" -ForegroundColor Yellow
    }
    
    Write-Host "`n[OK] Installazione terminata con successo!`n" -ForegroundColor Green

}
catch {
    Write-Host "`n`n[ERR] ERRORE DURANTE L'ESECUZIONE:" -ForegroundColor Red
    Write-Host "    $_" -ForegroundColor Red
    Write-Host "`nTraccia stack:" -ForegroundColor Yellow
    Write-Host $_.ScriptStackTrace -ForegroundColor Gray
    exit 1
}
