<#
.SYNOPSIS
  Installazione dell'agente CheckMK su Windows, in modalita' plain (nessuna
  restrizione IP, nessun TLS) - equivalente Windows dell'agente classico.

.DESCRIPTION
  - Download dell'MSI agente CheckMK dal server configurato
  - Installazione/aggiornamento silenzioso (msiexec /quiet)
  - Abilita connessioni non protette su cmk-agent-ctl.exe
    (delete-all --enable-insecure-connections), senza IP allowlist:
    l'agente Windows moderno include sempre cmk-agent-ctl.exe (non esiste
    piu' un agente Windows "puro" senza di esso), ma qui viene lasciato
    completamente aperto, equivalente in termini di sicurezza al vecchio
    agente classico plain usato su Linux prima della conversione a
    ip_allowlist - nessuna restrizione, nessun TLS.

.PARAMETER ServerUrl
  Base Checkmk server URL (default: https://monitor.nethlab.it)

.PARAMETER Site
  Checkmk site name (default: monitoring)

.PARAMETER Uninstall
  Disinstalla l'agente CheckMK e rimuove la configurazione cmk-agent-ctl.

.REQUIREMENTS
  PowerShell 5.1+, Windows 64-bit, privilegi amministratore

.USAGE
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$ServerUrl = "https://monitor.nethlab.it",
    [string]$Site = "monitoring",
    [switch]$Uninstall
)

$ScriptVersion = "2.0.0"
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$CmkAgentDir        = "C:\ProgramData\checkmk\agent"
$CmkAgentCtlExe     = "C:\Program Files (x86)\checkmk\service\cmk-agent-ctl.exe"

# ===============================
# Utility
# ===============================
function Write-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "WARN", "ERROR", "OK")] [string]$Level = "INFO"
    )
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "OK"    { "Green" }
        default { "White" }
    }
    Write-Host "[$ts] [$Level] $Message" -ForegroundColor $color
}

function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p  = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LocalAgentVersion {
    $uninstallPaths = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    foreach ($path in $uninstallPaths) {
        $entry = Get-ItemProperty $path -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like "*Checkmk Agent*" -or $_.DisplayName -like "*Check_MK Agent*" } |
            Select-Object -First 1
        if ($entry) { return $entry }
    }
    return $null
}

# ===============================
# Agent install/uninstall
# ===============================
function Install-CheckmkAgent {
    $msiUrl = "$ServerUrl/$Site/check_mk/agents/windows/check_mk_agent.msi"
    $tempMsi = Join-Path $env:TEMP "check_mk_agent.msi"
    Write-Log "Download agente CheckMK: $msiUrl" "INFO"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $msiUrl -OutFile $tempMsi -UseBasicParsing

    Write-Log "Installazione MSI (msiexec /quiet)..." "INFO"
    $logPath = Join-Path $env:TEMP "checkmk-agent-install.log"
    $proc = Start-Process msiexec.exe -ArgumentList "/i `"$tempMsi`" /quiet /norestart /l*v `"$logPath`"" -Wait -PassThru
    Remove-Item $tempMsi -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        throw "msiexec fallito con codice $($proc.ExitCode) - vedi $logPath"
    }
    Write-Log "Agente CheckMK installato" "OK"
}

function Uninstall-CheckmkAgent {
    $entry = Get-LocalAgentVersion
    if (-not $entry) {
        Write-Log "Nessun agente CheckMK installato, nulla da rimuovere" "WARN"
    } else {
        Write-Log "Disinstallazione agente CheckMK ($($entry.DisplayVersion))..." "INFO"
        if ($entry.PSChildName -match '^\{.*\}$') {
            Start-Process msiexec.exe -ArgumentList "/x $($entry.PSChildName) /quiet /norestart" -Wait | Out-Null
        } else {
            Start-Process cmd.exe -ArgumentList "/c $($entry.UninstallString) /quiet" -Wait | Out-Null
        }
        Write-Log "Agente CheckMK disinstallato" "OK"
    }

    if (Test-Path $CmkAgentCtlExe) {
        & $CmkAgentCtlExe delete-all --enable-insecure-connections 2>&1 | Out-Null
    }
    if (Test-Path $CmkAgentDir) {
        Remove-Item -Path $CmkAgentDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "Rimossa configurazione: $CmkAgentDir" "OK"
    }
}

# ===============================
# Plain, no restrictions (equivalente Windows dell'agente classico)
# ===============================
function Find-CheckmkAgentService {
    $svc = Get-Service | Where-Object {
        $_.Name -eq "CheckmkService" -or
        $_.DisplayName -like "*Checkmk*" -or
        $_.Name -like "*check_mk_agent*"
    } | Select-Object -First 1
    return $svc
}

function Set-PlainConfig {
    if (-not (Test-Path $CmkAgentCtlExe)) {
        throw "cmk-agent-ctl.exe non trovato in: $CmkAgentCtlExe (l'agente e' installato correttamente?)"
    }

    Write-Log "Rimozione registrazione TLS esistente e abilitazione connessioni non protette (nessuna restrizione IP)..." "INFO"
    & $CmkAgentCtlExe delete-all --enable-insecure-connections 2>&1 | ForEach-Object { Write-Log $_ "INFO" }

    $svc = Find-CheckmkAgentService
    if ($svc) {
        Write-Log "Riavvio servizio '$($svc.DisplayName)' ($($svc.Name))..." "INFO"
        Restart-Service -Name $svc.Name -Force
        Write-Log "Servizio riavviato" "OK"
    } else {
        Write-Log "Servizio agente CheckMK non trovato tramite Get-Service - riavviarlo manualmente" "WARN"
    }
}

# ===============================
# MAIN
# ===============================
try {
    if (-not (Test-Administrator)) { throw "Esegui PowerShell come Amministratore" }
    if (-not [Environment]::Is64BitOperatingSystem) { throw "Richiesto Windows 64-bit" }

    Write-Log "=== install-checkmk-agent-windows.ps1 v$ScriptVersion ===" "OK"

    if ($Uninstall) {
        Uninstall-CheckmkAgent
        Write-Log "=== Disinstallazione completata ===" "OK"
        exit 0
    }

    Install-CheckmkAgent
    Set-PlainConfig

    Write-Log "" "INFO"
    Write-Log "=== INSTALLAZIONE COMPLETATA ===" "OK"
    Write-Log "  Agente CheckMK   : porta 6556, plain, nessuna restrizione IP" "INFO"
    Write-Log "" "INFO"
    Write-Log "Verifica:" "INFO"
    Write-Log "  & '$CmkAgentCtlExe' status" "INFO"

    exit 0
}
catch {
    Write-Log "ERRORE: $($_.Exception.Message)" "ERROR"
    exit 1
}
