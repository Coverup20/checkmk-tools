# Script di Riparazione Script Corrotti
# Ripara gli script corrotti in install/checkmk-installer/ usando le versioni corrette

param(
    [switch]$DryRun,        # Simula senza modificare
    [switch]$AutoConfirm    # Salta conferma (usa con cautela)
)

$ErrorActionPreference = "Continue"

$REPO_PATH = "C:\Users\Marzio\Desktop\CheckMK\checkmk-tools"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "      RIPARAZIONE SCRIPT CORROTTI" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 1: RICERCA SCRIPT CORROTTI
# ═══════════════════════════════════════════════════════════════

Write-Host "[FASE 1] Ricerca script corrotti..." -ForegroundColor Cyan
Write-Host ""

# Esegui check integrità solo su install/checkmk-installer/
$corruptedScripts = @()
$wslAvailable = $false

# Verifica WSL
try {
    $null = wsl --version 2>&1
    $wslAvailable = $LASTEXITCODE -eq 0
} catch {
    $wslAvailable = $false
}

if (-not $wslAvailable) {
    Write-Host "[WARNING] WSL non disponibile - riparazione limitata" -ForegroundColor Yellow
    Write-Host ""
}

# Scansiona install/checkmk-installer/
$installerScripts = Get-ChildItem -Path "$REPO_PATH\install\checkmk-installer" -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { 
        $_.Extension -in @('.sh', '.bash') -and
        $_.FullName -notmatch '\\iso-output\\|\\\.git\\'
    }

Write-Host "Trovati $($installerScripts.Count) script bash in install/checkmk-installer/" -ForegroundColor Gray
Write-Host "Verifica integrità in corso..." -ForegroundColor Gray
Write-Host ""

foreach ($script in $installerScripts) {
    $relativePath = $script.FullName.Replace("$REPO_PATH\", "")
    
    # Verifica con WSL bash -n
    if ($wslAvailable) {
        $wslPath = $script.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            $errorMsg = if ($bashCheck) { ($bashCheck | Select-Object -First 1) -join "" } else { "Syntax error" }
            $corruptedScripts += [PSCustomObject]@{
                CorruptedPath = $relativePath
                FullPath = $script.FullName
                FileName = $script.Name
                Error = $errorMsg
                SourcePath = $null
                SourceExists = $false
            }
        }
    }
}

Write-Host "Script corrotti trovati: $($corruptedScripts.Count)" -ForegroundColor $(if ($corruptedScripts.Count -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

if ($corruptedScripts.Count -eq 0) {
    Write-Host " Nessuno script corrotto trovato!" -ForegroundColor Green
    Write-Host ""
    exit 0
}

# ═══════════════════════════════════════════════════════════════
# FASE 2: RICERCA VERSIONI CORRETTE
# ═══════════════════════════════════════════════════════════════

Write-Host "[FASE 2] Ricerca versioni corrette..." -ForegroundColor Cyan
Write-Host ""

$repairable = @()
$notFound = @()

foreach ($corrupt in $corruptedScripts) {
    $fileName = $corrupt.FileName
    
    # Pattern di ricerca:
    # 1. script-check-ns7/full/
    # 2. script-check-ns8/full/
    # 3. script-check-proxmox/full/
    # 4. script-tools/full/
    # 5. Ydea-Toolkit/full/
    
    $searchPaths = @(
        "script-check-ns7\full\$fileName",
        "script-check-ns8\full\$fileName",
        "script-check-nsec8\full\$fileName",
        "script-check-proxmox\full\$fileName",
        "script-check-ubuntu\full\$fileName",
        "script-tools\full\$fileName",
        "Ydea-Toolkit\full\$fileName"
    )
    
    $found = $false
    foreach ($searchPath in $searchPaths) {
        $fullSearchPath = Join-Path $REPO_PATH $searchPath
        if (Test-Path $fullSearchPath) {
            $corrupt.SourcePath = $searchPath
            $corrupt.SourceExists = $true
            $repairable += $corrupt
            $found = $true
            break
        }
    }
    
    if (-not $found) {
        $notFound += $corrupt
    }
}

Write-Host "Script riparabili: $($repairable.Count)" -ForegroundColor Green
Write-Host "Script non trovati: $($notFound.Count)" -ForegroundColor $(if ($notFound.Count -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 3: RIEPILOGO DETTAGLIATO
# ═══════════════════════════════════════════════════════════════

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "      RIEPILOGO AZIONI" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

if ($repairable.Count -gt 0) {
    Write-Host "SCRIPT CHE VERRANNO RIPARATI ($($repairable.Count)):" -ForegroundColor Green
    Write-Host ""
    
    $counter = 1
    foreach ($item in $repairable) {
        Write-Host "  $counter. $($item.FileName)" -ForegroundColor White
        Write-Host "     CORROTTO: $($item.CorruptedPath)" -ForegroundColor Red
        Write-Host "     SORGENTE:  $($item.SourcePath)" -ForegroundColor Green
        Write-Host "     ERRORE:    $($item.Error.Substring(0, [Math]::Min(80, $item.Error.Length)))..." -ForegroundColor DarkYellow
        Write-Host ""
        $counter++
    }
}

if ($notFound.Count -gt 0) {
    Write-Host "SCRIPT NON RIPARABILI (sorgente non trovata):" -ForegroundColor Yellow
    Write-Host ""
    
    foreach ($item in $notFound) {
        Write-Host "    $($item.FileName)" -ForegroundColor Yellow
        Write-Host "     Path: $($item.CorruptedPath)" -ForegroundColor Gray
        Write-Host ""
    }
}

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 4: CONFERMA
# ═══════════════════════════════════════════════════════════════

if ($repairable.Count -eq 0) {
    Write-Host " Nessuno script riparabile trovato!" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host "AZIONI CHE VERRANNO ESEGUITE:" -ForegroundColor Cyan
Write-Host "  • $($repairable.Count) file verranno sovrascritti" -ForegroundColor White
Write-Host "  • Le versioni corrotte verranno sostituite" -ForegroundColor White
Write-Host "  • Verrà creato un backup prima della modifica" -ForegroundColor White
Write-Host ""

if ($DryRun) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Magenta
    Write-Host "║               MODALITÀ DRY-RUN                   ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "[INFO] Nessuna modifica verrà effettuata" -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

if (-not $AutoConfirm) {
    Write-Host "════════════════════════════════════════════════════════" -ForegroundColor Yellow
    $confirmation = Read-Host "Procedere con la riparazione? (si/no)"
    Write-Host ""
    
    if ($confirmation -ne "si" -and $confirmation -ne "s" -and $confirmation -ne "yes" -and $confirmation -ne "y") {
        Write-Host " Operazione annullata dall'utente" -ForegroundColor Red
        Write-Host ""
        exit 0
    }
}

# ═══════════════════════════════════════════════════════════════
# FASE 5: BACKUP
# ═══════════════════════════════════════════════════════════════

Write-Host "[FASE 5] Creazione backup..." -ForegroundColor Cyan
Write-Host ""

$backupDir = Join-Path $REPO_PATH "install\checkmk-installer.BACKUP_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Write-Host "Directory backup: $backupDir" -ForegroundColor Gray
Write-Host ""

foreach ($item in $repairable) {
    $backupPath = Join-Path $backupDir ($item.CorruptedPath -replace '^install\\checkmk-installer\\', '')
    $backupDir = Split-Path $backupPath -Parent
    
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    
    Copy-Item $item.FullPath -Destination $backupPath -Force
}

Write-Host " Backup completato: $($repairable.Count) file salvati" -ForegroundColor Green
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 6: RIPARAZIONE
# ═══════════════════════════════════════════════════════════════

Write-Host "[FASE 6] Riparazione in corso..." -ForegroundColor Cyan
Write-Host ""

$repaired = 0
$failed = 0

foreach ($item in $repairable) {
    $sourcePath = Join-Path $REPO_PATH $item.SourcePath
    
    try {
        Copy-Item $sourcePath -Destination $item.FullPath -Force
        Write-Host "   $($item.FileName)" -ForegroundColor Green
        $repaired++
    } catch {
        Write-Host "   $($item.FileName) - Errore: $_" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════
# FASE 7: VERIFICA
# ═══════════════════════════════════════════════════════════════

Write-Host "[FASE 7] Verifica integrità post-riparazione..." -ForegroundColor Cyan
Write-Host ""

$stillCorrupted = 0

if ($wslAvailable) {
    foreach ($item in $repairable) {
        $wslPath = $item.FullPath -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
        $bashCheck = wsl bash -n "$wslPath" 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    $($item.FileName) - Ancora corrotto!" -ForegroundColor Yellow
            $stillCorrupted++
        }
    }
}

# ═══════════════════════════════════════════════════════════════
# REPORT FINALE
# ═══════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "      RIPARAZIONE COMPLETATA" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

Write-Host "RIEPILOGO FINALE:" -ForegroundColor White
Write-Host "  Script analizzati:        $($installerScripts.Count)" -ForegroundColor Gray
Write-Host "  Script corrotti trovati:  $($corruptedScripts.Count)" -ForegroundColor Yellow
Write-Host "  Script riparati:          $repaired" -ForegroundColor Green
Write-Host "  Script falliti:           $failed" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })
Write-Host "  Ancora corrotti:          $stillCorrupted" -ForegroundColor $(if ($stillCorrupted -eq 0) { "Green" } else { "Yellow" })
Write-Host ""

Write-Host "BACKUP:" -ForegroundColor White
Write-Host "  Percorso: $backupDir" -ForegroundColor Gray
Write-Host ""

if ($stillCorrupted -gt 0) {
    Write-Host "  ATTENZIONE: $stillCorrupted script risultano ancora corrotti" -ForegroundColor Yellow
    Write-Host "   Potrebbero richiedere riparazione manuale" -ForegroundColor Gray
    Write-Host ""
}

if ($notFound.Count -gt 0) {
    Write-Host "ℹ  INFO: $($notFound.Count) script non hanno una versione corretta disponibile" -ForegroundColor Cyan
    Write-Host "   Potrebbero richiedere ripristino da backup o riscrittura" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "PROSSIMI PASSI CONSIGLIATI:" -ForegroundColor Cyan
Write-Host "  1. Verifica funzionamento: .\check-integrity.ps1" -ForegroundColor Gray
Write-Host "  2. Se OK, commit: git add . && git commit -m 'Fix: Riparati script corrotti'" -ForegroundColor Gray
Write-Host "  3. Se problemi, ripristina: Copy-Item '$backupDir\*' -Destination 'install\checkmk-installer\' -Recurse -Force" -ForegroundColor Gray
Write-Host ""

Write-Host "================================================================" -ForegroundColor Green
Write-Host ""

# Exit code
if ($failed -gt 0) {
    exit 2  # Alcune riparazioni fallite
} elseif ($stillCorrupted -gt 0) {
    exit 1  # Riparazioni completate ma alcuni file ancora corrotti
} else {
    exit 0  # Tutto OK
}
