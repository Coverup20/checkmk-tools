<#
.SYNOPSIS
    Remote wrapper per check_ransomware_activity.ps1 - Scarica ed esegue da GitHub
.DESCRIPTION
    Questo script scarica l'ultima versione di check_ransomware_activity.ps1 da GitHub
    e lo esegue localmente. Utile per avere sempre l'ultima versione senza deployment manuale.
.NOTES
    Author: CheckMK Tools
    Version: 1.0
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

# Configurazione
$scriptUrl = "https://raw.githubusercontent.com/$GitHubRepo/$Branch/script-check-windows/nopolling/ransomware_detection/check_ransomware_activity.ps1"
$tempScript = "$env:TEMP\check_ransomware_activity_remote_$(Get-Date -Format 'yyyyMMddHHmmss').ps1"
$cacheFile = "$env:TEMP\ransomware_script_cache.ps1"
$cacheTimeout = 3600 # 1 ora in secondi

function Write-DebugLog {
    param([string]$Message)
    if ($VerboseLog) {
        Write-Host "[DEBUG] $Message" -ForegroundColor Cyan
    }
}

function Get-CachedScript {
    <#
    .SYNOPSIS
        Recupera lo script dalla cache se è ancora valido
    #>
    if (Test-Path $cacheFile) {
        $cacheAge = (Get-Date) - (Get-Item $cacheFile).LastWriteTime
        if ($cacheAge.TotalSeconds -lt $cacheTimeout) {
            Write-DebugLog "Uso script dalla cache (età: $([int]$cacheAge.TotalMinutes) minuti)"
            return $cacheFile
        } else {
            Write-DebugLog "Cache scaduta (età: $([int]$cacheAge.TotalMinutes) minuti)"
        }
    }
    return $null
}

function Download-Script {
    <#
    .SYNOPSIS
        Scarica lo script da GitHub
    #>
    try {
        Write-DebugLog "Download script da: $scriptUrl"
        
        # Prova con cache bypass
        $urlWithCache = $scriptUrl + "?t=" + (Get-Date).Ticks
        
        $webClient = New-Object System.Net.WebClient
        $webClient.Headers.Add("Cache-Control", "no-cache")
        $webClient.Headers.Add("Pragma", "no-cache")
        $webClient.DownloadFile($urlWithCache, $tempScript)
        
        # Verifica che il download sia riuscito
        if ((Test-Path $tempScript) -and ((Get-Item $tempScript).Length -gt 1000)) {
            Write-DebugLog "Script scaricato: $((Get-Item $tempScript).Length) bytes"
            
            # Aggiorna la cache
            Copy-Item $tempScript $cacheFile -Force
            
            return $tempScript
        } else {
            throw "File scaricato non valido o troppo piccolo"
        }
        
    } catch {
        Write-DebugLog "Errore nel download: $_"
        return $null
    }
}

function Invoke-RemoteScript {
    <#
    .SYNOPSIS
        Esegue lo script scaricato o dalla cache
    #>
    
    # Prova prima dalla cache
    $scriptPath = Get-CachedScript
    
    # Se non c'è cache valida, scarica
    if (-not $scriptPath) {
        $scriptPath = Download-Script
    }
    
    # Se il download fallisce, usa la cache comunque (se esiste)
    if (-not $scriptPath -and (Test-Path $cacheFile)) {
        Write-DebugLog "Download fallito, uso cache obsoleta come fallback"
        $scriptPath = $cacheFile
    }
    
    # Se ancora non abbiamo lo script, errore
    if (-not $scriptPath -or -not (Test-Path $scriptPath)) {
        Write-Host "<<<local>>>"
        Write-Host "3 Ransomware_Detection UNKNOWN - Impossibile scaricare lo script da GitHub. Verificare connettività Internet."
        exit 3
    }
    
    # Esegue lo script
    try {
        Write-DebugLog "Esecuzione script: $scriptPath"
        
        # Costruisci i parametri da passare
        $params = @{
            ConfigFile = $ConfigFile
            TimeWindowMinutes = $TimeWindowMinutes
            AlertThreshold = $AlertThreshold
        }
        
        if ($VerboseLog) {
            $params.VerboseLog = $true
        }
        
        # Esegui lo script
        & $scriptPath @params
        
        # Pulizia file temporaneo (non la cache)
        if ($scriptPath -eq $tempScript -and (Test-Path $tempScript)) {
            Remove-Item $tempScript -Force -ErrorAction SilentlyContinue
        }
        
    } catch {
        Write-Host "<<<local>>>"
        Write-Host "3 Ransomware_Detection UNKNOWN - Errore nell'esecuzione dello script: $_"
        exit 3
    }
}

# Main execution
try {
    Write-DebugLog "=== Remote Ransomware Check - Start ==="
    Write-DebugLog "Repository: $GitHubRepo/$Branch"
    Write-DebugLog "Config: $ConfigFile"
    
    Invoke-RemoteScript
    
    Write-DebugLog "=== Remote Ransomware Check - End ==="
    
} catch {
    Write-Host "<<<local>>>"
    Write-Host "3 Ransomware_Detection UNKNOWN - Errore critico: $_"
    exit 3
}
