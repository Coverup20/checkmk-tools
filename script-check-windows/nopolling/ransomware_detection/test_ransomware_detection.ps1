#!/usr/bin/env powershell
<#
.SYNOPSIS
    Script di test per check_ransomware_activity.ps1
    
.DESCRIPTION
    Crea un ambiente di test simulato con file e scenari vari per verificare
    il corretto funzionamento del sistema di rilevamento ransomware.
    
    ATTENZIONE: Eseguire solo in ambiente di test!
    
.NOTES
    Author: Marzio
    Date: 2025-10-22
    Version: 1.0
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string]$TestSharePath = "$env:TEMP\RansomwareTest",
    
    [Parameter(Mandatory=$false)]
    [ValidateSet('All', 'Basic', 'Canary', 'MassEncryption', 'RansomNote', 'Cleanup')]
    [string]$TestScenario = 'All',
    
    [Parameter(Mandatory=$false)]
    [switch]$Cleanup
)

# Colori per output
$ColorOK = 'Green'
$ColorWarn = 'Yellow'
$ColorError = 'Red'
$ColorInfo = 'Cyan'

function Write-TestHeader {
    param([string]$Title)
    Write-Host "`n========================================" -ForegroundColor $ColorInfo
    Write-Host "  $Title" -ForegroundColor $ColorInfo
    Write-Host "========================================`n" -ForegroundColor $ColorInfo
}

function Write-TestResult {
    param(
        [string]$Test,
        [bool]$Passed,
        [string]$Message = ''
    )
    
    if ($Passed) {
        Write-Host "[✓] $Test" -ForegroundColor $ColorOK
    } else {
        Write-Host "[✗] $Test" -ForegroundColor $ColorError
    }
    
    if ($Message) {
        Write-Host "    $Message" -ForegroundColor $ColorWarn
    }
}

function New-TestEnvironment {
    Write-TestHeader "Creazione Ambiente di Test"
    
    # Crea directory principale
    if (-not (Test-Path $TestSharePath)) {
        New-Item -Path $TestSharePath -ItemType Directory -Force | Out-Null
        Write-TestResult "Directory test creata" $true $TestSharePath
    }
    
    # Crea sottodirectory
    $subDirs = @('Documents', 'Finance', 'Archive', 'Backup')
    foreach ($dir in $subDirs) {
        $path = Join-Path $TestSharePath $dir
        if (-not (Test-Path $path)) {
            New-Item -Path $path -ItemType Directory -Force | Out-Null
        }
    }
    Write-TestResult "Sottodirectory create" $true
    
    # Crea file normali
    $normalFiles = @(
        'Documents\report.docx',
        'Documents\presentation.pptx',
        'Documents\spreadsheet.xlsx',
        'Finance\invoice_2025.pdf',
        'Finance\budget.xlsx',
        'Archive\old_report.doc',
        'Backup\data.zip'
    )
    
    foreach ($file in $normalFiles) {
        $path = Join-Path $TestSharePath $file
        "This is a test file: $file`nCreated: $(Get-Date)" | Set-Content $path -Force
    }
    Write-TestResult "File normali creati" $true "$($normalFiles.Count) files"
    
    return $TestSharePath
}

function Test-BasicFunctionality {
    Write-TestHeader "Test 1: Funzionalità Base"
    
    # Verifica esistenza script
    $scriptPath = Join-Path $PSScriptRoot "check_ransomware_activity.ps1"
    $exists = Test-Path $scriptPath
    Write-TestResult "Script principale esiste" $exists $scriptPath
    
    if (-not $exists) {
        Write-Host "ERRORE: Script non trovato!" -ForegroundColor $ColorError
        return $false
    }
    
    # Test esecuzione base
    try {
        $output = & $scriptPath -SharePaths @($TestSharePath) -Debug 2>&1
        $success = $LASTEXITCODE -eq 0 -or $null -eq $LASTEXITCODE
        Write-TestResult "Esecuzione script" $success
        
        # Verifica output CheckMK
        $hasLocalHeader = $output -match '<<<local>>>'
        Write-TestResult "Output CheckMK format" $hasLocalHeader
        
        # Verifica servizi
        $hasMainService = $output -match 'Ransomware_Detection'
        Write-TestResult "Servizio principale presente" $hasMainService
        
        return $success -and $hasLocalHeader -and $hasMainService
    } catch {
        Write-TestResult "Esecuzione script" $false $_.Exception.Message
        return $false
    }
}

function Test-CanaryFiles {
    Write-TestHeader "Test 2: Canary Files"
    
    $scriptPath = Join-Path $PSScriptRoot "check_ransomware_activity.ps1"
    
    # Esegui script per creare canary files
    Write-Host "Creazione canary files..." -ForegroundColor $ColorInfo
    & $scriptPath -SharePaths @($TestSharePath) -Debug | Out-Null
    
    # Verifica creazione canary
    $canaryPath = Join-Path $TestSharePath ".ransomware_canary_do_not_delete.txt"
    $exists = Test-Path $canaryPath
    Write-TestResult "Canary file creato" $exists
    
    if ($exists) {
        # Verifica attributi
        $file = Get-Item $canaryPath -Force
        $isHidden = $file.Attributes -band [System.IO.FileAttributes]::Hidden
        $isReadOnly = $file.Attributes -band [System.IO.FileAttributes]::ReadOnly
        
        Write-TestResult "Attributo Hidden" ($isHidden -ne 0)
        Write-TestResult "Attributo ReadOnly" ($isReadOnly -ne 0)
        
        # Test modifica canary (simula ransomware)
        Write-Host "`nSimulazione modifica canary file..." -ForegroundColor $ColorWarn
        
        try {
            # Rimuovi ReadOnly temporaneamente
            $file.Attributes = $file.Attributes -band (-bnot [System.IO.FileAttributes]::ReadOnly)
            "MODIFIED BY TEST" | Add-Content $canaryPath
            $file.LastWriteTime = Get-Date
            
            # Esegui check
            Start-Sleep -Seconds 2
            $output = & $scriptPath -SharePaths @($TestSharePath) 2>&1
            
            # Verifica alert
            $hasAlert = $output -match 'Canary file'
            $isCritical = $output -match '^2 Ransomware_Detection'
            
            Write-TestResult "Alert canary modificato" $hasAlert
            Write-TestResult "Stato CRITICAL" $isCritical
            
            return $exists -and $hasAlert -and $isCritical
        } catch {
            Write-TestResult "Test modifica canary" $false $_.Exception.Message
            return $false
        }
    }
    
    return $exists
}

function Test-MassEncryption {
    Write-TestHeader "Test 3: Rilevamento Crittografia Massiva"
    
    $scriptPath = Join-Path $PSScriptRoot "check_ransomware_activity.ps1"
    
    # Crea molti file con estensioni ransomware
    Write-Host "Creazione file crittografati simulati..." -ForegroundColor $ColorInfo
    
    $encryptedDir = Join-Path $TestSharePath "Encrypted"
    New-Item -Path $encryptedDir -ItemType Directory -Force | Out-Null
    
    $ransomExtensions = @('.locked', '.encrypted', '.wannacry', '.ryuk', '.lockbit')
    $filesCreated = 0
    
    for ($i = 1; $i -le 60; $i++) {
        $ext = $ransomExtensions[($i % $ransomExtensions.Count)]
        $filename = "document_$i.pdf$ext"
        $path = Join-Path $encryptedDir $filename
        
        # Crea file con contenuto random (simula crittografia)
        $randomBytes = New-Object byte[] 1024
        (New-Object Random).NextBytes($randomBytes)
        [System.IO.File]::WriteAllBytes($path, $randomBytes)
        
        $filesCreated++
    }
    
    Write-Host "File crittografati creati: $filesCreated" -ForegroundColor $ColorWarn
    
    # Esegui check
    Start-Sleep -Seconds 2
    $output = & $scriptPath -SharePaths @($TestSharePath) -AlertThreshold 50 2>&1
    
    # Verifica detection
    $hasAlert = $output -match 'crittografia massiva'
    $hasSuspicious = $output -match 'suspicious_files='
    $isCritical = $output -match '^2 Ransomware_Detection'
    
    Write-TestResult "File sospetti rilevati" $hasSuspicious
    Write-TestResult "Alert crittografia massiva" $hasAlert
    Write-TestResult "Stato CRITICAL" $isCritical
    
    # Estrai numero file sospetti
    if ($output -match 'suspicious_files=(\d+)') {
        $count = [int]$matches[1]
        Write-Host "    File sospetti rilevati: $count" -ForegroundColor $ColorInfo
        Write-TestResult "Soglia superata (>50)" ($count -gt 50)
    }
    
    return $hasAlert -and $isCritical
}

function Test-RansomNote {
    Write-TestHeader "Test 4: Rilevamento Ransom Notes"
    
    $scriptPath = Join-Path $PSScriptRoot "check_ransomware_activity.ps1"
    
    # Crea ransom notes tipiche
    Write-Host "Creazione ransom notes simulate..." -ForegroundColor $ColorInfo
    
    $ransomNotes = @(
        @{
            Name = 'README_DECRYPT.txt'
            Content = @"
YOUR FILES HAVE BEEN ENCRYPTED!

All your important files have been encrypted with strong cryptography.
To decrypt your files you need to purchase the decryption key.

Price: 0.5 Bitcoin (BTC)
Payment address: bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh

After payment, contact us: ransomware@darkweb.onion
"@
        },
        @{
            Name = 'HOW_TO_RESTORE_FILES.html'
            Content = @"
<html>
<body>
<h1>Your data has been encrypted!</h1>
<p>Don't worry, you can restore all your files!</p>
<p>You need to pay for decryption in Bitcoin.</p>
<p>Price: 1 BTC</p>
</body>
</html>
"@
        },
        @{
            Name = 'DECRYPT_INSTRUCTION.hta'
            Content = @"
<HTA:APPLICATION>
<title>Decrypt Instructions</title>
<body>
All your files are encrypted. Pay ransom to decrypt.
Contact: payment@ransom.com
Bitcoin: bc1234567890
</body>
"@
        }
    )
    
    foreach ($note in $ransomNotes) {
        $path = Join-Path $TestSharePath $note.Name
        $note.Content | Set-Content $path -Force
    }
    
    Write-TestResult "Ransom notes create" $true "$($ransomNotes.Count) notes"
    
    # Esegui check
    Start-Sleep -Seconds 2
    $output = & $scriptPath -SharePaths @($TestSharePath) 2>&1
    
    # Verifica detection
    $hasAlert = $output -match 'Ransom notes rilevate'
    $hasMetric = $output -match 'ransom_notes=\d+'
    $isCritical = $output -match '^2 Ransomware_Detection'
    
    Write-TestResult "Ransom notes rilevate" $hasAlert
    Write-TestResult "Metriche presenti" $hasMetric
    Write-TestResult "Stato CRITICAL" $isCritical
    
    # Estrai numero ransom notes
    if ($output -match 'ransom_notes=(\d+)') {
        $count = [int]$matches[1]
        Write-Host "    Ransom notes rilevate: $count" -ForegroundColor $ColorInfo
    }
    
    return $hasAlert -and $isCritical
}

function Test-DoubleExtension {
    Write-TestHeader "Test 5: Doppia Estensione"
    
    $scriptPath = Join-Path $PSScriptRoot "check_ransomware_activity.ps1"
    
    # Crea file con doppia estensione
    Write-Host "Creazione file con doppia estensione..." -ForegroundColor $ColorInfo
    
    $doubleExtFiles = @(
        'important.docx.locked',
        'financial.xlsx.encrypted',
        'presentation.pptx.crypto',
        'photo.jpg.crypt',
        'database.sql.ryuk'
    )
    
    $testDir = Join-Path $TestSharePath "DoubleExt"
    New-Item -Path $testDir -ItemType Directory -Force | Out-Null
    
    foreach ($file in $doubleExtFiles) {
        $path = Join-Path $testDir $file
        "Encrypted content" | Set-Content $path -Force
    }
    
    Write-TestResult "File doppia estensione creati" $true "$($doubleExtFiles.Count) files"
    
    # Esegui check
    Start-Sleep -Seconds 2
    $output = & $scriptPath -SharePaths @($TestSharePath) -Debug 2>&1
    
    # Verifica detection
    $hasDoubleExt = $output -match 'Doppia estensione sospetta'
    $hasSuspicious = $output -match 'suspicious_files='
    
    Write-TestResult "Doppia estensione rilevata" $hasDoubleExt
    Write-TestResult "File sospetti presenti" $hasSuspicious
    
    return $hasDoubleExt
}

function Test-PerformanceMetrics {
    Write-TestHeader "Test 6: Performance e Metriche"
    
    $scriptPath = Join-Path $PSScriptRoot "check_ransomware_activity.ps1"
    
    # Misura tempo esecuzione
    Write-Host "Misurazione performance..." -ForegroundColor $ColorInfo
    
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $output = & $scriptPath -SharePaths @($TestSharePath) 2>&1
    $stopwatch.Stop()
    
    $executionTime = $stopwatch.Elapsed.TotalSeconds
    Write-Host "Tempo esecuzione: $([Math]::Round($executionTime, 2)) secondi" -ForegroundColor $ColorInfo
    
    # Verifica performance (< 30 secondi per test environment)
    $performanceOK = $executionTime -lt 30
    Write-TestResult "Performance accettabile (<30s)" $performanceOK
    
    # Verifica metriche complete
    $metrics = @(
        'suspicious_files=',
        'ransom_notes=',
        'canary_alerts=',
        'shares_ok='
    )
    
    $allMetricsPresent = $true
    foreach ($metric in $metrics) {
        $present = $output -match [regex]::Escape($metric)
        if (-not $present) {
            $allMetricsPresent = $false
        }
        Write-TestResult "Metrica: $metric" $present
    }
    
    return $performanceOK -and $allMetricsPresent
}

function Remove-TestEnvironment {
    Write-TestHeader "Pulizia Ambiente di Test"
    
    if (Test-Path $TestSharePath) {
        try {
            # Rimuovi attributi readonly/hidden dai file
            Get-ChildItem $TestSharePath -Recurse -Force -File | ForEach-Object {
                $_.Attributes = 'Normal'
            }
            
            Remove-Item $TestSharePath -Recurse -Force
            Write-TestResult "Directory test rimossa" $true
            
            # Rimuovi state file
            $stateFile = "$env:TEMP\ransomware_state.json"
            if (Test-Path $stateFile) {
                Remove-Item $stateFile -Force
                Write-TestResult "State file rimosso" $true
            }
            
            return $true
        } catch {
            Write-TestResult "Pulizia" $false $_.Exception.Message
            return $false
        }
    } else {
        Write-Host "Nessun ambiente di test da rimuovere" -ForegroundColor $ColorWarn
        return $true
    }
}

function Show-TestSummary {
    param([hashtable]$Results)
    
    Write-TestHeader "Riepilogo Test"
    
    $total = $Results.Count
    $passed = ($Results.Values | Where-Object { $_ -eq $true }).Count
    $failed = $total - $passed
    
    Write-Host "Totale test: $total" -ForegroundColor $ColorInfo
    Write-Host "Passati:     $passed" -ForegroundColor $ColorOK
    Write-Host "Falliti:     $failed" -ForegroundColor $(if ($failed -eq 0) { $ColorOK } else { $ColorError })
    
    Write-Host "`nDettaglio:" -ForegroundColor $ColorInfo
    foreach ($test in $Results.Keys) {
        $status = if ($Results[$test]) { "✓ PASS" } else { "✗ FAIL" }
        $color = if ($Results[$test]) { $ColorOK } else { $ColorError }
        Write-Host "  $status - $test" -ForegroundColor $color
    }
    
    $successRate = [Math]::Round(($passed / $total) * 100, 1)
    Write-Host "`nTasso successo: $successRate%" -ForegroundColor $(
        if ($successRate -eq 100) { $ColorOK }
        elseif ($successRate -ge 80) { $ColorWarn }
        else { $ColorError }
    )
}

# ============================================================================
# MAIN
# ============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║     Test Suite - Ransomware Detection for CheckMK        ║
║                   Version 1.0                             ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor $ColorInfo

# Cleanup immediato se richiesto
if ($Cleanup) {
    Remove-TestEnvironment
    exit 0
}

# Risultati test
$testResults = @{}

# Setup ambiente
$testPath = New-TestEnvironment

# Esegui test in base allo scenario
switch ($TestScenario) {
    'All' {
        $testResults['Basic Functionality'] = Test-BasicFunctionality
        $testResults['Canary Files'] = Test-CanaryFiles
        $testResults['Mass Encryption'] = Test-MassEncryption
        $testResults['Ransom Notes'] = Test-RansomNote
        $testResults['Double Extension'] = Test-DoubleExtension
        $testResults['Performance'] = Test-PerformanceMetrics
    }
    'Basic' {
        $testResults['Basic Functionality'] = Test-BasicFunctionality
    }
    'Canary' {
        $testResults['Canary Files'] = Test-CanaryFiles
    }
    'MassEncryption' {
        $testResults['Mass Encryption'] = Test-MassEncryption
    }
    'RansomNote' {
        $testResults['Ransom Notes'] = Test-RansomNote
    }
    'Cleanup' {
        Remove-TestEnvironment
        exit 0
    }
}

# Mostra riepilogo
Show-TestSummary -Results $testResults

# Chiedi se rimuovere ambiente di test
Write-Host "`n"
$response = Read-Host "Rimuovere ambiente di test? (y/N)"
if ($response -eq 'y' -or $response -eq 'Y') {
    Remove-TestEnvironment
} else {
    Write-Host "Ambiente di test mantenuto in: $TestSharePath" -ForegroundColor $ColorInfo
    Write-Host "Per rimuoverlo manualmente: Remove-Item '$TestSharePath' -Recurse -Force" -ForegroundColor $ColorWarn
}

Write-Host "`nTest completati!`n" -ForegroundColor $ColorOK
