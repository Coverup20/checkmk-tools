<#
.SYNOPSIS
  Downloads the published Windows local checks from GitHub and deploys them.

.DESCRIPTION
  Reads the manifest.json of a public release, downloads only the checks that
  are missing or changed, verifies each sha256 in the staging directory, then
  moves them into the CheckMK agent local directory with atomic renames on the
  same volume. The previous version of a replaced check is kept in
  staging\previous, and checks that are no longer part of the release are
  removed from the local directory unless -NoPrune is given.

  No account is needed: the release assets of a public repository are
  downloaded anonymously over HTTPS. No repository clone is kept on the host.

.PARAMETER Repo
  Public GitHub repository, default Coverup20/checkmk-tools.

.PARAMETER Tag
  Release tag to apply, default the most recent release whose tag starts with
  winchecks-.

.PARAMETER StagingDir
  Directory that holds the verified downloads, default
  C:\ProgramData\cmk-sync\staging.

.PARAMETER Target
  CheckMK agent local directory, default C:\ProgramData\checkmk\agent\local.

.PARAMETER NoPrune
  Do not remove checks that are absent from the release.

.PARAMETER DryRun
  Report what would happen without downloading or changing anything.

.REQUIREMENTS
  Windows 64-bit, PowerShell 5.1+, outbound HTTPS. No GitHub account.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\sync_winchecks.ps1
  powershell -ExecutionPolicy Bypass -File .\sync_winchecks.ps1 -DryRun
  powershell -ExecutionPolicy Bypass -File .\sync_winchecks.ps1 -Tag winchecks-2026.11.13
#>

[CmdletBinding()]
param(
    [string]$Repo = "Coverup20/checkmk-tools",
    [string]$Tag = "",
    [string]$StagingDir = "C:\ProgramData\cmk-sync\staging",
    [string]$Target = "C:\ProgramData\checkmk\agent\local",
    [switch]$NoPrune,
    [switch]$DryRun
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Stop"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Headers = @{ "User-Agent" = "cmk-local-check-sync/$ScriptVersion" }

function Info($Message) {
    Write-Host "[INFO] $Message"
}

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

function Get-Json($Url) {
    try {
        return Invoke-RestMethod -Uri $Url -Headers $Headers -UseBasicParsing
    } catch {
        Fail "request failed: $Url ($($_.Exception.Message))"
    }
}

function Download-File($Url, $Path) {
    try {
        Invoke-WebRequest -Uri $Url -OutFile $Path -Headers $Headers -UseBasicParsing
    } catch {
        Fail "download failed: $Url ($($_.Exception.Message))"
    }
}

function File-Hash($Path) {
    if (-not (Test-Path $Path)) {
        return ""
    }
    return (Get-FileHash $Path -Algorithm SHA256).Hash.ToLower()
}

$api = "https://api.github.com/repos/$Repo/releases"

if ($Tag) {
    $release = Get-Json "$api/tags/$Tag"
} else {
    $releases = Get-Json "$api`?per_page=100"
    $release = $releases | Where-Object {
        -not $_.draft -and -not $_.prerelease -and $_.tag_name -like "winchecks-*"
    } | Select-Object -First 1
    if (-not $release) {
        Fail "no winchecks-* release found in $Repo"
    }
}

$tagName = $release.tag_name
Info "release: $tagName"

$manifestAsset = $release.assets | Where-Object { $_.name -eq "manifest.json" } | Select-Object -First 1
if (-not $manifestAsset) {
    Fail "manifest.json is missing from release $tagName"
}

New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
$manifestPath = Join-Path $StagingDir "manifest.json"
if (-not $DryRun) {
    Download-File $manifestAsset.browser_download_url $manifestPath
}
if (-not (Test-Path $manifestPath)) {
    Fail "manifest.json is not available in $StagingDir"
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$checks = $manifest.checks
if (-not $checks) {
    Info "the release contains no checks"
}

$downloaded = 0
$deployed = 0
$skipped = 0
$removed = 0

foreach ($check in $checks) {
    $stagedPath = Join-Path $StagingDir $check.name
    $targetPath = Join-Path $Target $check.name
    if ((File-Hash $targetPath) -eq $check.sha256) {
        Info "$($check.name): already up to date"
        $skipped++
        continue
    }
    if ((File-Hash $stagedPath) -eq $check.sha256) {
        Info "$($check.name): verified copy already in staging"
        continue
    }
    $asset = $release.assets | Where-Object { $_.name -eq $check.name } | Select-Object -First 1
    if (-not $asset) {
        Fail "asset $($check.name) is missing from release $tagName"
    }
    if ($DryRun) {
        Info "$($check.name): would download"
        continue
    }
    $partial = "$stagedPath.new"
    Download-File $asset.browser_download_url $partial
    if ((File-Hash $partial) -ne $check.sha256) {
        Remove-Item $partial -Force -ErrorAction SilentlyContinue
        Fail "$($check.name): sha256 mismatch, download discarded"
    }
    Move-Item -Force $partial $stagedPath
    Info "$($check.name): downloaded and verified"
    $downloaded++
}

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $previous = Join-Path $StagingDir "previous"
    New-Item -ItemType Directory -Force -Path $previous | Out-Null
    foreach ($check in $checks) {
        $stagedPath = Join-Path $StagingDir $check.name
        $targetPath = Join-Path $Target $check.name
        if (-not (Test-Path $stagedPath)) {
            continue
        }
        if ((File-Hash $targetPath) -eq $check.sha256) {
            continue
        }
        if (Test-Path $targetPath) {
            Move-Item -Force $targetPath (Join-Path $previous $check.name)
            Info "$($check.name): previous version kept in staging\previous"
        }
        Move-Item -Force $stagedPath $targetPath
        Info "$($check.name): deployed"
        $deployed++
    }

    if (-not $NoPrune) {
        $expected = @($checks | ForEach-Object { $_.name })
        Get-ChildItem $Target -Filter "check_*.exe" -File -ErrorAction SilentlyContinue |
            Where-Object { $expected -notcontains $_.Name } |
            ForEach-Object {
                Info "$($_.Name): removed (not part of release $tagName)"
                Remove-Item $_.FullName -Force
                $removed++
            }
    }
}

Info "summary: $downloaded downloaded, $deployed deployed, $skipped up to date, $removed removed"
if ($DryRun) {
    Info "dry run: nothing was changed"
}
