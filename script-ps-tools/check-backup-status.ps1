# Verifica Stato Backup Automatico
# Mostra risultati ultima esecuzione e log

$ErrorActionPreference = "Stop"

$TASK_NAME = "CheckMK-Backup-Auto"
$LOG_PATH = "C:\CheckMK-Backups\logs"

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║         STATO BACKUP AUTOMATICO                     ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# Verifica che il task esista
$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host " Task '$TASK_NAME' non trovato!" -ForegroundColor Red
    Write-Host "  Esegui 'setup-backup-task.ps1' per configurarlo." -ForegroundColor Yellow
    exit 1
}

# Ottieni info task
$taskInfo = Get-ScheduledTaskInfo -TaskName $TASK_NAME

Write-Host " Stato Task:" -ForegroundColor Yellow
Write-Host "   Nome: $TASK_NAME" -ForegroundColor Gray
Write-Host "   Stato: $($task.State)" -ForegroundColor $(if ($task.State -eq "Ready") { "Green" } else { "Yellow" })

# Ultima esecuzione
if ($taskInfo.LastRunTime) {
    $tempoTrascorso = (Get-Date) - $taskInfo.LastRunTime
    $tempoTestoDa = if ($tempoTrascorso.Days -gt 0) {
        "$($tempoTrascorso.Days) giorni fa"
    } elseif ($tempoTrascorso.Hours -gt 0) {
        "$($tempoTrascorso.Hours) ore fa"
    } elseif ($tempoTrascorso.Minutes -gt 0) {
        "$($tempoTrascorso.Minutes) minuti fa"
    } else {
        "pochi secondi fa"
    }
    
    Write-Host "   Ultima esecuzione: $($taskInfo.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss')) ($tempoTestoDa)" -ForegroundColor Gray
    
    # Risultato ultima esecuzione
    if ($taskInfo.LastTaskResult -eq 0) {
        Write-Host "   Risultato:  Successo (0x0)" -ForegroundColor Green
    } else {
        Write-Host "   Risultato:  Errore (0x$($taskInfo.LastTaskResult.ToString('X')))" -ForegroundColor Red
    }
} else {
    Write-Host "   Ultima esecuzione: Mai eseguito" -ForegroundColor Yellow
}

# Prossima esecuzione
if ($taskInfo.NextRunTime) {
    $tempoMancante = $taskInfo.NextRunTime - (Get-Date)
    $tempoTestoTra = if ($tempoMancante.Days -gt 0) {
        "$($tempoMancante.Days) giorni"
    } elseif ($tempoMancante.Hours -gt 0) {
        "$($tempoMancante.Hours) ore"
    } elseif ($tempoMancante.Minutes -gt 0) {
        "$($tempoMancante.Minutes) minuti"
    } else {
        "meno di 1 minuto"
    }
    
    Write-Host "   Prossima esecuzione: $($taskInfo.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss')) (tra $tempoTestoTra)" -ForegroundColor Gray
}

# Numero di esecuzioni
Write-Host "   Totale esecuzioni: $($taskInfo.NumberOfMissedRuns)" -ForegroundColor Gray

Write-Host ""

# ═══════════════════════════════════════════════════════════════════
# LOG ULTIMA ESECUZIONE
# ═══════════════════════════════════════════════════════════════════

$logFile = Join-Path $LOG_PATH "backup_$(Get-Date -Format 'yyyy-MM-dd').log"

if (Test-Path $logFile) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║            LOG ULTIMA ESECUZIONE                    ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow
    
    $logContent = Get-Content $logFile -Tail 50
    
    # Cerca messaggi importanti nel log
    $errori = $logContent | Select-String -Pattern "|ERROR|ERRORE|Failed" -SimpleMatch
    $successi = $logContent | Select-String -Pattern "|SUCCESS|COMPLETATO|Backup completato" -SimpleMatch
    
    if ($errori) {
        Write-Host "  Trovati $($errori.Count) errori nel log:" -ForegroundColor Red
        foreach ($errore in $errori | Select-Object -First 5) {
            Write-Host "   $errore" -ForegroundColor Red
        }
        Write-Host ""
    }
    
    if ($successi) {
        Write-Host " Trovati $($successi.Count) messaggi di successo" -ForegroundColor Green
        Write-Host ""
    }
    
    Write-Host " Ultime 20 righe del log:" -ForegroundColor Cyan
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
    $logContent | Select-Object -Last 20 | ForEach-Object {
        $color = if ($_ -match "|ERROR|ERRORE") {
            "Red"
        } elseif ($_ -match "|SUCCESS") {
            "Green"
        } elseif ($_ -match "|WARNING") {
            "Yellow"
        } else {
            "White"
        }
        Write-Host $_ -ForegroundColor $color
    }
    Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
    Write-Host ""
    Write-Host " Log completo: $logFile" -ForegroundColor Gray
} else {
    Write-Host " Nessun log trovato per oggi." -ForegroundColor Yellow
    Write-Host "   Il task potrebbe non essere ancora stato eseguito oggi." -ForegroundColor Gray
}

# ═══════════════════════════════════════════════════════════════════
# BACKUP RECENTI
# ═══════════════════════════════════════════════════════════════════

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║            BACKUP RECENTI (Locale)                  ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

$backupPath = "C:\CheckMK-Backups"
if (Test-Path $backupPath) {
    $backups = Get-ChildItem -Path $backupPath -Directory | 
        Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$' } |
        Sort-Object CreationTime -Descending |
        Select-Object -First 10
    
    if ($backups) {
        Write-Host "Ultimi 10 backup:" -ForegroundColor Yellow
        foreach ($backup in $backups) {
            $size = (Get-ChildItem -Path $backup.FullName -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
            $age = (Get-Date) - $backup.CreationTime
            $ageText = if ($age.Days -gt 0) { "$($age.Days)g" } 
                      elseif ($age.Hours -gt 0) { "$($age.Hours)h" }
                      else { "$($age.Minutes)m" }
            
            Write-Host "    $($backup.Name) - $([math]::Round($size, 2)) MB - $ageText fa" -ForegroundColor Gray
        }
        
        $totalSize = ($backups | ForEach-Object { 
            (Get-ChildItem -Path $_.FullName -Recurse | Measure-Object -Property Length -Sum).Sum 
        } | Measure-Object -Sum).Sum / 1GB
        
        Write-Host "`n   Totale spazio occupato: $([math]::Round($totalSize, 2)) GB" -ForegroundColor Cyan
    } else {
        Write-Host "Nessun backup trovato." -ForegroundColor Yellow
    }
} else {
    Write-Host "Cartella backup non trovata: $backupPath" -ForegroundColor Red
}

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║                   REPORT COMPLETATO                  ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

Write-Host " Comandi rapidi:" -ForegroundColor Yellow
Write-Host "   Esegui backup ora:        Start-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "   Disabilita backup:        Disable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "   Riabilita backup:         Enable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "   Ricontrolla stato:        .\check-backup-status.ps1" -ForegroundColor White
Write-Host ""
