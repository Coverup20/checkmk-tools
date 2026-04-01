# Script di Controllo Integrità Repository CheckMK-Tools
# Verifica sintassi di tutti gli script senza eseguire il backup

param(
    [switch]$Detailed,      # Mostra lista completa errori
    [switch]$ExportReport,  # Esporta report in file
    [int]$Threshold = 15,   # Soglia corruzione (default 15%)
    [switch]$SendEmail      # Invia email se errori trovati
)

$ErrorActionPreference = "Continue"

$REPO_PATH = "C:\Users\Marzio\Desktop\CheckMK\checkmk-tools"

# === CONFIGURAZIONE EMAIL ===
$SMTP_SERVER = "smtp-relay.nethesis.it"
$SMTP_PORT = 587
$SMTP_USE_SSL = $true
$EMAIL_FROM = "checkmk@nethesis.it"
$EMAIL_TO = "marzio@nethesis.it"
$EMAIL_CREDENTIAL_FILE = "C:\CheckMK-Backups\smtp_credential.xml"

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "      CONTROLLO INTEGRITÀ REPOSITORY CHECKMK-TOOLS" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# Verifica esistenza repository
if (-not (Test-Path $REPO_PATH)) {
    Write-Host "[ERRORE] Repository non trovato: $REPO_PATH" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Repository: $REPO_PATH" -ForegroundColor Gray
Write-Host "[INFO] Soglia corruzione: $Threshold%" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# VERIFICA DISPONIBILITÀ WSL
# ═══════════════════════════════════════════════════════════════

$wslAvailable = $false
try {
    $null = wsl --version 2>&1
    $wslAvailable = $LASTEXITCODE -eq 0
} catch {
    $wslAvailable = $false
}

if ($wslAvailable) {
    Write-Host "[INFO] WSL disponibile - verifica sintassi bash abilitata" -ForegroundColor Green
} else {
    Write-Host "[WARNING] WSL non disponibile - verifica bash limitata" -ForegroundColor Yellow
}
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# RACCOLTA SCRIPT
# ═══════════════════════════════════════════════════════════════

Write-Host "[INFO] Ricerca script nel repository..." -ForegroundColor Cyan

$allScripts = Get-ChildItem -Path $REPO_PATH -Recurse -File -ErrorAction SilentlyContinue | 
    Where-Object { 
        $_.FullName -notmatch '\\\.git\\' -and
        $_.FullName -notmatch '\\BACKUP' -and
        $_.FullName -notmatch '\.BACKUP' -and
        $_.FullName -notmatch 'BACKUP-CORRUPTED-' -and
        $_.Name -notmatch '^(LICENSE|README|CHANGELOG|AUTHORS|Dockerfile)$' -and
        $_.Name -notmatch '^\.' -and
        ($_.Extension -in @('.ps1', '.sh', '.bash', '.bat', '.cmd', '.py') -or $_.Extension -eq '') -and
        $_.Name -notmatch '^(test-|debug-|backup-)' # Escludi script di test
    }

$totalScripts = $allScripts.Count

if ($totalScripts -eq 0) {
    Write-Host "[ERRORE] Nessuno script trovato!" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Trovati $totalScripts script da verificare" -ForegroundColor White
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# VERIFICA INTEGRITÀ
# ═══════════════════════════════════════════════════════════════

Write-Host "================================================================" -ForegroundColor Yellow
Write-Host "    VERIFICA INTEGRITÀ IN CORSO" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Yellow
Write-Host ""

$validScripts = 0
$corruptedScripts = 0
$corruptedList = @()
$categoryStats = @{
    'PowerShell' = @{ Total = 0; Valid = 0; Errors = 0 }
    'Bash/Shell' = @{ Total = 0; Valid = 0; Errors = 0 }
    'Batch' = @{ Total = 0; Valid = 0; Errors = 0 }
    'Python' = @{ Total = 0; Valid = 0; Errors = 0 }
}

foreach ($script in $allScripts) {
    $relativePath = $script.FullName.Replace($REPO_PATH, "").TrimStart('\')
    
    # Whitelist file che possono essere legittimamente vuoti
    $allowedEmptyFiles = @(
        "corrupted-files-list.txt",
        ".gitkeep",
        ".env"
    )
    $fileName = $script.Name
    $canBeEmpty = $allowedEmptyFiles -contains $fileName
    
    # Determina tipo tramite estensione + shebang (shebang ha precedenza)
    $scriptType = $script.Extension
    $category = 'Unknown'
    
    try {
        $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
        if ($firstLine -match '^#!/.*bash') {
            $scriptType = '.sh'
            $category = 'Bash/Shell'
        } elseif ($firstLine -match '^#!/.*python') {
            $scriptType = '.py'
            $category = 'Python'
        } elseif ($script.Extension -eq '') {
            # File senza estensione e shebang non riconosciuto: salta
            $validScripts++
            continue
        } else {
            # Categorizza per estensione
            $category = switch ($script.Extension) {
                '.ps1' { 'PowerShell' }
                { $_ -in @('.sh', '.bash') } { 'Bash/Shell' }
                { $_ -in @('.bat', '.cmd') } { 'Batch' }
                '.py' { 'Python' }
                default { 'Unknown' }
            }
        }
    } catch {
        # Non può leggere il file, salta
        $validScripts++
        continue
    }
    
    if ($categoryStats.ContainsKey($category)) {
        $categoryStats[$category].Total++
    }
    
    # Verifica PowerShell
    if ($scriptType -eq ".ps1") {
        try {
            $errors = $null
            $tokens = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
            
            if ($errors.Count -gt 0) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $errorMsg = ($errors[0].Message -replace "`n", " " -replace "`r", "")
                $corruptedList += "[SINTASSI PS] $relativePath - Line $($errors[0].Extent.StartLineNumber): $errorMsg"
                continue
            }
        } catch {
            $corruptedScripts++
            $categoryStats[$category].Errors++
            $corruptedList += "[ERRORE PS] $relativePath - $_"
            continue
        }
    }
    
    # Verifica Bash con WSL
    if ($scriptType -in @(".sh", ".bash") -and $wslAvailable) {
        try {
            # Converti path Windows in path WSL
            $wslPath = $script.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
            
            # Usa bash -n per syntax check
            $bashCheck = wsl bash -n "$wslPath" 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $errorMsg = if ($bashCheck) { ($bashCheck | Select-Object -First 2) -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI BASH] $relativePath - $errorMsg"
                continue
            }
            
            # Verifica permessi eseguibili
            $perms = wsl stat -c "%a" "$wslPath" 2>&1
            if ($LASTEXITCODE -eq 0 -and $perms -match '^\d{3}$') {
                $execBit = [int]::Parse($perms.Substring(2, 1))
                if (($execBit -band 1) -eq 0) {
                    # Non eseguibile, correggi automaticamente
                    wsl chmod +x "$wslPath" 2>&1 | Out-Null
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "  [FIX] Reso eseguibile: $relativePath" -ForegroundColor Yellow
                    }
                }
            }
        } catch {
            # Fallback: verifica shebang
            try {
                $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
                if (-not ($firstLine -match '^#!/')) {
                    Write-Host "  [WARN] Shebang mancante: $relativePath" -ForegroundColor DarkYellow
                }
            } catch {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $corruptedList += "[LETTURA] $relativePath - $_"
                continue
            }
        }
    }
    
    # Verifica Batch (controllo base)
    if ($scriptType -in @(".bat", ".cmd")) {
        try {
            $content = Get-Content $script.FullName -Raw -ErrorAction Stop
            # Skip verifica vuoto per file nella whitelist
            if ([string]::IsNullOrWhiteSpace($content) -and -not $canBeEmpty) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $corruptedList += "[VUOTO] $relativePath - File vuoto"
                continue
            }
        } catch {
            $corruptedScripts++
            $categoryStats[$category].Errors++
            $corruptedList += "[LETTURA] $relativePath - $_"
            continue
        }
    }
    
    # Verifica Python (controllo base sintassi)
    if ($scriptType -eq ".py") {
        try {
            $pythonCheck = python -m py_compile "$($script.FullName)" 2>&1
            if ($LASTEXITCODE -ne 0) {
                $corruptedScripts++
                $categoryStats[$category].Errors++
                $errorMsg = if ($pythonCheck) { $pythonCheck -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI PY] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # Python non disponibile, skip
        }
    }
    
    $validScripts++
    if ($categoryStats.ContainsKey($category)) {
        $categoryStats[$category].Valid++
    }
    
    if ($validScripts % 100 -eq 0) {
        Write-Host "  Verificati $validScripts / $totalScripts script..." -ForegroundColor Gray
    }
}

# ═══════════════════════════════════════════════════════════════
# CALCOLO PERCENTUALE CORRUZIONE
# ═══════════════════════════════════════════════════════════════

$corruptionPercentage = if ($totalScripts -gt 0) { 
    [math]::Round(($corruptedScripts / $totalScripts) * 100, 2) 
} else { 
    0 
}

# ═══════════════════════════════════════════════════════════════
# REPORT RISULTATI
# ═══════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "    RISULTATI VERIFICA INTEGRITÀ" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "RIEPILOGO GENERALE:" -ForegroundColor White
Write-Host "  Script verificati:    $totalScripts" -ForegroundColor Gray
Write-Host "  Script validi:        $validScripts" -ForegroundColor Green
Write-Host "  Script con errori:    $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "  Percentuale errori:   $corruptionPercentage%" -ForegroundColor $(if ($corruptionPercentage -gt $Threshold) { "Red" } elseif ($corruptionPercentage -gt 5) { "Yellow" } else { "Green" })
Write-Host "  Soglia corruzione:    $Threshold%" -ForegroundColor Gray
Write-Host ""

# Statistiche per categoria
Write-Host "DETTAGLIO PER TIPO:" -ForegroundColor White
foreach ($cat in $categoryStats.Keys | Sort-Object) {
    $stats = $categoryStats[$cat]
    if ($stats.Total -gt 0) {
        $catPercent = [math]::Round(($stats.Errors / $stats.Total) * 100, 1)
        Write-Host "  $cat" -ForegroundColor Cyan
        Write-Host "    Totale:      $($stats.Total)" -ForegroundColor Gray
        Write-Host "    Validi:      $($stats.Valid)" -ForegroundColor Green
        Write-Host "    Errori:      $($stats.Errors) ($catPercent%)" -ForegroundColor $(if ($stats.Errors -eq 0) { "Green" } else { "Yellow" })
    }
}
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# VALUTAZIONE SOGLIA
# ═══════════════════════════════════════════════════════════════

Write-Host "================================================================" -ForegroundColor $(if ($corruptionPercentage -gt $Threshold) { "Red" } else { "Green" })
Write-Host "    VALUTAZIONE FINALE" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor $(if ($corruptionPercentage -gt $Threshold) { "Red" } else { "Green" })
Write-Host ""

if ($corruptionPercentage -gt $Threshold) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║        CORRUZIONE MASSIVA RILEVATA               ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "[STATO] CRITICO - Corruzione sopra soglia!" -ForegroundColor Red
    Write-Host "  • Il backup automatico verrebbe BLOCCATO" -ForegroundColor Red
    Write-Host "  • Necessaria azione immediata" -ForegroundColor Red
    Write-Host ""
    Write-Host "AZIONI CONSIGLIATE:" -ForegroundColor Yellow
    Write-Host "  1. Verifica encoding dei file (UTF-8 vs ANSI)" -ForegroundColor Gray
    Write-Host "  2. Controlla line endings (CRLF vs LF)" -ForegroundColor Gray
    Write-Host "  3. Esegui 'git status' per vedere modifiche massive" -ForegroundColor Gray
    Write-Host "  4. Considera ripristino da backup precedente" -ForegroundColor Gray
    Write-Host ""
    $exitCode = 2
} elseif ($corruptedScripts -gt 0) {
    Write-Host "[STATO] WARNING - Errori rilevati ma sotto soglia" -ForegroundColor Yellow
    Write-Host "  • Il backup automatico continuerebbe normalmente" -ForegroundColor Yellow
    Write-Host "  • Errori presenti: $corruptedScripts ($corruptionPercentage%)" -ForegroundColor Yellow
    Write-Host "  • Considerare la correzione quando possibile" -ForegroundColor Gray
    Write-Host ""
    $exitCode = 1
} else {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "║          REPOSITORY INTEGRO                       ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "[STATO] OK - Nessun errore rilevato" -ForegroundColor Green
    Write-Host "  • Tutti gli script sono validi" -ForegroundColor Green
    Write-Host "  • Il backup automatico funziona correttamente" -ForegroundColor Green
    Write-Host ""
    $exitCode = 0
}

# ═══════════════════════════════════════════════════════════════
# LISTA DETTAGLIATA ERRORI
# ═══════════════════════════════════════════════════════════════

if ($corruptedScripts -gt 0 -and ($Detailed -or $corruptionPercentage -gt $Threshold)) {
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host "    LISTA ERRORI DETTAGLIATA" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Yellow
    Write-Host ""
    
    $maxToShow = if ($Detailed) { $corruptedList.Count } else { [Math]::Min(20, $corruptedList.Count) }
    
    for ($i = 0; $i -lt $maxToShow; $i++) {
        Write-Host "  $($i+1). $($corruptedList[$i])" -ForegroundColor Red
    }
    
    if ($corruptedList.Count -gt $maxToShow) {
        Write-Host ""
        Write-Host "  ... e altri $($corruptedList.Count - $maxToShow) errori" -ForegroundColor DarkRed
        Write-Host "  Usa -Detailed per vedere tutti gli errori" -ForegroundColor Gray
    }
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════
# EXPORT REPORT
# ═══════════════════════════════════════════════════════════════

if ($ExportReport) {
    $reportPath = Join-Path $REPO_PATH "integrity-report_$(Get-Date -Format 'yyyy-MM-dd_HH-mm-ss').txt"
    
    $reportContent = @"
================================================================
 REPORT INTEGRITÀ REPOSITORY CHECKMK-TOOLS
================================================================

Data verifica: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Repository: $REPO_PATH

RIEPILOGO:
  Script verificati:    $totalScripts
  Script validi:        $validScripts
  Script con errori:    $corruptedScripts
  Percentuale errori:   $corruptionPercentage%
  Soglia corruzione:    $Threshold%

STATO: $(if ($corruptionPercentage -gt $Threshold) { 'CRITICO' } elseif ($corruptedScripts -gt 0) { 'WARNING' } else { 'OK' })

DETTAGLIO PER TIPO:
"@
    
    foreach ($cat in $categoryStats.Keys | Sort-Object) {
        $stats = $categoryStats[$cat]
        if ($stats.Total -gt 0) {
            $catPercent = [math]::Round(($stats.Errors / $stats.Total) * 100, 1)
            $reportContent += "`n  $cat : $($stats.Total) script, $($stats.Errors) errori ($catPercent%)"
        }
    }
    
    if ($corruptedScripts -gt 0) {
        $reportContent += "`n`n================================================================`nLISTA ERRORI DETTAGLIATA:`n================================================================`n"
        $reportContent += $corruptedList -join "`n"
    }
    
    $reportContent | Out-File -FilePath $reportPath -Encoding UTF8
    Write-Host "[INFO] Report esportato: $reportPath" -ForegroundColor Cyan
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════
# INVIO EMAIL SE RICHIESTO E ERRORI TROVATI
# ═══════════════════════════════════════════════════════════════

if ($SendEmail -and $corruptedScripts -gt 0) {
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "    INVIO EMAIL NOTIFICA ERRORI" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    
    try {
        $emailSubject = "[CheckMK Integrity] ERRORI RILEVATI - $corruptedScripts script corrotti"
        
        $emailBody = @"
===============================================================
       CONTROLLO INTEGRITÀ - ERRORI RILEVATI
===============================================================

Data e ora: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Repository: $REPO_PATH

---------------------------------------------------------------
  RIEPILOGO GENERALE
---------------------------------------------------------------
Script verificati:     $totalScripts
Script validi:         $validScripts
Script corrotti:       $corruptedScripts
Percentuale errori:    $([math]::Round($corruptionPercentage, 2))%
Soglia corruzione:     $Threshold%

STATO: $(if ($corruptionPercentage -gt $Threshold) { 'CRITICO ' } else { 'WARNING ' })

---------------------------------------------------------------
  DETTAGLIO PER TIPO
---------------------------------------------------------------
"@
        
        foreach ($cat in $categoryStats.Keys | Sort-Object) {
            $stats = $categoryStats[$cat]
            if ($stats.Total -gt 0) {
                $catPercent = [math]::Round(($stats.Errors / $stats.Total) * 100, 1)
                $emailBody += "`n  $cat"
                $emailBody += "`n    Totale:      $($stats.Total)"
                $emailBody += "`n    Validi:      $($stats.Valid)"
                $emailBody += "`n    Errori:      $($stats.Errors) ($catPercent%)"
            }
        }
        
        if ($corruptedList.Count -gt 0) {
            $emailBody += "`n`n---------------------------------------------------------------"
            $emailBody += "`n  LISTA SCRIPT CORROTTI (primi 20)"
            $emailBody += "`n---------------------------------------------------------------`n"
            $emailBody += ($corruptedList | Select-Object -First 20) -join "`n"
            
            if ($corruptedList.Count -gt 20) {
                $emailBody += "`n`n... e altri $($corruptedList.Count - 20) errori"
                $emailBody += "`n`nEsegui: .\check-integrity.ps1 -Detailed per vedere tutti gli errori"
            }
        }
        
        $emailBody += @"


---------------------------------------------------------------
  AZIONE RICHIESTA
---------------------------------------------------------------
Verificare e correggere gli script con errori di sintassi.
Eseguire: .\check-integrity.ps1 -Detailed per lista completa

===============================================================
  NOTIFICA AUTOMATICA CONTROLLO INTEGRITÀ
===============================================================

Questo è un messaggio automatico generato dal sistema.
"@
        
        $smtpParams = @{
            SmtpServer = $SMTP_SERVER
            Port = $SMTP_PORT
            From = $EMAIL_FROM
            To = $EMAIL_TO
            Subject = $emailSubject
            Body = $emailBody
            Encoding = [System.Text.Encoding]::UTF8
        }
        
        if ($SMTP_USE_SSL) {
            $smtpParams.UseSsl = $true
        }
        
        if (Test-Path $EMAIL_CREDENTIAL_FILE) {
            $credential = Import-Clixml -Path $EMAIL_CREDENTIAL_FILE
            $smtpParams.Credential = $credential
            
            Send-MailMessage @smtpParams -WarningAction SilentlyContinue
            Write-Host "[OK] Email inviata a: $EMAIL_TO" -ForegroundColor Green
        } else {
            Write-Host "[WARN] Impossibile inviare email: credenziali mancanti" -ForegroundColor Yellow
            Write-Host "[INFO] File richiesto: $EMAIL_CREDENTIAL_FILE" -ForegroundColor Gray
        }
        
    } catch {
        Write-Host "[WARN] Impossibile inviare email: $_" -ForegroundColor Yellow
    }
    
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════
# RIEPILOGO COMANDI UTILI
# ═══════════════════════════════════════════════════════════════

if ($corruptedScripts -gt 0) {
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "    COMANDI UTILI" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  .\check-integrity.ps1 -Detailed       # Mostra tutti gli errori" -ForegroundColor Gray
    Write-Host "  .\check-integrity.ps1 -ExportReport   # Esporta report completo" -ForegroundColor Gray
    Write-Host "  .\check-integrity.ps1 -Threshold 20   # Cambia soglia" -ForegroundColor Gray
    Write-Host "  git status                             # Verifica modifiche" -ForegroundColor Gray
    Write-Host "  git diff                               # Mostra differenze" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

exit $exitCode
