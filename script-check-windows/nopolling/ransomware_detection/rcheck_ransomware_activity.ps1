<#
.SYNOPSIS
    Remote wrapper per check_ransomware_activity.ps1 - Scarica ed esegue da GitHub
.DESCRIPTION
    Wrapper semplice che scarica ed esegue direttamente da GitHub (come gli script Linux).
    Nessuna cache - sempre l'ultima versione.
.NOTES
    Author: CheckMK Tools
    Version: 2.0 - Semplificato
    Richiede: PowerShell 5.1+, accesso Internet
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$ConfigFile = "$PSScriptRoot\ransomware_config.json",
    
    [Parameter(Mandatory=$false)]
    [int]$TimeWindowMinutes = 30,
    
    [Parameter(Mandatory=$false)]
    [int]$AlertThreshold = 50,
    
    [Parameter(Mandatory=$false)]
    [switch]$VerboseLog,
    
    [Parameter(Mandatory=$false)]
    [string]$GitHubRepo = "Coverup20/checkmk-tools",
    
    [Parameter(Mandatory=$false)]
    [string]$Branch = "main"
)

# URL script principale su GitHub
$scriptUrl = "https://raw.githubusercontent.com/$GitHubRepo/$Branch/script-check-windows/nopolling/ransomware_detection/check_ransomware_activity.ps1"

# Scarica ed esegui direttamente (come gli script Linux)
try {
    # Download con cache bypass
    $urlWithTimestamp = $scriptUrl + "?t=" + (Get-Date).Ticks
    $tempScript = "$env:TEMP\check_ransomware_activity_$(Get-Date -Format 'yyyyMMddHHmmss').ps1"
    
    # Scarica
    (New-Object System.Net.WebClient).DownloadFile($urlWithTimestamp, $tempScript)
    
    # Verifica download
    if (-not (Test-Path $tempScript) -or (Get-Item $tempScript).Length -lt 1000) {
        throw "Download fallito o file troppo piccolo"
    }
    
    # Costruisci parametri
    $params = @{
        ConfigFile = $ConfigFile
        TimeWindowMinutes = $TimeWindowMinutes
        AlertThreshold = $AlertThreshold
    }
    
    if ($VerboseLog) {
        $params.VerboseLog = $true
    }
    
    # Esegui
    & $tempScript @params
    
    # Cleanup
    Remove-Item $tempScript -Force -ErrorAction SilentlyContinue
    
} catch {
    Write-Host "<<<local>>>"
    Write-Host "3 Ransomware_Detection UNKNOWN - Errore: $_"
    exit 3
}
