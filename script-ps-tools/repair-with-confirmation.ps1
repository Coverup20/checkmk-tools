#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Riparazione script corrotti con conferma utente
.DESCRIPTION
    1. Crea backup temporaneo
    2. Ripara i file nella copia temporanea
    3. Mostra report dettagliato
    4. Attende conferma utente
    5. Sostituisce originali con riparati
#>

param(
    [switch]$SkipBackup
)

$ErrorActionPreference = "Stop"
$WORKSPACE = $PSScriptRoot
$TEMP_DIR = Join-Path $WORKSPACE "REPAIR_TEMP_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss')"
$REPORT_FILE = Join-Path $TEMP_DIR "repair-report.txt"

# Verifica WSL
try {
    $null = wsl --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "WSL non disponibile"
    }
} catch {
    Write-Host "[ERROR] WSL non disponibile - necessario per validazione bash" -ForegroundColor Red
    exit 1
}

Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "    RIPARAZIONE SCRIPT CORROTTI CON CONFERMA" -ForegroundColor Cyan
Write-Host "================================================================`n" -ForegroundColor Cyan

# FASE 1: Trova file corrotti
Write-Host "[FASE 1] Ricerca file corrotti..." -ForegroundColor Yellow

$corruptedFiles = @()
$scriptExtensions = @(".sh", ".bash", ".ps1")
$excludeDirs = @("node_modules", ".git", "REPAIR_TEMP_*", "*.BACKUP_*")

Get-ChildItem -Path $WORKSPACE -Recurse -File | Where-Object {
    $_.Extension -in $scriptExtensions -and
    $excludeDirs | ForEach-Object { $file = $_.FullName; $file -notlike "*$_*" } | Where-Object { $_ }
} | ForEach-Object {
    $file = $_
    $isCorrupted = $false
    $errorMsg = ""
    
    # Check bash
    if ($file.Extension -in @(".sh", ".bash")) {
        $wslPath = $file.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $isCorrupted = $true
            $errorMsg = ($bashCheck -join " ").Substring(0, [Math]::Min(200, ($bashCheck -join " ").Length))
        }
    }
    
    # Check PowerShell
    if ($file.Extension -eq ".ps1" -and -not $isCorrupted) {
        $tokens = $null
        $errors = $null
        $null = [System.Management.Automation.Language.Parser]::ParseFile(
            $file.FullName, [ref]$tokens, [ref]$errors
        )
        if ($errors.Count -gt 0) {
            $isCorrupted = $true
            $errorMsg = ($errors[0].Message).Substring(0, [Math]::Min(200, $errors[0].Message.Length))
        }
    }
    
    if ($isCorrupted) {
        $relativePath = $file.FullName.Replace("$WORKSPACE\", "")
        $corruptedFiles += [PSCustomObject]@{
            FullPath = $file.FullName
            RelativePath = $relativePath
            Name = $file.Name
            Error = $errorMsg
        }
    }
}

Write-Host "Trovati $($corruptedFiles.Count) file corrotti`n" -ForegroundColor Yellow

if ($corruptedFiles.Count -eq 0) {
    Write-Host "[SUCCESSO] Nessun file corrotto trovato!" -ForegroundColor Green
    exit 0
}

# Filtra solo Ydea-Toolkit/full e script-tools/full
$targetFiles = $corruptedFiles | Where-Object { 
    $_.RelativePath -like "Ydea-Toolkit\full\*" -or 
    $_.RelativePath -like "script-tools\full\*" 
}

if ($targetFiles.Count -eq 0) {
    Write-Host "[INFO] Nessun file da riparare in Ydea-Toolkit/full o script-tools/full" -ForegroundColor Cyan
    Write-Host "[INFO] File corrotti rimanenti: $($corruptedFiles.Count)" -ForegroundColor Cyan
    $corruptedFiles | Format-Table RelativePath, @{L='Error';E={$_.Error.Substring(0,[Math]::Min(80,$_.Error.Length))}}
    exit 0
}

Write-Host "[INFO] File selezionati per riparazione: $($targetFiles.Count)" -ForegroundColor Cyan
$targetFiles | Format-Table RelativePath

# FASE 2: Crea backup temporaneo
Write-Host "`n[FASE 2] Creazione backup temporaneo..." -ForegroundColor Yellow

New-Item -ItemType Directory -Path $TEMP_DIR -Force | Out-Null
$backupDir = Join-Path $TEMP_DIR "backup"
$workingDir = Join-Path $TEMP_DIR "working"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
New-Item -ItemType Directory -Path $workingDir -Force | Out-Null

$targetFiles | ForEach-Object {
    $file = $_
    $destBackup = Join-Path $backupDir $file.RelativePath
    $destWorking = Join-Path $workingDir $file.RelativePath
    
    # Crea directory
    $null = New-Item -ItemType Directory -Path (Split-Path $destBackup) -Force
    $null = New-Item -ItemType Directory -Path (Split-Path $destWorking) -Force
    
    # Copia file
    Copy-Item $file.FullPath -Destination $destBackup -Force
    Copy-Item $file.FullPath -Destination $destWorking -Force
}

Write-Host "Backup creato in: $backupDir" -ForegroundColor Green
Write-Host "Directory lavoro: $workingDir`n" -ForegroundColor Green

# FASE 3: Analizza e ripara
Write-Host "[FASE 3] Analisi e riparazione in corso..." -ForegroundColor Yellow

$repairLog = @()
$repairedCount = 0
$failedCount = 0

foreach ($file in $targetFiles) {
    $workingFile = Join-Path $workingDir $file.RelativePath
    Write-Host "`nAnalisi: $($file.Name)" -ForegroundColor Cyan
    
    $content = Get-Content $workingFile -Raw
    $fixed = $false
    $changes = @()
    
    # Problema comune: righe concatenate senza newline
    if ($content -match '[a-z]\)[a-zA-Z]') {

        # Fix: aggiungi newline dopo parentesi chiuse
        $content = $content -replace '(\))([\$a-zA-Z_])', "`$1`n`$2"
        $changes += "- Aggiunte newline dopo parentesi chiuse"
        $fixed = $true
    }
    
    # Problema: righe concatenate con 'fi' o 'done'
    if ($content -match '([a-z]+)(fi|done|then|else)([a-zA-Z])') {
        $content = $content -replace '([a-z]+)(fi)([a-zA-Z])', "`$1`n`$2`n`$3"
        $content = $content -replace '([a-z]+)(done)([a-zA-Z])', "`$1`n`$2`n`$3"
        $content = $content -replace '([a-z]+)(then)([a-zA-Z])', "`$1`n`$2`n`$3"
        $content = $content -replace '([a-z]+)(else)([a-zA-Z])', "`$1`n`$2`n`$3"
        $changes += "- Separate keyword bash (fi, done, then, else)"
        $fixed = $true
    }
    
    # Problema: caratteri corrotti tipo ┬¡ãÆ
    if ($content -match '[┬¡ãÆ├┤│─└┘┌┐]') {
        $content = $content -replace '[┬¡ãÆ├┤│─└┘┌┐]+', ''
        $changes += "- Rimossi caratteri corrotti Unicode"
        $fixed = $true
    }
    
    if ($fixed) {
        Set-Content -Path $workingFile -Value $content -NoNewline -Encoding UTF8
        
        # Verifica se riparato
        $wslPath = $workingFile -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   RIPARATO CON SUCCESSO" -ForegroundColor Green
            $repairedCount++
            $repairLog += [PSCustomObject]@{
                File = $file.RelativePath
                Status = " Riparato"
                Changes = ($changes -join "; ")
            }
        } else {
            Write-Host "    Riparazione parziale (ancora errori)" -ForegroundColor Yellow
            $failedCount++
            $repairLog += [PSCustomObject]@{
                File = $file.RelativePath
                Status = " Parziale"
                Changes = ($changes -join "; ")
            }
        }
    } else {
        Write-Host "   Nessuna riparazione automatica disponibile" -ForegroundColor Red
        $failedCount++
        $repairLog += [PSCustomObject]@{
            File = $file.RelativePath
            Status = " Fallito"
            Changes = "Nessuna riparazione trovata"
        }
    }
}

# FASE 4: Report
Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "    REPORT RIPARAZIONE" -ForegroundColor Cyan
Write-Host "================================================================`n" -ForegroundColor Cyan

$report = @"
RIEPILOGO:
  File analizzati:         $($targetFiles.Count)
  File riparati:           $repairedCount
  Riparazioni parziali:    $failedCount
  Data: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')

DETTAGLIO RIPARAZIONI:

"@

$repairLog | ForEach-Object {
    $report += "`n$($_.Status) $($_.File)`n"
    $report += "   $($_.Changes)`n"
}

$report += "`n`nLOCAZIONI:`n"
$report += "  Backup originali: $backupDir`n"
$report += "  File riparati:    $workingDir`n"

Write-Host $report
$report | Out-File -FilePath $REPORT_FILE -Encoding UTF8

Write-Host "`nReport salvato in: $REPORT_FILE`n" -ForegroundColor Green

# FASE 5: Conferma utente
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "Vuoi sostituire i file originali con quelli riparati?" -ForegroundColor Yellow
Write-Host "  - Backup in: $backupDir" -ForegroundColor Gray
Write-Host "  - File riparati: $repairedCount su $($targetFiles.Count)" -ForegroundColor Gray
Write-Host "================================================================`n" -ForegroundColor Yellow

$response = Read-Host "Procedere con la sostituzione? (si/no)"

if ($response -ne "si") {
    Write-Host "`n[ANNULLATO] Nessun file modificato." -ForegroundColor Yellow
    Write-Host "I file riparati sono disponibili in: $workingDir" -ForegroundColor Cyan
    exit 0
}

# FASE 6: Sostituzione
Write-Host "`n[FASE 6] Sostituzione file..." -ForegroundColor Yellow

$successCount = 0
$errorCount = 0

foreach ($file in $targetFiles) {
    $workingFile = Join-Path $workingDir $file.RelativePath
    
    # Verifica se è stato riparato
    $logEntry = $repairLog | Where-Object { $_.File -eq $file.RelativePath -and $_.Status -eq " Riparato" }
    
    if ($logEntry) {
        try {
            Copy-Item $workingFile -Destination $file.FullPath -Force
            Write-Host "   $($file.Name)" -ForegroundColor Green
            $successCount++
        } catch {
            Write-Host "   $($file.Name): $($_.Exception.Message)" -ForegroundColor Red
            $errorCount++
        }
    }
}

Write-Host "`n================================================================" -ForegroundColor Cyan
Write-Host "    COMPLETATO" -ForegroundColor Cyan
Write-Host "================================================================`n" -ForegroundColor Cyan

Write-Host "File sostituiti con successo: $successCount" -ForegroundColor Green
Write-Host "Errori durante sostituzione:  $errorCount" -ForegroundColor $(if($errorCount -gt 0){"Red"}else{"Green"})
Write-Host "`nBackup permanente in: $backupDir" -ForegroundColor Cyan
Write-Host "Report completo in: $REPORT_FILE`n" -ForegroundColor Cyan

if ($successCount -gt 0) {
    Write-Host "[CONSIGLIO] Esegui '.\check-integrity.ps1' per verificare lo stato finale`n" -ForegroundColor Yellow
}
