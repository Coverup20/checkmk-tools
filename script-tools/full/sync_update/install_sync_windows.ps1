<#
.SYNOPSIS
  Installs the local-check sync tool on a Windows host.

.DESCRIPTION
  With Source github (default) it installs the anonymous downloader that reads
  the published GitHub release, verifies the checks and deploys them into the
  CheckMK agent local directory. With Source repo it installs the executable
  that reads a local repository copy instead. In both cases it writes the
  wrapper script and registers a scheduled task that runs at startup and every
  IntervalMinutes minutes as SYSTEM.

.PARAMETER Source
  github downloads the published release assets anonymously, repo syncs from a
  local repository copy.

.PARAMETER ExeDir
  Folder that contains sync-python-full-checks.exe. Empty means the default
  dist\sync-python-full-checks next to this script.

.PARAMETER InstallDir
  Installation directory, default C:\ProgramData\cmk-sync.

.PARAMETER RepoDir
  Local repository directory the sync reads the categories from, default
  checkmk-tools inside the install directory.

.PARAMETER Target
  CheckMK agent local directory, default C:\ProgramData\checkmk\agent\local.

.PARAMETER Category
  Category synced from the repository, default script-check-windows.

.PARAMETER IntervalMinutes
  Repetition interval of the scheduled task, default 5.

.PARAMETER NoStart
  Register the task without starting it now.

.PARAMETER Staging
  Write the files only: no scheduled task, no start, no administrator
  requirement.

.PARAMETER Force
  Replace an existing executable even when it is already present.

.PARAMETER Uninstall
  Remove the task and the executable. The repository and the logs are kept
  unless Purge is given.

.PARAMETER Purge
  With Uninstall, also delete the repository, the logs and the install
  directory.

.REQUIREMENTS
  Windows 64-bit, PowerShell 5.1+, Administrator (except with Staging).

.USAGE
  powershell -ExecutionPolicy Bypass -File .\install_sync_windows.ps1
  powershell -ExecutionPolicy Bypass -File .\install_sync_windows.ps1 -ExeDir .\dist\sync-python-full-checks
  powershell -ExecutionPolicy Bypass -File .\install_sync_windows.ps1 -Staging -InstallDir C:\Temp\cmk-sync
  powershell -ExecutionPolicy Bypass -File .\install_sync_windows.ps1 -Uninstall
  powershell -ExecutionPolicy Bypass -File .\install_sync_windows.ps1 -Uninstall -Purge
#>

[CmdletBinding()]
param(
    [string]$ExeDir = "",
    [ValidateSet("github", "repo")]
    [string]$Source = "github",
    [string]$InstallDir = "C:\ProgramData\cmk-sync",
    [string]$RepoDir = "",
    [string]$Target = "C:\ProgramData\checkmk\agent\local",
    [string]$Category = "script-check-windows",
    [int]$IntervalMinutes = 5,
    [switch]$NoStart,
    [switch]$Staging,
    [switch]$Force,
    [switch]$Uninstall,
    [switch]$Purge
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Stop"
$TaskName = "cmk-sync-local-checks"
$ExeName = "sync-python-full-checks"
$DownloaderName = "sync_winchecks.ps1"

$ToolDir = Join-Path $InstallDir "tool"
$DownloaderPath = Join-Path $InstallDir $DownloaderName
if (-not $RepoDir) { $RepoDir = Join-Path $InstallDir "checkmk-tools" }
$LogDir = Join-Path $InstallDir "logs"
$RunCmd = Join-Path $InstallDir "run-sync.cmd"
$LogPath = Join-Path $LogDir "sync.log"

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

function Resolve-ExeDir {
    if ($ExeDir) {
        $candidate = Join-Path $ExeDir "$ExeName.exe"
        if (-not (Test-Path $candidate)) {
            Fail "$ExeName.exe not found in $ExeDir"
        }
        return $ExeDir
    }
    $auto = Join-Path $PSScriptRoot "dist\$ExeName"
    if (Test-Path (Join-Path $auto "$ExeName.exe")) {
        return $auto
    }
    Fail "sync executable not found: build it first with build_sync_exe.ps1 or pass -ExeDir"
}

if ($Uninstall) {
    Require-Admin
    if (-not $Staging) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Info "removed scheduled task $TaskName"
    }
    foreach ($path in @($ToolDir, $RunCmd, $DownloaderPath)) {
        if (Test-Path $path) {
            Remove-Item $path -Recurse -Force
            Info "removed $path"
        }
    }
    if ($Purge) {
        if (Test-Path $InstallDir) {
            Remove-Item $InstallDir -Recurse -Force
            Info "removed $InstallDir"
        }
    } else {
        Info "kept repository and logs in $InstallDir (use -Purge to remove them)"
    }
    exit 0
}

Require-Admin

if ($Source -eq "github") {
    $downloaderSrc = Join-Path $PSScriptRoot $DownloaderName
    if (-not (Test-Path $downloaderSrc)) {
        Fail "$DownloaderName is missing next to this installer"
    }
} else {
    $sourceDir = Resolve-ExeDir
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
if ($Source -eq "github") {
    New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "staging") | Out-Null
    Copy-Item $downloaderSrc $DownloaderPath -Force
    Info "installed the downloader in $DownloaderPath"
} else {
    New-Item -ItemType Directory -Force -Path $ToolDir, (Join-Path $RepoDir "$Category\full") | Out-Null
    if ($Force -or -not (Test-Path (Join-Path $ToolDir "$ExeName.exe"))) {
        Copy-Item (Join-Path $sourceDir "*") $ToolDir -Recurse -Force
        Info "installed the executable in $ToolDir"
    } else {
        Info "executable already present in $ToolDir (use -Force to replace it)"
    }
}
if ($Staging) {
    Info "staging: target $Target left untouched"
} else {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
}

if ($Source -eq "github") {
    $runContent = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$DownloaderPath" -StagingDir "$InstallDir\staging" -Target "$Target" >> "$LogPath" 2>&1
"@
} else {
    $runContent = @"
@echo off
"$ToolDir\$ExeName.exe" --repo "$RepoDir" --target "$Target" --category $Category >> "$LogPath" 2>&1
"@
}
Set-Content -Path $RunCmd -Value $runContent -Encoding ASCII
Info "wrote $RunCmd (source: $Source)"

if (-not $Staging) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument "/c `"$RunCmd`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
    $trigger.Repetition = $repeat.Repetition
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Info "registered scheduled task $TaskName (startup and every $IntervalMinutes minutes, as SYSTEM)"
    if (-not $NoStart) {
        Start-ScheduledTask -TaskName $TaskName
        Info "started $TaskName"
    }
} else {
    Info "staging: scheduled task and start skipped"
}

Set-AvExclusion $InstallDir

Write-Host ""
Info "installation complete for the local-check sync"
if ($Source -eq "github") {
    Write-Host "  source:   GitHub release assets (anonymous download)"
    Write-Host "  tool:     $DownloaderPath"
} else {
    Write-Host "  source:   local repository $RepoDir"
    Write-Host "  tool:     $(Join-Path $ToolDir "$ExeName.exe")"
    Write-Host "  category: $Category"
}
Write-Host "  target:   $Target"
Write-Host "  log:      $LogPath"
Write-Host ""
if ($Source -eq "repo") {
    Write-Host "  Put the built check executables in $(Join-Path $RepoDir "$Category\full")."
}
Write-Host "  Run now: powershell -Command Start-ScheduledTask -TaskName $TaskName"
Write-Host "  Last run: Get-ScheduledTaskInfo -TaskName $TaskName"
Write-Host "  Log tail: Get-Content '$LogPath' -Tail 20"
