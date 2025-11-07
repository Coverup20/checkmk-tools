# ============================================================
# Installazione Interattiva CheckMK Agent + FRPC per Windows
# Compatibile con: Windows 10, 11, Server 2019, 2022
# Version: 1.0 - 2025-11-07
# ============================================================

# Imposta execution policy per questo script
#Requires -RunAsAdministrator
#Requires -Version 5.0

Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process -Force -ErrorAction SilentlyContinue

# Global error handling
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# Trap per errori non gestiti
trap {
    Write-Host "`n❌ ERRORE CRITICO: $_" -ForegroundColor Red
    Write-Host "Stack Trace: $($_.ScriptStackTrace)" -ForegroundColor DarkRed
    exit 1
}

# Colori per output
$Colors = @{
    Green  = "Green"
    Red    = "Red"
    Yellow = "Yellow"
    Cyan   = "Cyan"
    Gray   = "Gray"
    DarkYellow = "DarkYellow"
}

# =====================================================
# Funzione: Mostra utilizzo
# =====================================================
function Show-Usage {
    $usage = @"
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

Note:
  - Lo script deve essere eseguito come Administrator
  - Richiede connessione internet per download
  - Windows 10/11 e Server 2019/2022 sono supportati
"@
    Write-Host $usage
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
# Funzione: Rileva Sistema Operativo Windows
# =====================================================
function Detect-WindowsOS {
    Write-Host "🔍 Rilevamento sistema operativo..." -ForegroundColor $Colors.Cyan
    
    $osInfo = Get-WmiObject -Class Win32_OperatingSystem
    $winVersion = $osInfo.Version
    $caption = $osInfo.Caption
    $arch = $osInfo.OSArchitecture
    
    # Rileva versione Windows più precisa
    if ($caption -like "*Windows 11*") {
        $osName = "Windows 11"
        $osType = "Windows 11"
    }
    elseif ($caption -like "*Windows 10*") {
        $osName = "Windows 10"
        $osType = "Windows 10"
    }
    elseif ($caption -like "*Server 2022*") {
        $osName = "Windows Server 2022"
        $osType = "Windows Server 2022"
    }
    elseif ($caption -like "*Server 2019*") {
        $osName = "Windows Server 2019"
        $osType = "Windows Server 2019"
    }
    else {
        $osName = $caption
        $osType = "Windows (altro)"
    }
    
    # Architettura
    $architecture = if ($arch -like "*64-bit*") { "x64" } else { "x86" }
    
    Write-Host "   ✓ OS: $osName" -ForegroundColor $Colors.Green
    Write-Host "   ✓ Versione: $winVersion" -ForegroundColor $Colors.Green
    Write-Host "   ✓ Architettura: $architecture" -ForegroundColor $Colors.Green
    
    return @{
        Name = $osName
        Type = $osType
        Version = $winVersion
        Architecture = $architecture
        Caption = $caption
    }
}

# =====================================================
# Configurazione Variabili
# =====================================================
$CHECKMK_VERSION = "2.4.0p14"
$FRP_VERSION = "0.64.0"
$FRP_URL = "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_windows_amd64.zip"
$CHECKMK_MSI_URL = "https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent-${CHECKMK_VERSION}-1_all.msi"

$DOWNLOAD_DIR = "$env:TEMP\CheckMK-Setup"
$AGENT_INSTALL_DIR = "C:\Program Files (x86)\checkmk\service"
$FRPC_INSTALL_DIR = "C:\Program Files\frp"
$FRPC_CONFIG_DIR = "C:\ProgramData\frp"
$FRPC_LOG_DIR = "C:\ProgramData\frp\logs"

# =====================================================
# Funzione: Disinstalla FRPC
# =====================================================
function Uninstall-FRPC {
    Write-Host "`n`n"
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Red
    Write-Host "║           DISINSTALLAZIONE FRPC CLIENT                    ║" -ForegroundColor $Colors.Red
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Red
    
    Write-Host "`n🗑️  Rimozione FRPC in corso...`n" -ForegroundColor $Colors.Yellow
    
    try {
        # Ferma servizio
        $service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($service) {
            Write-Host "⏹️  Arresto servizio FRPC..." -ForegroundColor $Colors.Yellow
            Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
        
        # Rimuovi servizio Windows
        if ($service) {
            Write-Host "🗑️  Rimozione servizio Windows..." -ForegroundColor $Colors.Yellow
            sc.exe delete frpc | Out-Null
            Start-Sleep -Seconds 1
        }
        
        # Termina processi
        Write-Host "⏹️  Terminazione processi FRPC..." -ForegroundColor $Colors.Yellow
        Get-Process -Name "frpc" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        
        # Rimuovi directory
        if (Test-Path $FRPC_INSTALL_DIR) {
            Write-Host "🗑️  Rimozione directory installazione..." -ForegroundColor $Colors.Yellow
            Remove-Item -Path $FRPC_INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        # Rimuovi configurazione
        if (Test-Path $FRPC_CONFIG_DIR) {
            Write-Host "🗑️  Rimozione directory configurazione..." -ForegroundColor $Colors.Yellow
            Remove-Item -Path $FRPC_CONFIG_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        # Rimuovi log
        if (Test-Path $FRPC_LOG_DIR) {
            Write-Host "🗑️  Rimozione file log..." -ForegroundColor $Colors.Yellow
            Remove-Item -Path $FRPC_LOG_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        Write-Host "`n✅ FRPC disinstallato completamente" -ForegroundColor $Colors.Green
        Write-Host "📋 File rimossi:" -ForegroundColor $Colors.Cyan
        Write-Host "   • $FRPC_INSTALL_DIR" -ForegroundColor $Colors.Gray
        Write-Host "   • $FRPC_CONFIG_DIR" -ForegroundColor $Colors.Gray
        Write-Host "   • Servizio Windows 'frpc'" -ForegroundColor $Colors.Gray
    }
    catch {
        Write-Host "❌ Errore durante disinstallazione FRPC: $_" -ForegroundColor $Colors.Red
    }
}

# =====================================================
# Funzione: Disinstalla CheckMK Agent
# =====================================================
function Uninstall-CheckMKAgent {
    Write-Host "`n`n"
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Red
    Write-Host "║        DISINSTALLAZIONE CHECKMK AGENT                     ║" -ForegroundColor $Colors.Red
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Red
    
    Write-Host "`n🗑️  Rimozione CheckMK Agent in corso...`n" -ForegroundColor $Colors.Yellow
    
    try {
        # Ferma servizio agent
        $agentService = Get-Service -Name "CheckMK Agent" -ErrorAction SilentlyContinue
        if ($agentService) {
            Write-Host "⏹️  Arresto servizio CheckMK Agent..." -ForegroundColor $Colors.Yellow
            Stop-Service -Name "CheckMK Agent" -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
        }
        
        # Disinstalla MSI se presente
        Write-Host "📦 Disinstallazione pacchetto MSI..." -ForegroundColor $Colors.Yellow
        $uninstallString = Get-WmiObject -Class Win32_Product | Where-Object {$_.Name -like "*CheckMK*"} | Select-Object -ExpandProperty IdentifyingNumber -ErrorAction SilentlyContinue
        
        if ($uninstallString) {
            msiexec.exe /x $uninstallString /qn /norestart | Out-Null
            Start-Sleep -Seconds 3
        }
        
        # Rimuovi directory installazione se esiste ancora
        if (Test-Path $AGENT_INSTALL_DIR) {
            Write-Host "🗑️  Rimozione directory installazione..." -ForegroundColor $Colors.Yellow
            Remove-Item -Path $AGENT_INSTALL_DIR -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        # Rimuovi configurazione
        $configPath = "C:\ProgramData\checkmk"
        if (Test-Path $configPath) {
            Write-Host "🗑️  Rimozione directory configurazione..." -ForegroundColor $Colors.Yellow
            Remove-Item -Path $configPath -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        # Termina processi rimasti
        Get-Process -Name "check_mk_agent" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        
        Write-Host "`n✅ CheckMK Agent disinstallato completamente" -ForegroundColor $Colors.Green
        Write-Host "📋 File rimossi:" -ForegroundColor $Colors.Cyan
        Write-Host "   • $AGENT_INSTALL_DIR" -ForegroundColor $Colors.Gray
        Write-Host "   • C:\ProgramData\checkmk\" -ForegroundColor $Colors.Gray
        Write-Host "   • Servizio Windows 'CheckMK Agent'" -ForegroundColor $Colors.Gray
    }
    catch {
        Write-Host "❌ Errore durante disinstallazione Agent: $_" -ForegroundColor $Colors.Red
    }
}

# =====================================================
# Funzione: Crea directory download
# =====================================================
function Initialize-DownloadDir {
    if (-not (Test-Path $DOWNLOAD_DIR)) {
        New-Item -ItemType Directory -Path $DOWNLOAD_DIR -Force | Out-Null
    }
}

# =====================================================
# Funzione: Installa CheckMK Agent
# =====================================================
function Install-CheckMKAgent {
    Write-Host "`n`n"
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Cyan
    Write-Host "║  INSTALLAZIONE CHECKMK AGENT PER WINDOWS                 ║" -ForegroundColor $Colors.Cyan
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Cyan
    
    Initialize-DownloadDir
    
    # Download MSI
    $msiFile = "$DOWNLOAD_DIR\check-mk-agent-${CHECKMK_VERSION}-1_all.msi"
    
    Write-Host "`n📦 Download CheckMK Agent v${CHECKMK_VERSION}..." -ForegroundColor $Colors.Yellow
    Write-Host "   URL: $CHECKMK_MSI_URL" -ForegroundColor $Colors.Gray
    
    try {
        if (-not (Test-Path $msiFile)) {
            Write-Host "   ⏳ Download in corso..." -ForegroundColor $Colors.Cyan
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            (New-Object Net.WebClient).DownloadFile($CHECKMK_MSI_URL, $msiFile)
        }
        
        if (-not (Test-Path $msiFile) -or (Get-Item $msiFile).Length -eq 0) {
            Write-Host "❌ Errore: File MSI non valido" -ForegroundColor $Colors.Red
            return $false
        }
        
        Write-Host "   ✅ Download completato ($('{0:N2}' -f ((Get-Item $msiFile).Length/1MB)) MB)" -ForegroundColor $Colors.Green
    }
    catch {
        Write-Host "❌ Errore durante download: $_" -ForegroundColor $Colors.Red
        return $false
    }
    
    # Installa MSI
    Write-Host "`n🔧 Installazione in corso..." -ForegroundColor $Colors.Yellow
    try {
        $msiLog = "$DOWNLOAD_DIR\checkmk-install.log"
        $installArgs = @(
            "/i"
            $msiFile
            "/qn"
            "/norestart"
            "/l*v"
            $msiLog
        )
        
        $process = Start-Process -FilePath "msiexec.exe" -ArgumentList $installArgs -Wait -PassThru
        
        if ($process.ExitCode -eq 0 -or $process.ExitCode -eq 3010) {
            Write-Host "   ✅ Installazione completata" -ForegroundColor $Colors.Green
            
            # Avvia servizio
            Start-Sleep -Seconds 2
            $agentService = Get-Service -Name "CheckMK Agent" -ErrorAction SilentlyContinue
            if ($agentService) {
                if ($agentService.Status -ne "Running") {
                    Start-Service -Name "CheckMK Agent"
                }
                Write-Host "   ✅ Servizio CheckMK Agent avviato" -ForegroundColor $Colors.Green
            }
            
            return $true
        }
        else {
            Write-Host "❌ Errore installazione (Exit code: $($process.ExitCode))" -ForegroundColor $Colors.Red
            Write-Host "   Log: $msiLog" -ForegroundColor $Colors.Gray
            return $false
        }
    }
    catch {
        Write-Host "❌ Errore durante installazione: $_" -ForegroundColor $Colors.Red
        return $false
    }
}

# =====================================================
# Funzione: Installa FRPC
# =====================================================
function Install-FRPC {
    Write-Host "`n`n"
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Blue
    Write-Host "║  INSTALLAZIONE FRPC CLIENT PER WINDOWS                   ║" -ForegroundColor $Colors.Blue
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Blue
    
    Initialize-DownloadDir
    
    # Download FRPC
    $zipFile = "$DOWNLOAD_DIR\frp_${FRP_VERSION}_windows_amd64.zip"
    
    Write-Host "`n📦 Download FRPC v${FRP_VERSION}..." -ForegroundColor $Colors.Yellow
    Write-Host "   URL: $FRP_URL" -ForegroundColor $Colors.Gray
    
    try {
        if (-not (Test-Path $zipFile)) {
            Write-Host "   ⏳ Download in corso..." -ForegroundColor $Colors.Cyan
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            (New-Object Net.WebClient).DownloadFile($FRP_URL, $zipFile)
        }
        
        if (-not (Test-Path $zipFile) -or (Get-Item $zipFile).Length -eq 0) {
            Write-Host "❌ Errore: File ZIP non valido" -ForegroundColor $Colors.Red
            return $false
        }
        
        Write-Host "   ✅ Download completato ($('{0:N2}' -f ((Get-Item $zipFile).Length/1MB)) MB)" -ForegroundColor $Colors.Green
    }
    catch {
        Write-Host "❌ Errore durante download: $_" -ForegroundColor $Colors.Red
        return $false
    }
    
    # Estrai ZIP
    Write-Host "`n📦 Estrazione archivio..." -ForegroundColor $Colors.Yellow
    try {
        # Crea directory installazione
        if (-not (Test-Path $FRPC_INSTALL_DIR)) {
            New-Item -ItemType Directory -Path $FRPC_INSTALL_DIR -Force | Out-Null
        }
        
        # Estrai ZIP
        Expand-Archive -Path $zipFile -DestinationPath $DOWNLOAD_DIR -Force
        
        # Copia frpc.exe
        $extractedDir = Get-ChildItem "$DOWNLOAD_DIR" -Directory | Where-Object {$_.Name -like "frp_*"} | Select-Object -First 1
        if ($extractedDir) {
            $frpcExe = Join-Path $extractedDir.FullName "frpc.exe"
            if (Test-Path $frpcExe) {
                Copy-Item -Path $frpcExe -Destination "$FRPC_INSTALL_DIR\frpc.exe" -Force
                Write-Host "   ✅ frpc.exe copiato" -ForegroundColor $Colors.Green
            }
        }
        
        # Verifica
        if (-not (Test-Path "$FRPC_INSTALL_DIR\frpc.exe")) {
            Write-Host "❌ Errore: frpc.exe non trovato" -ForegroundColor $Colors.Red
            return $false
        }
    }
    catch {
        Write-Host "❌ Errore durante estrazione: $_" -ForegroundColor $Colors.Red
        return $false
    }
    
    # Configura FRPC
    Write-Host "`n📋 Configurazione FRPC..." -ForegroundColor $Colors.Yellow
    
    # Crea directory config
    if (-not (Test-Path $FRPC_CONFIG_DIR)) {
        New-Item -ItemType Directory -Path $FRPC_CONFIG_DIR -Force | Out-Null
    }
    
    # Input utente
    $computerName = $env:COMPUTERNAME
    Write-Host "`nInserisci le informazioni per la configurazione FRPC:`n" -ForegroundColor $Colors.Yellow
    
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
# Configurazione FRPC Client
# Generato il $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

[common]
server_addr = "$frpServer"
server_port = 7000
auth.method = "token"
auth.token  = "$authToken"
tls.enable = true
log.to = "$($FRPC_LOG_DIR)\frpc.log"
log.level = "debug"

[$frpcHostname]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = $remotePort
"@
    
    $tomlFile = "$FRPC_CONFIG_DIR\frpc.toml"
    Set-Content -Path $tomlFile -Value $tomlConfig
    
    Write-Host "`n📝 Configurazione salvata in: $tomlFile" -ForegroundColor $Colors.Green
    
    # Crea servizio Windows
    Write-Host "`n🔧 Creazione servizio Windows..." -ForegroundColor $Colors.Yellow
    
    try {
        # Ferma servizio se esiste
        $existingService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($existingService) {
            Stop-Service -Name "frpc" -Force -ErrorAction SilentlyContinue
            sc.exe delete frpc | Out-Null
            Start-Sleep -Seconds 1
        }
        
        # Crea servizio
        $frpcPath = "$FRPC_INSTALL_DIR\frpc.exe"
        sc.exe create frpc `
            binPath= "$frpcPath -c $tomlFile" `
            start= auto `
            displayname= "FRP Client Service" | Out-Null
        
        # Avvia servizio
        Start-Service -Name "frpc" -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        
        # Verifica
        $frpcService = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
        if ($frpcService -and $frpcService.Status -eq "Running") {
            Write-Host "   ✅ Servizio FRPC avviato" -ForegroundColor $Colors.Green
        }
        else {
            Write-Host "   ⚠️  Servizio creato ma non avviato (verifica configurazione)" -ForegroundColor $Colors.Yellow
        }
    }
    catch {
        Write-Host "   ❌ Errore creazione servizio: $_" -ForegroundColor $Colors.Red
    }
    
    Write-Host "`n📊 Configurazione FRPC:" -ForegroundColor $Colors.Cyan
    Write-Host "   Server:      $frpServer`:7000" -ForegroundColor $Colors.Green
    Write-Host "   Tunnel:      $frpcHostname" -ForegroundColor $Colors.Green
    Write-Host "   Porta remota: $remotePort" -ForegroundColor $Colors.Green
    Write-Host "   Porta locale: 6556" -ForegroundColor $Colors.Green
    
    return $true
}

# =====================================================
# Funzione: Mostra riepilogo finale
# =====================================================
function Show-Summary {
    Write-Host "`n`n"
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Green
    Write-Host "║              INSTALLAZIONE COMPLETATA                     ║" -ForegroundColor $Colors.Green
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Green
    
    Write-Host "`n📋 RIEPILOGO:" -ForegroundColor $Colors.Cyan
    Write-Host "   ✓ CheckMK Agent installato (plain TCP 6556)" -ForegroundColor $Colors.Green
    Write-Host "   ✓ Servizio Windows attivo: CheckMK Agent" -ForegroundColor $Colors.Green
    
    if ($script:installFRPC -eq "yes") {
        Write-Host "   ✓ FRPC Client installato e configurato" -ForegroundColor $Colors.Green
        Write-Host "   ✓ Servizio Windows attivo: frpc" -ForegroundColor $Colors.Green
    }
    
    Write-Host "`n🔧 COMANDI UTILI:" -ForegroundColor $Colors.Cyan
    Write-Host "   Visualizza servizi:  Get-Service | Where-Object {`$_.Name -like '*CheckMK*' -or `$_.Name -like '*frpc*'}" -ForegroundColor $Colors.Yellow
    Write-Host "   Riavvia servizio:    Restart-Service -Name 'CheckMK Agent'" -ForegroundColor $Colors.Yellow
    Write-Host "   Visualizza stato:    Get-Service -Name 'CheckMK Agent' | Format-List" -ForegroundColor $Colors.Yellow
    
    if ($script:installFRPC -eq "yes") {
        Write-Host "   Log FRPC:            Get-Content 'C:\ProgramData\frp\logs\frpc.log' -Tail 50" -ForegroundColor $Colors.Yellow
    }
    
    Write-Host "`n🎉 Installazione terminata con successo!`n" -ForegroundColor $Colors.Green
}

# =====================================================
# MAIN SCRIPT
# =====================================================

try {
    # Mostra header
    Write-Host "`n"
    Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Cyan
    Write-Host "║  Installazione Interattiva CheckMK Agent + FRPC per Windows║" -ForegroundColor $Colors.Cyan
    Write-Host "║  Version: 1.0 - 2025-11-07                                ║" -ForegroundColor $Colors.Cyan
    Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Cyan

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
                Write-Host "❌ Parametro non valido: $($args[0])" -ForegroundColor $Colors.Red
                Show-Usage
                exit 1
            }
        }
    }

    # Verifica Administrator
    if (-not (Test-Administrator)) {
    Write-Host "❌ Errore: Questo script deve essere eseguito come Administrator" -ForegroundColor $Colors.Red
    Write-Host "   Riavvia PowerShell come Administrator e riprova." -ForegroundColor $Colors.Gray
    exit 1
}

# Modalità disinstallazione
if ($MODE -eq "uninstall-frpc") {
    Uninstall-FRPC
    exit 0
}
elseif ($MODE -eq "uninstall-agent") {
    Uninstall-CheckMKAgent
    exit 0
}
elseif ($MODE -eq "uninstall-all") {
    Write-Host "`n❗ DISINSTALLAZIONE COMPLETA`n" -ForegroundColor $Colors.Red
    $confirm = Read-Host "Sei sicuro di voler rimuovere tutto (Agent + FRPC)? [s/N]"
    if ($confirm -match "^[sS]$") {
        Uninstall-FRPC
        Write-Host ""
        Uninstall-CheckMKAgent
        Write-Host "`n🎉 Disinstallazione completa terminata!`n" -ForegroundColor $Colors.Green
    }
    else {
        Write-Host "`n❌ Operazione annullata`n" -ForegroundColor $Colors.Cyan
    }
    exit 0
}

# Modalità installazione
Write-Host "`n📊 Rilevamento Sistema Operativo..." -ForegroundColor $Colors.Cyan
$osInfo = Detect-WindowsOS

Write-Host "`n"
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor $Colors.Cyan
Write-Host "║             RILEVAMENTO SISTEMA OPERATIVO                 ║" -ForegroundColor $Colors.Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor $Colors.Cyan

Write-Host "`n📌 Sistema Rilevato:" -ForegroundColor $Colors.Yellow
Write-Host "   OS: $($osInfo.Name)" -ForegroundColor $Colors.Green
Write-Host "   Versione: $($osInfo.Version)" -ForegroundColor $Colors.Green
Write-Host "   Architettura: $($osInfo.Architecture)" -ForegroundColor $Colors.Green

Write-Host "`n📌 Questa installazione utilizzerà:" -ForegroundColor $Colors.Yellow
Write-Host "   • CheckMK Agent (plain TCP on port 6556)" -ForegroundColor $Colors.Gray
Write-Host "   • Servizio Windows: CheckMK Agent" -ForegroundColor $Colors.Gray

Write-Host "`n$("="*62)" -ForegroundColor $Colors.Yellow
$confirmSystem = Read-Host "Procedi con l'installazione su questo sistema? [s/N]"
Write-Host "$("="*62)" -ForegroundColor $Colors.Yellow

if ($confirmSystem -notmatch "^[sS]$") {
    Write-Host "`n❌ Installazione annullata dall'utente`n" -ForegroundColor $Colors.Cyan
    exit 0
}

Write-Host "`n✅ Procedendo con l'installazione...`n" -ForegroundColor $Colors.Green

# Installa Agent
if (Install-CheckMKAgent) {
    Write-Host "`n✅ CheckMK Agent installato con successo" -ForegroundColor $Colors.Green
}
else {
    Write-Host "`n❌ Errore nell'installazione di CheckMK Agent" -ForegroundColor $Colors.Red
    exit 1
}

# Chiedi FRPC
Write-Host "`n$("="*62)" -ForegroundColor $Colors.Yellow
$installFRPC = Read-Host "Vuoi installare anche FRPC? [s/N]"
Write-Host "$("="*62)" -ForegroundColor $Colors.Yellow

$script:installFRPC = "no"
if ($installFRPC -match "^[sS]$") {
    $script:installFRPC = "yes"
    if (-not (Install-FRPC)) {
        Write-Host "`n⚠️  FRPC non installato, ma Agent è operativo" -ForegroundColor $Colors.Yellow
    }
}
else {
    Write-Host "`n⏭️  Installazione FRPC saltata" -ForegroundColor $Colors.Yellow
}

# Mostra riepilogo
Show-Summary

} catch {
    Write-Host "`n`n❌ ERRORE DURANTE L'ESECUZIONE:" -ForegroundColor $Colors.Red
    Write-Host "   $_" -ForegroundColor $Colors.Red
    Write-Host "`nTraccia stack:" -ForegroundColor $Colors.DarkYellow
    Write-Host $_.ScriptStackTrace -ForegroundColor $Colors.Gray
    exit 1
}
