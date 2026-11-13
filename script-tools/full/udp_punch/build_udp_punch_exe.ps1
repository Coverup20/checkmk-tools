<#
.SYNOPSIS
  Builds the Windows executable of the UDP punch tunnel peer.

.DESCRIPTION
  Runs PyInstaller in onedir mode on punch_peer.py; protocol.py is found next
  to it. The result is a self-contained folder with cmk-punch.exe and its
  _internal directory, so the target machine needs no Python installation.

  With -CertificateThumbprint the executable is signed with signtool using a
  SHA-256, timestamped Authenticode signature. Without it the build is not
  signed and antivirus products still decide on behaviour: keep an exclusion
  for the install directory.

.PARAMETER OutputDir
  Directory that receives the built folder, default dist.

.PARAMETER CertificateThumbprint
  Thumbprint of a code-signing certificate in the current user store.

.PARAMETER TimestampUrl
  RFC 3161 timestamp server used when signing.

.PARAMETER Clean
  Let PyInstaller clear its caches before building.

.REQUIREMENTS
  Windows 64-bit, PowerShell 5.1+, Python 3 with cryptography and pyinstaller.

.USAGE
  powershell -ExecutionPolicy Bypass -File .\build_udp_punch_exe.ps1
  powershell -ExecutionPolicy Bypass -File .\build_udp_punch_exe.ps1 -Clean
  powershell -ExecutionPolicy Bypass -File .\build_udp_punch_exe.ps1 -CertificateThumbprint <thumbprint>
#>

[CmdletBinding()]
param(
    [string]$OutputDir = "dist",
    [string]$CertificateThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$Clean
)

$ScriptVersion = "1.0.0"
$ErrorActionPreference = "Stop"

function Info($Message) {
    Write-Host "[INFO] $Message"
}

$here = $PSScriptRoot
foreach ($name in @("punch_peer.py", "protocol.py")) {
    if (-not (Test-Path (Join-Path $here $name))) {
        throw "$name not found next to this script"
    }
}

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "python.exe not found in PATH"
}
& $python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing: $python -m pip install --user pyinstaller"
}

$work = Join-Path $here "build"
$pyArgs = @("-m", "PyInstaller")
if ($Clean) {
    $pyArgs += "--clean"
}
$pyArgs += @(
    "--noconfirm",
    "--onedir",
    "--name", "cmk-punch",
    "--distpath", (Join-Path $here $OutputDir),
    "--workpath", $work,
    "--specpath", $work,
    "--paths", $here,
    (Join-Path $here "punch_peer.py")
)

Info "building with $python"
& $python @pyArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed"
}

$exe = Join-Path $here (Join-Path $OutputDir "cmk-punch\cmk-punch.exe")
if (-not (Test-Path $exe)) {
    throw "expected executable not found: $exe"
}

if ($CertificateThumbprint) {
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) {
        throw "signtool.exe not found: install the Windows SDK or add it to PATH"
    }
    Info "signing with certificate $CertificateThumbprint"
    & $signtool.Source sign /sha1 $CertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $exe
    if ($LASTEXITCODE -ne 0) {
        throw "signtool failed"
    }
}

$size = [math]::Round((Get-ChildItem (Split-Path $exe -Parent) -Recurse -File |
    Measure-Object Length -Sum).Sum / 1MB, 1)
Info "built $exe"
Info "folder size: $size MB"
if (-not $CertificateThumbprint) {
    Info "not signed: add the install directory to the antivirus exclusions"
}
