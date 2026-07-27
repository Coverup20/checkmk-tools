<#
.SYNOPSIS
  Installazione dell'agente CheckMK su Windows, con bind IP opzionale.

.DESCRIPTION
  - Download dell'MSI agente CheckMK dal server configurato
  - Installazione/aggiornamento silenzioso (msiexec /quiet)
  - Abilita il plain pull nativo di cmk-agent-ctl.exe
    (delete-all --enable-insecure-connections), niente TLS/certificati custom
  - Chiede interattivamente se limitare l'accesso a un IP specifico:
      - se si', chiede l'IP e lo scrive in cmk-agent-ctl.toml (allowed_ip)
      - se no, il plain pull resta senza restrizioni IP

.PARAMETER ServerUrl
  Base Checkmk server URL (default: https://monitor.nethlab.it)

.PARAMETER Site
  Checkmk site name (default: monitoring)

.PARAMETER AllowedIp
  IP da autorizzare nell'allowlist di cmk-agent-ctl. Se fornito, salta il
  prompt e applica direttamente il bind a questo IP.

.PARAMETER NoBind
  Salta il prompt e non applica nessuna restrizione IP (plain pull aperto).

.PARAMETER Quick
  Alias di -NoBind, per uso non interattivo senza specificare un IP.

.PARAMETER Uninstall
  Disinstalla l'agente CheckMK e rimuove la configurazione cmk-agent-ctl.

.REQUIREMENTS
  PowerShell 5.1+, Windows 64-bit, privilegi amministratore

.USAGE
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -AllowedIp 127.0.0.1
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -NoBind
  powershell -ExecutionPolicy Bypass -File .\install-checkmk-agent-windows.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$ServerUrl = "https://monitor.nethlab.it",
    [string]$Site = "monitoring",
    [string]$AllowedIp = "",
    [switch]$NoBind,
    [switch]$Quick,
    [switch]$Uninstall
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$CmkAgentDir        = "C:\ProgramData\checkmk\agent"
$CmkAgentCtlToml    = Join-Path $CmkAgentDir "cmk-agent-ctl.toml"
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

function Ask-BindIp {
    # Restituisce l'IP da autorizzare, oppure $null se l'utente non vuole
    # nessuna restrizione IP sul plain pull.
    Write-Host ""
    $ans = Read-Host "  Vuoi limitare l'accesso all'agente a un IP specifico? [s/N]"
    if ($ans -notmatch '^(s|si|y|yes)$') {
        return $null
    }
    while ($true) {
        $ip = Read-Host "  IP autorizzato"
        if ($ip -match '^\d{1,3}(\.\d{1,3}){3}$') { return $ip.Trim() }
        Write-Log "IP non valido, formato atteso: x.x.x.x" "WARN"
    }
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
# cmk-agent-ctl plain pull (+ IP allowlist opzionale)
# ===============================
function Find-CheckmkAgentService {
    $svc = Get-Service | Where-Object {
        $_.Name -eq "CheckmkService" -or
        $_.DisplayName -like "*Checkmk*" -or
        $_.Name -like "*check_mk_agent*"
    } | Select-Object -First 1
    return $svc
}

function Set-PlainPullConfig {
    param([string]$AllowedIp)  # vuoto/$null = nessuna restrizione IP

    if (-not (Test-Path $CmkAgentCtlExe)) {
        throw "cmk-agent-ctl.exe non trovato in: $CmkAgentCtlExe (l'agente e' installato correttamente?)"
    }

    Write-Log "Rimozione registrazione TLS esistente e abilitazione plain pull..." "INFO"
    & $CmkAgentCtlExe delete-all --enable-insecure-connections 2>&1 | ForEach-Object { Write-Log $_ "INFO" }

    if ($AllowedIp) {
        if (-not (Test-Path $CmkAgentDir)) {
            New-Item -Path $CmkAgentDir -ItemType Directory -Force | Out-Null
        }
        Set-Content -Path $CmkAgentCtlToml -Value "allowed_ip = [`"$AllowedIp`"]`n" -Encoding UTF8
        Write-Log "Scritto $CmkAgentCtlToml (allowed_ip=$AllowedIp)" "OK"
    } else {
        Write-Log "Nessuna restrizione IP applicata: plain pull aperto a qualsiasi indirizzo" "WARN"
    }

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

    if ($AllowedIp) {
        $resolvedIp = $AllowedIp
    } elseif ($NoBind -or $Quick) {
        $resolvedIp = $null
    } else {
        $resolvedIp = Ask-BindIp
    }

    Install-CheckmkAgent
    Set-PlainPullConfig -AllowedIp $resolvedIp

    Write-Log "" "INFO"
    Write-Log "=== INSTALLAZIONE COMPLETATA ===" "OK"
    if ($resolvedIp) {
        Write-Log "  Agente CheckMK   : porta 6556, plain pull, allowed_ip=$resolvedIp" "INFO"
    } else {
        Write-Log "  Agente CheckMK   : porta 6556, plain pull, nessuna restrizione IP" "INFO"
    }
    Write-Log "" "INFO"
    Write-Log "Verifica:" "INFO"
    Write-Log "  & '$CmkAgentCtlExe' status" "INFO"
    Write-Log "" "INFO"
    Write-Log "Se questo host deve essere raggiunto tramite tunnel FRP, installare" "INFO"
    Write-Log "separatamente: install-frpc-pc.ps1 (stessa cartella)" "INFO"

    exit 0
}
catch {
    Write-Log "ERRORE: $($_.Exception.Message)" "ERROR"
    exit 1
}
