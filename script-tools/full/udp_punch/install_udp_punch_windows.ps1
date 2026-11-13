<#
.SYNOPSIS
  Installer for the UDP punch tunnel host role on Windows.

.DESCRIPTION
  Installs one peer of the tunnel on a Windows machine. The peer forwards
  every stream to a local TCP target, by default the CheckMK Windows agent
  on 127.0.0.1:6556, and reaches the tunnel server over UDP.

  The script copies the peer to the install directory, writes the JSON
  configuration, generates or imports the pre-shared key, restricts its
  ACL, opens the UDP port in Windows Firewall, registers a scheduled task
  that starts the peer at boot as SYSTEM and starts it immediately.

.PARAMETER StunServer
  STUN server used to learn the public mapping, empty to disable.

.PARAMETER UdpBind
  Local UDP bind address, default 0.0.0.0:6015.

.PARAMETER Peer
  Public endpoint of the tunnel server as host:port. Empty means no peer
  endpoint file is written and the address is learned at runtime.

.PARAMETER Target
  Local TCP target for every stream, default 127.0.0.1:6556.

.PARAMETER PskFile
  Copy an existing pre-shared key (32 bytes as hex) instead of generating it.

.PARAMETER InstallDir
  Installation directory, default C:\ProgramData\cmk-punch.

.PARAMETER AdvertiseIp
  Address announced in the handshake; empty lets the peer detect it.

.PARAMETER NoFirewallRule
  Do not create the inbound UDP firewall rule.

.PARAMETER NoStart
  Register the scheduled task but do not start it now.

.PARAMETER Staging
  Write only the files: no firewall rule, no scheduled task, no start, and
  no administrator requirement. Used to rehearse the installation.

.PARAMETER Force
  Replace an existing configuration (a backup is kept).

.PARAMETER Uninstall
  Remove the scheduled task, the firewall rule and the peer code. The
  configuration and the pre-shared key are kept unless -Purge is given.

.PARAMETER Purge
  With -Uninstall, also delete configuration, pre-shared key and state.

.REQUIREMENTS
  Windows 64-bit, PowerShell 5.1+, Administrator, Python 3 with the
  cryptography package.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1 -Peer <server>:6015
  powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1 -PskFile .\psk -Peer <server>:6015
  powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1 -Staging -InstallDir C:\Temp\cmk-punch
  powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1 -Uninstall
  powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1 -Uninstall -Purge
#>

[CmdletBinding()]
param(
    [string]$StunServer = "stun.l.google.com:19302",
    [string]$UdpBind = "0.0.0.0:6015",
    [string]$Peer = "",
    [string]$Target = "127.0.0.1:6556",
    [string]$PskFile = "",
    [string]$InstallDir = "C:\ProgramData\cmk-punch",
    [string]$AdvertiseIp = "",
    [string]$ExeDir = "",
    [switch]$NoFirewallRule,
    [switch]$NoStart,
    [switch]$Staging,
    [switch]$Force,
    [switch]$NoAvExclusion,
    [switch]$Uninstall,
    [switch]$Purge
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Stop"
$TaskName = "cmk-punch-host"
$FirewallName = "cmk-punch host UDP"

$PeerDir = Join-Path $InstallDir "peer"
$EtcDir = Join-Path $InstallDir "etc"
$StateDir = Join-Path $InstallDir "state"
$LogDir = Join-Path $InstallDir "logs"
$ConfigPath = Join-Path $EtcDir "host.json"
$PeerFilePath = Join-Path $EtcDir "peer.json"
$PskPath = Join-Path $EtcDir "psk"
$RunCmd = Join-Path $InstallDir "run.cmd"
$LogPath = Join-Path $LogDir "peer.log"

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Info($Message) {
    Write-Host "[INFO] $Message"
}

function Require-Admin {
    if ($Staging) { return }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Fail "this installer needs an elevated PowerShell"
    }
}

function Find-Python {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Fail "python.exe not found in PATH: install Python 3 and the cryptography package"
    }
    return $cmd.Source
}

function Test-Cryptography($Python) {
    & $Python -c "import cryptography" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail "the cryptography package is missing: $Python -m pip install cryptography"
    }
    foreach ($name in @("protocol.py", "punch_peer.py")) {
        $path = Join-Path $PSScriptRoot $name
        & $Python -B -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" $path
        if ($LASTEXITCODE -ne 0) {
            Fail "$name does not compile"
        }
    }
}

function New-Psk {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Write-Json($Path, $Object) {
    $Object | ConvertTo-Json -Depth 5 | Set-Content -Path $Path -Encoding ASCII
}

function Protect-File($Path) {
    icacls $Path /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
}

function Get-ThirdPartyAv {
    $names = @()
    try {
        Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction Stop |
            ForEach-Object {
                if ($_.displayName -and $_.displayName -ne "Windows Defender") {
                    $names += $_.displayName
                }
            }
    } catch {
    }
    return @($names | Sort-Object -Unique)
}

function Set-AvExclusion($Path, [switch]$Remove) {
    $thirdParty = Get-ThirdPartyAv
    if ($thirdParty.Count -gt 0) {
        Info "third-party antivirus detected: $($thirdParty -join ', ')"
        if (-not $Remove) {
            Info "create this exclusion in its console: $Path"
        }
        return
    }
    $status = Get-MpComputerStatus -ErrorAction SilentlyContinue
    if (-not $status -or -not $status.AMServiceEnabled) {
        return
    }
    if ($Staging) {
        Info "staging: Defender exclusion not changed for $Path"
        return
    }
    if ($Remove) {
        Remove-MpPreference -ExclusionPath $Path -ErrorAction SilentlyContinue
        Info "removed the Defender exclusion for $Path"
    } else {
        Add-MpPreference -ExclusionPath $Path -ErrorAction SilentlyContinue
        Info "added the Defender exclusion for $Path"
    }
}

function Backup-File($Path) {
    if (Test-Path $Path) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $dest = "$Path.bak-$stamp"
        Copy-Item $Path $dest
        Info "backed up $Path as $(Split-Path $dest -Leaf)"
    }
}

if ($Uninstall) {
    Require-Admin
    if (-not $Staging) {
        $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($task) {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Info "removed scheduled task $TaskName"
        }
        Get-NetFirewallRule -DisplayName "$FirewallName*" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-NetFirewallRule -Name $_.Name
            Info "removed firewall rule $($_.DisplayName)"
        }
    }
    foreach ($path in @($PeerDir, $RunCmd)) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
            Info "removed $path"
        }
    }
    if (-not $NoAvExclusion) {
        Set-AvExclusion $InstallDir -Remove
    }
    if ($Purge) {
        foreach ($path in @($EtcDir, $StateDir, $LogDir)) {
            if (Test-Path $path) {
                Remove-Item $path -Recurse -Force
                Info "removed $path"
            }
        }
    } else {
        Info "kept configuration and state in $EtcDir and $StateDir (use -Purge to remove them)"
    }
    exit 0
}

Require-Admin

$exePath = $null
if ($ExeDir) {
    $exePath = Join-Path $ExeDir "cmk-punch.exe"
    if (-not (Test-Path $exePath)) {
        Fail "cmk-punch.exe not found in $ExeDir"
    }
} else {
    $autoExe = Join-Path $PSScriptRoot "dist\cmk-punch\cmk-punch.exe"
    if (Test-Path $autoExe) {
        $exePath = $autoExe
    }
}

if ($exePath) {
    Info "using the executable $exePath"
} else {
    foreach ($name in @("protocol.py", "punch_peer.py")) {
        if (-not (Test-Path (Join-Path $PSScriptRoot $name))) {
            Fail "$name is missing next to this installer"
        }
    }
    $Python = Find-Python
    Test-Cryptography $Python
    Info "using $Python"
}
if (-not $NoAvExclusion) {
    Set-AvExclusion $InstallDir
}

if ((Test-Path $ConfigPath) -and -not $Force) {
    Fail "$ConfigPath exists, use -Force to replace it (a backup is kept)"
}

New-Item -ItemType Directory -Force -Path $PeerDir, $EtcDir, $StateDir, $LogDir | Out-Null
if ($exePath) {
    Copy-Item (Join-Path (Split-Path $exePath -Parent) "*") $PeerDir -Recurse -Force
    Info "installed the executable in $PeerDir"
} else {
    foreach ($name in @("protocol.py", "punch_peer.py")) {
        $dest = Join-Path $PeerDir $name
        Backup-File $dest
        Copy-Item (Join-Path $PSScriptRoot $name) $dest -Force
    }
    Info "installed the peer code in $PeerDir"
}

if (Test-Path $PskPath) {
    Info "reusing the existing PSK $PskPath"
} elseif ($PskFile) {
    $content = (Get-Content -Path $PskFile -Raw).Trim()
    if ($content -notmatch "^[0-9a-fA-F]{64}$") {
        Fail "-PskFile must contain 32 bytes as hex"
    }
    [IO.File]::WriteAllText($PskPath, $content.ToLower() + "`n", (New-Object System.Text.ASCIIEncoding))
    Info "copied the PSK from $PskFile"
} else {
    [IO.File]::WriteAllText($PskPath, (New-Psk) + "`n", (New-Object System.Text.ASCIIEncoding))
    Info "generated a new PSK"
}
$hash = (Get-FileHash -Path $PskPath -Algorithm SHA256).Hash.ToLower()
if (-not $Staging) {
    Protect-File $PskPath
}

$config = [ordered]@{
    role = "host"
    psk_file = $PskPath
    udp_bind = $UdpBind
    peer_file = $PeerFilePath
    state_dir = $StateDir
    target = $Target
    keepalive_s = 15
    punch_interval_s = 1.0
}
if ($StunServer) { $config["stun_server"] = $StunServer }
if ($AdvertiseIp) { $config["advertise_ip"] = $AdvertiseIp }

if (Test-Path $ConfigPath) { Backup-File $ConfigPath }
Write-Json $ConfigPath $config
Info "wrote $ConfigPath"

if ($Peer) {
    Write-Json $PeerFilePath ([ordered]@{ peer = $Peer })
    Info "wrote $PeerFilePath"
}

if ($exePath) {
    $runContent = @"
@echo off
"$PeerDir\cmk-punch.exe" --config "$ConfigPath" >> "$LogPath" 2>&1
"@
} else {
    $runContent = @"
@echo off
"$Python" "$PeerDir\punch_peer.py" --config "$ConfigPath" >> "$LogPath" 2>&1
"@
}
Set-Content -Path $RunCmd -Value $runContent -Encoding ASCII
Info "wrote $RunCmd"

if (-not $Staging -and -not $NoFirewallRule) {
    $port = ($UdpBind -split ":")[-1]
    Get-NetFirewallRule -DisplayName "$FirewallName $port" -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-NetFirewallRule -Name $_.Name
    }
    New-NetFirewallRule -DisplayName "$FirewallName $port" -Direction Inbound -Action Allow -Protocol UDP -LocalPort $port -Profile Any | Out-Null
    Info "opened inbound UDP $port in Windows Firewall"
}

if (-not $Staging) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument "/c `"$RunCmd`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Info "registered scheduled task $TaskName (at startup, as SYSTEM)"
    if (-not $NoStart) {
        Start-ScheduledTask -TaskName $TaskName
        Info "started $TaskName"
    }
} else {
    Info "staging: firewall, task and start skipped"
}

$mode = if ($exePath) { "executable" } else { "python" }
Write-Host ""
Info "installation complete for the host role"
Write-Host "  mode:        $mode"
Write-Host "  install dir: $InstallDir"
Write-Host "  config:      $ConfigPath"
Write-Host "  psk:         $PskPath (restricted ACL)"
Write-Host "  psk sha256:  $hash"
Write-Host "  target:      $Target"
Write-Host "  log:         $LogPath"
Write-Host ""
Write-Host "  Copy the psk file to the other peer and install it there so both share the same key."
Write-Host "  Check the peer with: Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "  Log tail: Get-Content '$LogPath' -Tail 20"
