# Script di Backup Automatico Repository CheckMK-Tools
# Versione semplificata per Scheduled Task (solo caratteri ASCII)

param(
    [switch]$Unattended
)

$ErrorActionPreference = "Stop"

# === CONFIGURAZIONE ===
$REPO_PATH = "C:\Users\Gaming\Desktop\CheckMK\checkmk-tools"
$LOCAL_BACKUP_BASE = "C:\CheckMK-Backups"
$NETWORK_BACKUP_BASE = "\\192.168.10.132\usbshare\CheckMK-Backups"
$TIMESTAMP = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LOCAL_BACKUP_PATH = Join-Path $LOCAL_BACKUP_BASE $TIMESTAMP
$NETWORK_BACKUP_PATH = Join-Path $NETWORK_BACKUP_BASE $TIMESTAMP
$RETENTION_COUNT = 20

# === CONFIGURAZIONE EMAIL ===
$SMTP_SERVER = "smtp-relay.nethesis.it"
$SMTP_PORT = 587
$SMTP_USE_SSL = $true
$EMAIL_FROM = "checkmk@nethesis.it"
$EMAIL_TO = "marzio@nethesis.it"
$EMAIL_CREDENTIAL_FILE = Join-Path $LOCAL_BACKUP_BASE "smtp_credential.xml"  # File credenziali crittografato
$SEND_EMAIL = $true  # Email attivata

# === VARIABILI GLOBALI PER EMAIL ERRORE ===
$GLOBAL_ERROR_MESSAGE = ""

Write-Host ""
Write-Host "================================================================"
Write-Host "     BACKUP COMPLETO REPOSITORY CHECKMK-TOOLS"
Write-Host "================================================================"
Write-Host ""

# === INIZIO TRY GLOBALE PER GESTIONE ERRORI ===
try {

# Crea cartella backup se non esiste
if (-not (Test-Path $LOCAL_BACKUP_BASE)) {
    New-Item -ItemType Directory -Path $LOCAL_BACKUP_BASE -Force | Out-Null
}

# Verifica che il repository esista
if (-not (Test-Path $REPO_PATH)) {
    Write-Host "[ERRORE] Repository non trovato: $REPO_PATH" -ForegroundColor Red
    throw "Repository non trovato: $REPO_PATH"
}

# === CONTROLLO INTEGRITA SCRIPT ===
Write-Host "================================================================"
Write-Host "    CONTROLLO INTEGRITA SCRIPT"
Write-Host "================================================================"
Write-Host ""

# Verifica disponibilità WSL per controllo sintassi bash
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
    Write-Host "[WARN] WSL non disponibile - verifica bash limitata" -ForegroundColor Yellow
}

$scriptFiles = Get-ChildItem -Path $REPO_PATH -Recurse -File -ErrorAction SilentlyContinue | 
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
$totalScripts = $scriptFiles.Count
$validScripts = 0
$corruptedScripts = 0
$corruptedList = @()

Write-Host "[INFO] Verifica di $totalScripts script..." -ForegroundColor Cyan

# Whitelist file che possono essere legittimamente vuoti
$allowedEmptyFiles = @(
    "corrupted-files-list.txt",
    ".gitkeep",
    ".env"
)

foreach ($script in $scriptFiles) {
    $relativePath = $script.FullName.Replace($REPO_PATH, "").TrimStart('\')
    $fileName = $script.Name
    $canBeEmpty = $allowedEmptyFiles -contains $fileName
    
    # Verifica file non vuoto (a meno che non sia nella whitelist)
    if ($script.Length -eq 0 -and -not $canBeEmpty) {
        $corruptedScripts++
        $corruptedList += "[VUOTO] $relativePath"
        continue
    }
    
    # Determina tipo tramite estensione o shebang
    $scriptType = $script.Extension
    
    if ($script.Extension -eq '') {
        # File senza estensione: controlla shebang
        try {
            $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
            if ($firstLine -match '^#!/.*bash') {
                $scriptType = '.sh'
            } elseif ($firstLine -match '^#!/.*python') {
                $scriptType = '.py'
            } else {
                # Shebang non riconosciuto, salta
                $validScripts++
                continue
            }
        } catch {
            # Non può leggere il file, salta
            $validScripts++
            continue
        }
    }
    
    # Verifica sintassi PowerShell con ParseFile
    if ($scriptType -eq ".ps1") {
        try {
            $errors = $null
            $tokens = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$errors)
            
            if ($errors -and $errors.Count -gt 0) {
                $corruptedScripts++
                $corruptedList += "[SINTASSI PS] $relativePath - $($errors[0].Message)"
                continue
            }
        } catch {
            $corruptedScripts++
            $corruptedList += "[ERRORE PS] $relativePath - $_"
            continue
        }
    }
    
    # Verifica sintassi bash/sh con WSL (bash -n)
    if ($scriptType -in @(".sh", ".bash") -and $wslAvailable) {
        try {
            # Converti path Windows in path WSL
            $wslPath = $script.FullName -replace '\\', '/' -replace '^([A-Z]):', { "/mnt/$($_.Groups[1].Value.ToLower())" }
            
            # Usa bash -n per syntax check (non esegue lo script)
            $bashCheck = wsl bash -n "$wslPath" 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -ne 0) {
                $corruptedScripts++
                $errorMsg = if ($bashCheck) { ($bashCheck | Select-Object -First 2) -join "; " } else { "Syntax error" }
                $corruptedList += "[SINTASSI BASH] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # Se bash -n fallisce, prova almeno a verificare il shebang
            try {
                $firstLine = Get-Content $script.FullName -First 1 -ErrorAction Stop
                if (-not ($firstLine -match '^#!/')) {
                    Write-Host "  [WARN] Shebang mancante: $relativePath" -ForegroundColor DarkYellow
                }
            } catch {
                $corruptedScripts++
                $corruptedList += "[LETTURA] $relativePath - $_"
                continue
            }
        }
    }
    
    # Verifica sintassi Batch/CMD
    if ($scriptType -in @(".bat", ".cmd")) {
        try {
            # cmd /c verifica la sintassi senza eseguire
            $cmdCheck = cmd /c "echo off & call `"$($script.FullName)`" /?" 2>&1
            if ($LASTEXITCODE -ne 0 -and $cmdCheck -match "syntax error|unexpected|invalid") {
                $corruptedScripts++
                $errorMsg = ($cmdCheck | Select-Object -First 2) -join "; "
                $corruptedList += "[SINTASSI BAT] $relativePath - $errorMsg"
                continue
            }
        } catch {
            # Errore durante la verifica, ma non blocchiamo
            Write-Host "  [WARN] Impossibile verificare: $relativePath" -ForegroundColor DarkYellow
        }
    }
    
    $validScripts++
    if ($validScripts % 100 -eq 0) {
        Write-Host "  Verificati $validScripts / $totalScripts script..." -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "================================================================"
Write-Host "  Script verificati: $totalScripts" -ForegroundColor Gray
Write-Host "  Script validi:     $validScripts" -ForegroundColor Green
Write-Host "  Script corrotti:   $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "================================================================"
Write-Host ""

# ═══════════════════════════════════════════════════════════════
# CONTROLLO SOGLIA CORRUZIONE MASSIVA
# ═══════════════════════════════════════════════════════════════
$corruptionPercentage = if ($totalScripts -gt 0) { 
    [math]::Round(($corruptedScripts / $totalScripts) * 100, 2) 
} else { 
    0 
}

# Soglia 15%: se più del 15% degli script è corrotto, blocca il backup
$CORRUPTION_THRESHOLD = 15

Write-Host "Percentuale errori: $corruptionPercentage%" -ForegroundColor $(if ($corruptionPercentage -gt $CORRUPTION_THRESHOLD) { "Red" } else { "Yellow" })
Write-Host ""

if ($corruptionPercentage -gt $CORRUPTION_THRESHOLD) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║        CORRUZIONE MASSIVA RILEVATA               ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Red
    Write-Host ""
    Write-Host "[ERRORE CRITICO] Rilevata corruzione massiva del repository!" -ForegroundColor Red
    Write-Host "  • Script corrotti: $corruptedScripts / $totalScripts ($($corruptionPercentage)%)" -ForegroundColor Red
    Write-Host "  • Soglia sicurezza: $($CORRUPTION_THRESHOLD)%" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "[BACKUP ANNULLATO] Per evitare di propagare la corruzione ai backup esistenti!" -ForegroundColor Red
    Write-Host ""
    Write-Host "AZIONI CONSIGLIATE:" -ForegroundColor Yellow
    Write-Host "  1. Verifica encoding dei file (UTF-8 vs ANSI)" -ForegroundColor Gray
    Write-Host "  2. Controlla line endings (CRLF vs LF)" -ForegroundColor Gray
    Write-Host "  3. Ripristina da un backup precedente se necessario" -ForegroundColor Gray
    Write-Host "  4. Esegui 'git status' per verificare modifiche massive" -ForegroundColor Gray
    Write-Host "  5. Controlla se c'è stata una conversione di massa non intenzionale" -ForegroundColor Gray
    Write-Host ""
    
    # Mostra primi 10 errori per diagnostica
    Write-Host "Primi errori rilevati (per diagnostica):" -ForegroundColor Yellow
    $corruptedList | Select-Object -First 10 | ForEach-Object {
        Write-Host "  - $_" -ForegroundColor Red
    }
    if ($corruptedList.Count -gt 10) {
        Write-Host "  ... e altri $($corruptedList.Count - 10) errori" -ForegroundColor DarkRed
    }
    Write-Host ""
    
    exit 1
}

# Se sotto soglia, continua con warning
if ($corruptedScripts -gt 0) {
    Write-Host "[WARNING] Trovati $corruptedScripts errori (sotto soglia $CORRUPTION_THRESHOLD%, backup continua)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Script segnalati (errori non critici):" -ForegroundColor Gray
    foreach ($item in $corruptedList) {
        Write-Host "  - $item" -ForegroundColor DarkYellow
    }
    Write-Host ""
    Write-Host "[INFO] Backup procede comunque..." -ForegroundColor Cyan
}

Write-Host "[OK] Proseguo con il backup..." -ForegroundColor Green
Write-Host ""

# Conta tutti i file per il backup (con filtri di esclusione)
$allFiles = Get-ChildItem -Path $REPO_PATH -Recurse -File -ErrorAction SilentlyContinue | 
    Where-Object { 
        $_.FullName -notmatch '\\\.git\\' -and
        $_.FullName -notmatch '\\BACKUP' -and
        $_.FullName -notmatch '\.BACKUP' -and
        $_.FullName -notmatch 'BACKUP-CORRUPTED-' -and
        $_.Name -notmatch '^\.' # Escludi file nascosti
    }
$totalFiles = $allFiles.Count

if ($totalFiles -eq 0) {
    Write-Host "[ERRORE] Nessun file trovato nel repository!" -ForegroundColor Red
    exit 1
}

Write-Host "[INFO] Trovati $totalFiles file da backuppare" -ForegroundColor Cyan
Write-Host ""

if (-not $Unattended) {
    Write-Host "Premi un tasto per continuare con il backup..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Write-Host ""
}

# === BACKUP LOCALE ===
Write-Host "================================================================"
Write-Host "    BACKUP LOCALE"
Write-Host "================================================================"
Write-Host ""
Write-Host "[INFO] Destinazione: $LOCAL_BACKUP_PATH" -ForegroundColor Gray
Write-Host ""

# Crea cartella backup
try {
    New-Item -ItemType Directory -Path $LOCAL_BACKUP_PATH -Force | Out-Null
    Write-Host "[OK] Cartella backup creata" -ForegroundColor Green
} catch {
    Write-Host "[ERRORE] Impossibile creare cartella backup: $_" -ForegroundColor Red
    exit 1
}

# Copia file
Write-Host ""
Write-Host "[INFO] Copia file in corso..." -ForegroundColor Cyan

$copiedFiles = 0
$errorCount = 0

foreach ($file in $allFiles) {
    $relativePath = $file.FullName.Replace($REPO_PATH, "").TrimStart('\')
    $destinationPath = Join-Path $LOCAL_BACKUP_PATH $relativePath
    $destinationDir = Split-Path $destinationPath -Parent
    
    try {
        if (-not (Test-Path $destinationDir)) {
            New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
        }
        
        Copy-Item -Path $file.FullName -Destination $destinationPath -Force
        $copiedFiles++
        
        if ($copiedFiles % 50 -eq 0) {
            Write-Host "  Copiati $copiedFiles / $totalFiles file..." -ForegroundColor Gray
        }
    } catch {
        $errorCount++
        Write-Host "[WARN] Errore copia file $relativePath" -ForegroundColor Yellow
    }
}

Write-Host "[OK] Completato: $copiedFiles file copiati" -ForegroundColor Green

if ($errorCount -gt 0) {
    Write-Host "[WARN] $errorCount file non copiati" -ForegroundColor Yellow
}

# Calcola dimensione backup locale
$backupSize = (Get-ChildItem -Path $LOCAL_BACKUP_PATH -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB

# === BACKUP SU RETE ===
Write-Host ""
Write-Host "================================================================"
Write-Host "    BACKUP SU RETE"
Write-Host "================================================================"
Write-Host ""

$networkCopied = 0
$networkSuccess = $false

# Verifica connessione rete
if (Test-Path $NETWORK_BACKUP_BASE) {
    Write-Host "[INFO] Share di rete raggiungibile" -ForegroundColor Green
    Write-Host "[INFO] Destinazione: $NETWORK_BACKUP_PATH" -ForegroundColor Gray
    Write-Host ""
    
    try {
        # Crea cartella backup di rete
        New-Item -ItemType Directory -Path $NETWORK_BACKUP_PATH -Force -ErrorAction Stop | Out-Null
        Write-Host "[OK] Cartella backup rete creata" -ForegroundColor Green
        Write-Host ""
        Write-Host "[INFO] Copia file su rete in corso..." -ForegroundColor Cyan
        
        # Copia ricorsiva
        foreach ($file in $allFiles) {
            $relativePath = $file.FullName.Replace($REPO_PATH, "").TrimStart('\')
            $destinationPath = Join-Path $NETWORK_BACKUP_PATH $relativePath
            $destinationDir = Split-Path $destinationPath -Parent
            
            try {
                if (-not (Test-Path $destinationDir)) {
                    New-Item -ItemType Directory -Path $destinationDir -Force -ErrorAction Stop | Out-Null
                }
                
                Copy-Item -Path $file.FullName -Destination $destinationPath -Force -ErrorAction Stop
                $networkCopied++
                
                if ($networkCopied % 50 -eq 0) {
                    Write-Host "  Copiati $networkCopied / $totalFiles file..." -ForegroundColor Gray
                }
            } catch {
                Write-Host "[WARN] Errore copia file $relativePath su rete" -ForegroundColor Yellow
            }
        }
        
        Write-Host "[OK] Backup rete completato: $networkCopied file copiati" -ForegroundColor Green
        $networkSuccess = $true
        
    } catch {
        Write-Host "[ERRORE] Backup su rete fallito: $_" -ForegroundColor Red
        Write-Host "[INFO] Il backup locale e comunque disponibile" -ForegroundColor Yellow
    }
} else {
    Write-Host "[WARN] Share di rete non raggiungibile: $NETWORK_BACKUP_BASE" -ForegroundColor Yellow
    Write-Host "[INFO] Continuo solo con backup locale" -ForegroundColor Yellow
}

# === STATISTICHE ===
Write-Host ""
Write-Host "================================================================"
Write-Host "    STATISTICHE BACKUP"
Write-Host "================================================================"
Write-Host ""
Write-Host "  LOCALE:" -ForegroundColor Cyan
Write-Host "    File copiati:     $copiedFiles" -ForegroundColor Gray
Write-Host "    Dimensione:       $([math]::Round($backupSize, 2)) MB" -ForegroundColor Gray
Write-Host "    Percorso:         $LOCAL_BACKUP_PATH" -ForegroundColor Gray
Write-Host ""
if ($networkSuccess) {
    Write-Host "  RETE:" -ForegroundColor Cyan
    Write-Host "    File copiati:     $networkCopied" -ForegroundColor Gray
    Write-Host "    Percorso:         $NETWORK_BACKUP_PATH" -ForegroundColor Gray
} else {
    Write-Host "  RETE: Non disponibile" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  Timestamp:        $TIMESTAMP" -ForegroundColor Gray
Write-Host ""

# === RETENTION POLICY ===
Write-Host "================================================================"
Write-Host "    PULIZIA BACKUP VECCHI (Retention)"
Write-Host "================================================================"
Write-Host ""

$existingBackups = Get-ChildItem -Path $LOCAL_BACKUP_BASE -Directory | 
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$' } |
    Sort-Object Name -Descending

$backupCount = $existingBackups.Count
Write-Host "[INFO] Backup totali: $backupCount (retention: $RETENTION_COUNT)" -ForegroundColor Cyan

if ($backupCount -gt $RETENTION_COUNT) {
    $toDelete = $backupCount - $RETENTION_COUNT
    Write-Host "[INFO] Verranno eliminati $toDelete backup piu vecchi..." -ForegroundColor Yellow
    Write-Host ""
    
    $backupsToDelete = $existingBackups | Select-Object -Skip $RETENTION_COUNT
    
    foreach ($backup in $backupsToDelete) {
        try {
            Write-Host "  [DELETE] $($backup.Name)" -ForegroundColor Gray
            Remove-Item -Path $backup.FullName -Recurse -Force -ErrorAction Stop
            Write-Host "     [OK] Eliminato" -ForegroundColor Green
        } catch {
            Write-Host "     [ERRORE] $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    Write-Host ""
    Write-Host "[OK] Pulizia completata: mantenuti gli ultimi $RETENTION_COUNT backup" -ForegroundColor Green
} else {
    Write-Host "[INFO] Nessun backup da eliminare" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================================"
Write-Host "    BACKUP COMPLETATO CON SUCCESSO"
Write-Host "================================================================"
Write-Host ""

# === INVIO EMAIL REPORT ===
if ($SEND_EMAIL) {
    Write-Host "================================================================"
    Write-Host "    INVIO EMAIL REPORT"
    Write-Host "================================================================"
    Write-Host ""
    
    try {
        $emailSubject = "[CheckMK Backup] Completato - $TIMESTAMP"
        
        $emailBody = @"
===============================================================
       REPORT BACKUP REPOSITORY CHECKMK-TOOLS
===============================================================

Data e ora: $TIMESTAMP
Host: $env:COMPUTERNAME

---------------------------------------------------------------
  CONTROLLO INTEGRITA SCRIPT
---------------------------------------------------------------
Script verificati:     $totalScripts
Script validi:         $validScripts
Script corrotti:       $corruptedScripts
Stato:                 $(if ($corruptedScripts -eq 0) { "OK" } else { "WARNING" })

"@
        
        # Aggiungi lista errori se presenti
        if ($corruptedScripts -gt 0 -and $corruptedList.Count -gt 0) {
            $emailBody += "`nScript con errori sintassi bash:`n"
            $emailBody += "---------------------------------------------------------------`n"
            foreach ($errorItem in $corruptedList) {
                $emailBody += "  - $errorItem`n"
            }
        }
        
        $emailBody += @"

---------------------------------------------------------------
  BACKUP LOCALE
---------------------------------------------------------------
File copiati:          $copiedFiles
Dimensione:            $([math]::Round($backupSize, 2)) MB
Percorso:              $LOCAL_BACKUP_PATH

---------------------------------------------------------------
  BACKUP RETE
---------------------------------------------------------------
"@
        
        if ($networkSuccess) {
            $emailBody += @"
Stato:                 COMPLETATO
File copiati:          $networkCopied
Percorso:              $NETWORK_BACKUP_PATH

"@
        } else {
            $emailBody += @"
Stato:                 NON DISPONIBILE
Motivo:                Share di rete non raggiungibile

"@
        }
        
        $emailBody += @"
---------------------------------------------------------------
  RETENTION POLICY
---------------------------------------------------------------
Backup totali:         $backupCount
Retention:             $RETENTION_COUNT
"@
        
        if ($backupCount -gt $RETENTION_COUNT) {
            $deleted = $backupCount - $RETENTION_COUNT
            $emailBody += "Backup eliminati:      $deleted`n"
        } else {
            $emailBody += "Backup eliminati:      0`n"
        }
        
        $emailBody += @"

===============================================================
  BACKUP COMPLETATO CON SUCCESSO
===============================================================

Questo e un messaggio automatico generato dal sistema di backup.
"@
        
        # Prepara credenziali se necessarie
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
        
        # Carica credenziali crittografate se esistono
        if (Test-Path $EMAIL_CREDENTIAL_FILE) {
            $credential = Import-Clixml -Path $EMAIL_CREDENTIAL_FILE
            $smtpParams.Credential = $credential
        } else {
            Write-Host "[WARN] File credenziali non trovato: $EMAIL_CREDENTIAL_FILE" -ForegroundColor Yellow
            Write-Host "[INFO] Esegui: .\setup-smtp-credentials.ps1 per configurare" -ForegroundColor Cyan
            throw "Credenziali SMTP mancanti"
        }
        
        Send-MailMessage @smtpParams -WarningAction SilentlyContinue
        
        Write-Host "[OK] Email inviata a: $EMAIL_TO" -ForegroundColor Green
        
    } catch {
        Write-Host "[WARN] Impossibile inviare email: $_" -ForegroundColor Yellow
        Write-Host "[INFO] Il backup e comunque completato correttamente" -ForegroundColor Cyan
    }
    
    Write-Host ""
}

exit 0

} catch {
    # === GESTIONE ERRORE GLOBALE CON INVIO EMAIL ===
    $GLOBAL_ERROR_MESSAGE = $_.Exception.Message
    $errorDetails = $_.Exception | Out-String
    
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host "    BACKUP FALLITO - ERRORE CRITICO" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "[ERRORE] $GLOBAL_ERROR_MESSAGE" -ForegroundColor Red
    Write-Host ""
    
    # Invia email di errore
    if ($SEND_EMAIL) {
        try {
            $emailSubject = "[CheckMK Backup] ERRORE - $TIMESTAMP"
            
            $emailBody = @"
===============================================================
       BACKUP FALLITO - ERRORE CRITICO
===============================================================

Data e ora: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host: $env:COMPUTERNAME
Repository: $REPO_PATH

---------------------------------------------------------------
  DETTAGLIO ERRORE
---------------------------------------------------------------
$GLOBAL_ERROR_MESSAGE

---------------------------------------------------------------
  STACK TRACE
---------------------------------------------------------------
$errorDetails

---------------------------------------------------------------
  AZIONE RICHIESTA
---------------------------------------------------------------
Verificare manualmente il sistema di backup.
Log disponibile in: C:\CheckMK-Backups\logs\

===============================================================
  NOTIFICA AUTOMATICA DI ERRORE
===============================================================

Questo e un messaggio automatico generato dal sistema di backup.
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
                Write-Host "[OK] Email di errore inviata a: $EMAIL_TO" -ForegroundColor Green
            } else {
                Write-Host "[WARN] Impossibile inviare email: credenziali mancanti" -ForegroundColor Yellow
            }
            
        } catch {
            Write-Host "[WARN] Impossibile inviare email di errore: $_" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    exit 1
}
