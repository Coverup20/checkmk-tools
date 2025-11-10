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
$NSSM_VERSION = "2.24"

$FRP_URL = "https://github.com/fatedier/frp/releases/download/v$FRP_VERSION/frp_$FRP_VERSION`_windows_amd64.zip"

# Try multiple CheckMK URLs (fallback if one fails)
$CHECKMK_MSI_URLS = @(
    "https://monitoring.nethlab.it/monitoring/check_mk/agents/windows/check_mk_agent.msi",
    "https://download.checkmk.com/checkmk/$CHECKMK_VERSION/check-mk-agent-$CHECKMK_VERSION-1_all.msi"
)
$CHECKMK_MSI_URL = $CHECKMK_MSI_URLS[0]  # Primary URL

# NSSM download URLs (fallback se uno fallisce)
$NSSM_URLS = @(
    "https://nssm.cc/release/nssm-$NSSM_VERSION.zip",
    "https://nssm.cc/ci/nssm-$NSSM_VERSION-101-g897c7ad.zip",
    "https://github.com/kirillkovalenko/nssm/releases/download/$NSSM_VERSION/nssm-$NSSM_VERSION.zip"
)
$NSSM_URL = $NSSM_URLS[0]  # Primary URL

$DOWNLOAD_DIR = "$env:TEMP\CheckMK-Setup"
$AGENT_INSTALL_DIR = "C:\Program Files (x86)\checkmk\service"
$FRPC_INSTALL_DIR = "C:\frp"
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
# Funzione: Scarica e installa NSSM se non presente
# =====================================================
function Ensure-NSSM {
    $nssm = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($nssm) {
        Write-Host "    [OK] NSSM già disponibile" -ForegroundColor Green
        return $true
    }
    
    Write-Host "    [*] NSSM non trovato, tentando download..." -ForegroundColor Yellow
    
    try {
        # Ensure download directory exists
        if (-not (Test-Path $DOWNLOAD_DIR)) {
            New-Item -ItemType Directory -Path $DOWNLOAD_DIR -Force -ErrorAction SilentlyContinue | Out-Null
        }
        
        # Use global NSSM_URLS variable (defined at top of script)
        $NSSM_ZIP = "$DOWNLOAD_DIR\nssm-$NSSM_VERSION.zip"
        
        # Clean up old ZIP if exists
        if (Test-Path $NSSM_ZIP) {
            Remove-Item $NSSM_ZIP -Force -ErrorAction SilentlyContinue
        }
        
        $downloadSuccess = $false
        foreach ($url in $NSSM_URLS) {
            try {
                Write-Host "    [*] Tentativo da: $(($url -split '/')[-2])..." -ForegroundColor Cyan
                [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
                
                $webClient = New-Object Net.WebClient
                $webClient.Proxy = [Net.GlobalProxySelection]::GetEmptyWebProxy()
                $webClient.DownloadFile($url, $NSSM_ZIP)
                
                # Verify download
                if ((Test-Path $NSSM_ZIP) -and (Get-Item $NSSM_ZIP).Length -gt 100KB) {
                    $downloadSuccess = $true
                    Write-Host "    [OK] NSSM scaricato ($('{0:N0}' -f (Get-Item $NSSM_ZIP).Length) bytes)" -ForegroundColor Green
                    break
                }
            }
            catch {
                Write-Host "    [WARN] Errore da $url : $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
        
        if (-not $downloadSuccess) {
            Write-Host "    [WARN] Download NSSM fallito da tutte le fonti" -ForegroundColor Yellow
            return $false
        }
        
        # Extract NSSM
        Write-Host "    [*] Estrazione archivio..." -ForegroundColor Yellow
        $nssm_extract = "$DOWNLOAD_DIR\nssm-extract"
        if (Test-Path $nssm_extract) {
            Remove-Item $nssm_extract -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        try {
            Expand-Archive -Path $NSSM_ZIP -DestinationPath $nssm_extract -Force -ErrorAction Stop
            Write-Host "    [OK] Archivio estratto" -ForegroundColor Green
        }
        catch {
            Write-Host "    [ERR] Errore estrazione ZIP: $_" -ForegroundColor Red
            return $false
        }
        
        # Find nssm.exe in extracted folder - preferisci win64 per architettura 64-bit
        $osArch = [Environment]::Is64BitOperatingSystem
        
        if ($osArch) {
            # Preferisci win64 su sistemi 64-bit
            Write-Host "    [*] Rilevato OS 64-bit, cercando NSSM 64-bit..." -ForegroundColor Cyan
            $nssm_exe = Get-ChildItem -Path "$nssm_extract\*\win64" -Filter "nssm.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $nssm_exe) {
                Write-Host "    [WARN] NSSM 64-bit non trovato, usando versione disponibile..." -ForegroundColor Yellow
                $nssm_exe = Get-ChildItem -Path $nssm_extract -Filter "nssm.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            }
        } else {
            # Su sistemi 32-bit usa win32
            $nssm_exe = Get-ChildItem -Path "$nssm_extract\*\win32" -Filter "nssm.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $nssm_exe) {
                $nssm_exe = Get-ChildItem -Path $nssm_extract -Filter "nssm.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            }
        }
        
        if ($nssm_exe) {
            Write-Host "    [*] Trovato: $($nssm_exe.FullName)" -ForegroundColor Cyan
            Write-Host "    [*] Architettura: $(if ($nssm_exe.FullName -like '*win64*') { '64-bit' } else { '32-bit' })" -ForegroundColor Cyan
            # Copy to System32
            try {
                Copy-Item -Path $nssm_exe.FullName -Destination "C:\Windows\System32\nssm.exe" -Force -ErrorAction Stop
                Write-Host "    [OK] NSSM installato in System32" -ForegroundColor Green
            }
            catch {
                Write-Host "    [ERR] Errore copia NSSM: $_" -ForegroundColor Red
                return $false
            }
            
            # Verify it works
            Start-Sleep -Milliseconds 500
            $nssm = Get-Command nssm.exe -ErrorAction SilentlyContinue
            if ($nssm) {
                Write-Host "    [OK] NSSM pronto e funzionante" -ForegroundColor Green
                return $true
            }
            else {
                Write-Host "    [WARN] nssm.exe copiato ma non trovato nel PATH" -ForegroundColor Yellow
                # Try direct execution
                if (Test-Path "C:\Windows\System32\nssm.exe") {
                    Write-Host "    [OK] nssm.exe disponibile in System32" -ForegroundColor Green
                    return $true
                }
            }
        }
        else {
            Write-Host "    [WARN] nssm.exe non trovato nell'archivio estratto" -ForegroundColor Yellow
            Write-Host "    [DEBUG] Contenuto di $nssm_extract :" -ForegroundColor Gray
            Get-ChildItem -Path $nssm_extract -Recurse | Select-Object -First 10 | ForEach-Object { Write-Host "      $_" -ForegroundColor Gray }
            return $false
        }
    }
    catch {
        Write-Host "    [WARN] Errore download NSSM: $_" -ForegroundColor Yellow
        return $false
    }
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
    
    $msiFile = "$DOWNLOAD_DIR\check_mk_agent.msi"
    
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
    
    # Crea directory log
    if (-not (Test-Path $FRPC_LOG_DIR)) {
        New-Item -ItemType Directory -Path $FRPC_LOG_DIR -Force | Out-Null
    }
    
    # Imposta permessi su FRPC_CONFIG_DIR per SYSTEM e tutti gli utenti
    Write-Host "    [*] Configurazione permessi directory..." -ForegroundColor Cyan
    try {
        $acl = Get-Acl -Path $FRPC_CONFIG_DIR
        $systemIdentity = New-Object System.Security.Principal.NTAccount("SYSTEM")
        $everyoneIdentity = New-Object System.Security.Principal.NTAccount("Everyone")
        
        # Aggiungi permessi per SYSTEM (read/write)
        $ace = New-Object System.Security.AccessControl.FileSystemAccessRule($systemIdentity, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
        $acl.AddAccessRule($ace)
        
        # Aggiungi permessi per Everyone (read)
        $ace = New-Object System.Security.AccessControl.FileSystemAccessRule($everyoneIdentity, "Read", "ContainerInherit,ObjectInherit", "None", "Allow")
        $acl.AddAccessRule($ace)
        
        Set-Acl -Path $FRPC_CONFIG_DIR -AclObject $acl
        Write-Host "    [OK] Permessi configurati correttamente" -ForegroundColor Green
    }
    catch {
        Write-Host "    [WARN] Errore configurazione permessi (non critico): $_" -ForegroundColor Yellow
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
    
    # Token di sicurezza (nascosto per sicurezza)
    $useDefaultToken = Read-Host "Usare il token di sicurezza predefinito? [S/n]"
    if ($useDefaultToken -match "^[nN]$") {
        $authToken = Read-Host "Inserisci token personalizzato"
        if ([string]::IsNullOrEmpty($authToken)) {
            Write-Host "    [WARN] Token vuoto, uso quello predefinito" -ForegroundColor Yellow
            $authToken = "conduit-reenact-talon-macarena-demotion-vaguely"
        }
    }
    else {
        $authToken = "conduit-reenact-talon-macarena-demotion-vaguely"
        Write-Host "    [OK] Uso token predefinito" -ForegroundColor Green
    }
    
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
    
    Write-Host "`n[*] Creazione file di configurazione..." -ForegroundColor Yellow
    try {
        Set-Content -Path $tomlFile -Value $tomlConfig -Force
        Write-Host "    [OK] Configurazione salvata in: $tomlFile" -ForegroundColor Green
        
        # Verifica che il file esista e sia leggibile
        if (-not (Test-Path $tomlFile)) {
            Write-Host "    [ERR] Errore: File configurazione non creato" -ForegroundColor Red
            return $false
        }
        
        # Imposta permessi sul file TOML per SYSTEM
        $acl = Get-Acl -Path $tomlFile
        $systemIdentity = New-Object System.Security.Principal.NTAccount("SYSTEM")
        $ace = New-Object System.Security.AccessControl.FileSystemAccessRule($systemIdentity, "FullControl", "None", "None", "Allow")
        $acl.AddAccessRule($ace)
        Set-Acl -Path $tomlFile -AclObject $acl
        Write-Host "    [OK] Permessi file configurazione impostati" -ForegroundColor Green
    }
    catch {
        Write-Host "    [ERR] Errore creazione configurazione: $_" -ForegroundColor Red
        return $false
    }
    
    Write-Host "`n[OK] Configurazione completata" -ForegroundColor Green
    
    # Scarica e configura NSSM (Non-Sucking Service Manager)
    Write-Host "`n[*] Download NSSM (Service Wrapper)..." -ForegroundColor Yellow
    
    # IMPORTANTE: Ferma il servizio FRPC se esiste, prima di manipolare nssm.exe
    $existingFrpcService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
    if ($existingFrpcService -and $existingFrpcService.Status -eq 'Running') {
        Write-Host "    [*] Arresto servizio FRPC esistente per evitare conflitti..." -ForegroundColor Yellow
        Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        Write-Host "    [OK] Servizio FRPC arrestato" -ForegroundColor Green
    }
    
    $nssmZip = "$DOWNLOAD_DIR\nssm-$NSSM_VERSION.zip"
    $nssmExtractPath = "$DOWNLOAD_DIR\nssm-$NSSM_VERSION"
    
    try {
        # Download NSSM con fallback su URL multipli
        $downloadSuccess = $false
        
        if (-not (Test-Path $nssmZip)) {
            Write-Host "    [*] Scaricamento NSSM..." -ForegroundColor Cyan
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            
            foreach ($url in $NSSM_URLS) {
                try {
                    Write-Host "    [*] Tentativo da: $url" -ForegroundColor Gray
                    (New-Object Net.WebClient).DownloadFile($url, $nssmZip)
                    
                    # Verifica download
                    if ((Test-Path $nssmZip) -and (Get-Item $nssmZip).Length -gt 100KB) {
                        $downloadSuccess = $true
                        $sizeMB = [math]::Round((Get-Item $nssmZip).Length / 1MB, 2)
                        Write-Host "    [OK] NSSM scaricato ($sizeMB MB)" -ForegroundColor Green
                        break
                    }
                }
                catch {
                    Write-Host "    [WARN] URL fallito: $($_.Exception.Message)" -ForegroundColor Yellow
                    if (Test-Path $nssmZip) {
                        Remove-Item $nssmZip -Force -ErrorAction SilentlyContinue
                    }
                    Continue
                }
            }
            
            if (-not $downloadSuccess) {
                Write-Host "[ERR] Errore: Nessun URL NSSM disponibile" -ForegroundColor Red
                return $false
            }
        }
        else {
            Write-Host "    [OK] NSSM già scaricato" -ForegroundColor Green
        }
        
        # Estrai NSSM
        Write-Host "    [*] Estrazione NSSM..." -ForegroundColor Cyan
        if (Test-Path $nssmExtractPath) {
            Remove-Item -Recurse -Force $nssmExtractPath
        }
        
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($nssmZip, $DOWNLOAD_DIR)
        
        # Trova il file nssm.exe corretto (preferisci win64 su sistemi 64-bit)
        $nssmExe = $null
        if ([Environment]::Is64BitOperatingSystem) {
            $nssmExe = Get-ChildItem -Path $nssmExtractPath -Recurse -Filter "nssm.exe" | 
                       Where-Object { $_.FullName -like "*win64*" } | 
                       Select-Object -First 1 -ExpandProperty FullName
        }
        
        if (-not $nssmExe) {
            $nssmExe = Get-ChildItem -Path $nssmExtractPath -Recurse -Filter "nssm.exe" | 
                       Select-Object -First 1 -ExpandProperty FullName
        }
        
        if (-not $nssmExe -or -not (Test-Path $nssmExe)) {
            Write-Host "[ERR] Errore: NSSM.exe non trovato nell'archivio" -ForegroundColor Red
            return $false
        }
        
        # Copia NSSM in una posizione permanente
        $nssmInstallPath = "$FRPC_INSTALL_DIR\nssm.exe"
        
        # Rimuovi file esistente se presente e non in uso
        if (Test-Path $nssmInstallPath) {
            try {
                Remove-Item -Path $nssmInstallPath -Force -ErrorAction Stop
                Start-Sleep -Milliseconds 500
            }
            catch {
                Write-Host "    [WARN] Impossibile rimuovere nssm.exe esistente: $($_.Exception.Message)" -ForegroundColor Yellow
                Write-Host "    [*] Tentativo alternativo con Stop-Process..." -ForegroundColor Cyan
                
                # Trova e termina eventuali processi che usano nssm.exe
                Get-Process | Where-Object { $_.Path -eq $nssmInstallPath } | Stop-Process -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 2
                
                try {
                    Remove-Item -Path $nssmInstallPath -Force -ErrorAction Stop
                }
                catch {
                    Write-Host "    [WARN] File ancora in uso, tentativo rinomina..." -ForegroundColor Yellow
                    Move-Item -Path $nssmInstallPath -Destination "$nssmInstallPath.old" -Force -ErrorAction SilentlyContinue
                }
            }
        }
        
        Copy-Item -Path $nssmExe -Destination $nssmInstallPath -Force
        
        Write-Host "    [OK] NSSM estratto: $nssmInstallPath" -ForegroundColor Green
    }
    catch {
        Write-Host "[ERR] Errore configurazione NSSM: $_" -ForegroundColor Red
        return $false
    }
    
    # Crea servizio Windows con NSSM (configurazione SEMPLIFICATA)
    Write-Host "`n[*] Creazione servizio Windows con NSSM..." -ForegroundColor Yellow
    
    try {
        # Rimuovi servizio esistente se presente
        $existingService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($existingService) {
            Write-Host "    [*] Arresto servizio esistente..." -ForegroundColor Yellow
            Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            
            Write-Host "    [*] Rimozione servizio precedente..." -ForegroundColor Yellow
            & $nssmInstallPath remove frpc confirm 2>&1 | Out-Null
            Start-Sleep -Seconds 2
        }
        
        $frpcPath = "$FRPC_INSTALL_DIR\frpc.exe"
        
        Write-Host "    [*] Registrazione servizio con NSSM..." -ForegroundColor Cyan
        
        # CONFIGURAZIONE SEMPLIFICATA - Solo parametri essenziali
        & $nssmInstallPath install frpc "$frpcPath" 2>&1 | Out-Null
        & $nssmInstallPath set frpc AppParameters "-c `"$tomlFile`"" 2>&1 | Out-Null
        & $nssmInstallPath set frpc AppDirectory "$FRPC_INSTALL_DIR" 2>&1 | Out-Null
        & $nssmInstallPath set frpc DisplayName "FRP Client Service" 2>&1 | Out-Null
        & $nssmInstallPath set frpc Description "FRP Client - Tunneling service" 2>&1 | Out-Null
        & $nssmInstallPath set frpc Start SERVICE_AUTO_START 2>&1 | Out-Null
        
        # Log semplici (opzionali)
        & $nssmInstallPath set frpc AppStdout "$FRPC_LOG_DIR\nssm-stdout.log" 2>&1 | Out-Null
        & $nssmInstallPath set frpc AppStderr "$FRPC_LOG_DIR\nssm-stderr.log" 2>&1 | Out-Null
        
        Write-Host "    [OK] Servizio registrato con NSSM" -ForegroundColor Green
        
        Write-Host "    [OK] Servizio registrato con NSSM" -ForegroundColor Green
        
        Start-Sleep -Seconds 2
        
        # Verify service was created
        $frpcService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if (-not $frpcService) {
            Write-Host "    [ERR] Servizio non registrato correttamente" -ForegroundColor Red
            return $false
        }
        
        Write-Host "    [OK] Servizio registrato" -ForegroundColor Green
        
        # Try to start service with retry logic (increased timeouts)
        $maxRetries = 5
        $retryCount = 0
        $serviceRunning = $false
        
        While ($retryCount -lt $maxRetries -and -not $serviceRunning) {
            $retryCount++
            Write-Host "    [*] Tentativo di avvio ($retryCount/$maxRetries)..." -ForegroundColor Yellow
            
            try {
                Start-Service -Name "frpc" -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 5
                
                $frpcService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
                if ($frpcService -and $frpcService.Status -eq "Running") {
                    Write-Host "    [OK] Servizio FRPC avviato con successo" -ForegroundColor Green
                    $serviceRunning = $true
                }
                elseif ($retryCount -lt $maxRetries) {
                    Write-Host "    [WARN] Servizio non è in esecuzione, nuovo tentativo tra 2 secondi..." -ForegroundColor Yellow
                    Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 2
                }
            }
            catch {
                Write-Host "    [WARN] Errore avvio: $_" -ForegroundColor Yellow
            }
        }
        
        if (-not $serviceRunning) {
            Write-Host "    [WARN] Servizio creato ma non avviato automaticamente" -ForegroundColor Yellow
            Write-Host "`n    [INFO] Comandi diagnostici:" -ForegroundColor Cyan
            Write-Host "      - Verifica permessi: icacls '$FRPC_CONFIG_DIR'" -ForegroundColor Yellow
            Write-Host "      - Avvio manuale: Start-Service -Name 'frpc'" -ForegroundColor Yellow
            Write-Host "      - Stato servizio: Get-Service -Name 'frpc'" -ForegroundColor Yellow
            Write-Host "      - Log TOML: Get-Content '$tomlFile'" -ForegroundColor Yellow
            Write-Host "      - Log errori: Get-Content '$FRPC_LOG_DIR\frpc-stderr.log' -Tail 50" -ForegroundColor Yellow
            Write-Host "      - Log output: Get-Content '$FRPC_LOG_DIR\frpc-stdout.log' -Tail 50" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "    [ERR] Errore creazione servizio: $_" -ForegroundColor Red
        return $false
    }
    
    Write-Host "`n[OK] FRPC Configurazione:" -ForegroundColor Green
    Write-Host "    Server:        $frpServer`:7000"
    Write-Host "    Tunnel:        $frpcHostname"
    Write-Host "    Porta remota:  $remotePort"
    Write-Host "    Porta locale:  6556"
    Write-Host "    Config:        $tomlFile"
    Write-Host "    Log:           $FRPC_LOG_DIR\frpc.log"
    
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
            Write-Host "`n[WARN] FRPC non installato correttamente" -ForegroundColor Yellow
            Write-Host "[INFO] L'Agent CheckMK è comunque operativo sulla porta 6556" -ForegroundColor Cyan
            Write-Host "[INFO] Per completare l'installazione FRPC, prova:" -ForegroundColor Cyan
            Write-Host "       1. Chiudi tutti i processi che usano NSSM" -ForegroundColor Cyan
            Write-Host "       2. Rilancia lo script" -ForegroundColor Cyan
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
