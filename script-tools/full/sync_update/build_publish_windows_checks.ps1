<#
.SYNOPSIS
  Builds the Windows local checks and publishes them as a GitHub release.

.DESCRIPTION
  For every check_*.py in <RepoDir>\full this script builds a self-contained
  Windows executable with PyInstaller in onefile mode, computes its sha256 and
  writes a manifest.json. With -Publish it creates or updates the GitHub
  release that carries the executables and the manifest; the downloader on the
  client reads that release instead of a local repository copy.

.PARAMETER RepoDir
  Category directory that holds the sources in full\, default the
  script-check-windows directory at the root of the checkout that contains
  this script. No mount or fixed path is assumed.

.PARAMETER OutDir
  Directory that receives the executables and the manifest, default a
  per-tag folder under the temporary directory.

.PARAMETER Tag
  Release tag, default winchecks-YYYY.MM.DD.

.PARAMETER Repo
  GitHub repository, default Coverup20/checkmk-tools.

.PARAMETER Publish
  Create or update the GitHub release with the assets.

.PARAMETER Draft
  Create the release as a draft (useful to test the flow without publishing).

.PARAMETER Clean
  Let PyInstaller clear its caches before building.

.REQUIREMENTS
  Windows 64-bit, PowerShell 5.1+, Python 3 with pyinstaller, GitHub CLI
  authenticated for -Publish. Only the publisher needs an account: clients
  download the release assets anonymously over HTTPS.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\build_publish_windows_checks.ps1
  powershell -ExecutionPolicy Bypass -File .\build_publish_windows_checks.ps1 -Publish
  powershell -ExecutionPolicy Bypass -File .\build_publish_windows_checks.ps1 -Publish -Draft -Tag winchecks-test
#>

[CmdletBinding()]
param(
    [string]$RepoDir = "",
    [string]$OutDir = "",
    [string]$Tag = "",
    [string]$Repo = "Coverup20/checkmk-tools",
    [switch]$Publish,
    [switch]$Draft,
    [switch]$Clean
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Continue"

function Info($Message) {
    Write-Host "[INFO] $Message"
}

function Fail($Message) {
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

if (-not $RepoDir) {
    $repoRoot = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
    $RepoDir = Join-Path $repoRoot "script-check-windows"
}

$fullDir = Join-Path $RepoDir "full"
if (-not (Test-Path $fullDir)) {
    Fail "source directory not found: $fullDir"
}
$sources = @(Get-ChildItem $fullDir -Filter "check_*.py" -File | Sort-Object Name)
if ($sources.Count -eq 0) {
    Fail "no check_*.py in $fullDir"
}

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Fail "python.exe not found in PATH"
}
& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "PyInstaller is missing: $python -m pip install --user pyinstaller"
}

if (-not $Tag) {
    $Tag = "winchecks-" + (Get-Date -Format "yyyy.MM.dd")
}
if (-not $OutDir) {
    $OutDir = Join-Path $env:TEMP (Join-Path "winchecks-build" $Tag)
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$entries = @()
foreach ($src in $sources) {
    $name = [IO.Path]::GetFileNameWithoutExtension($src.Name)
    Info "building $name"
    $work = Join-Path $OutDir (Join-Path "build" $name)
    $pyArgs = @("-m", "PyInstaller")
    if ($Clean) {
        $pyArgs += "--clean"
    }
    $pyArgs += @(
        "--noconfirm", "--onefile", "--name", $name,
        "--distpath", $OutDir,
        "--workpath", $work,
        "--specpath", $work,
        $src.FullName
    )
    & $python @pyArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "PyInstaller failed for $name"
    }
    $exe = Join-Path $OutDir "$name.exe"
    if (-not (Test-Path $exe)) {
        Fail "executable not produced: $exe"
    }
    $entries += [pscustomobject]@{
        name   = "$name.exe"
        sha256 = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
        size   = (Get-Item $exe).Length
    }
}

$manifest = [ordered]@{
    tag        = $Tag
    version    = (Get-Date -Format "yyyy.MM.dd")
    built_at   = (Get-Date).ToString("o")
    generator  = "build_publish_windows_checks.ps1 $ScriptVersion"
    checks     = $entries
}
$manifestPath = Join-Path $OutDir "manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Path $manifestPath -Encoding ASCII

$entries | Format-Table name, size, sha256 -AutoSize | Out-String | Write-Host
Info "manifest: $manifestPath"

if (-not $Publish) {
    Info "build only: pass -Publish to create or update the release $Tag"
    exit 0
}

$gh = (Get-Command gh.exe -ErrorAction SilentlyContinue).Source
if (-not $gh) {
    Fail "GitHub CLI not found: install it and run gh auth login"
}
& $gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    Fail "GitHub CLI not authenticated: run gh auth login"
}

$assets = @($entries | ForEach-Object { Join-Path $OutDir $_.name })
$assets += $manifestPath

& $gh release view $Tag --repo $Repo *> $null
if ($LASTEXITCODE -eq 0) {
    Info "release $Tag exists, uploading assets"
    & $gh release upload $Tag @assets --repo $Repo --clobber
    if ($LASTEXITCODE -ne 0) {
        Fail "gh release upload failed"
    }
} else {
    $notes = "Windows local checks $Tag`n`n" + (($entries | ForEach-Object {
        "- $($_.name) sha256 $($_.sha256)"
    }) -join "`n")
    $createArgs = @($Tag) + $assets + @("--repo", $Repo,
        "--title", "Windows local checks $Tag", "--notes", $notes)
    if ($Draft) {
        $createArgs += "--draft"
    }
    & $gh release create @createArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "gh release create failed"
    }
}

Info "published release $Tag on $Repo"
