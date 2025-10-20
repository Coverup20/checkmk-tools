#!/usr/bin/env pwsh
# Quick Backup Script - Versione con GitLab + Notifiche Telegram

Write-Host "🔄 Quick Backup..." -ForegroundColor Cyan

# Push su GitHub
Write-Host "� GitHub..." -NoNewline
git push origin main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
    $results += "🐙 GitHub: ✅ OK"
} else { 
    Write-Host " ❌" -ForegroundColor Red 
    $results += "🐙 GitHub: ❌ FAILED"
}

# Push su GitLab
Write-Host "🦊 GitLab..." -NoNewline
git push gitlab main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
    $results += "🦊 GitLab: ✅ OK"
} else { 
    Write-Host " ❌" -ForegroundColor Red 
    $results += "🦊 GitLab: ❌ FAILED"
}

# Push su backup locale
Write-Host "💾 Locale..." -NoNewline  
git push backup main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
    $results += "💾 Locale: ✅ OK"
} else { 
    Write-Host " ❌" -ForegroundColor Red 
    $results += "💾 Locale: ❌ FAILED"
}

# 🆕 BACKUP RETENTION SYSTEM
Write-Host "📦 Retention..." -NoNewline
$retentionResult = ""
try {
    $timestamp = Get-Date -Format "yyyy-MM-dd-HH-mm"
    $backupDir = "C:\Backup\CheckMK"
    $currentBackup = "$backupDir\checkmk-tools-$timestamp"
    
    # Crea directory se non esiste
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    
    # Copia snapshot corrente
    $sourceDir = (Get-Location).Path
    Copy-Item -Path $sourceDir -Destination $currentBackup -Recurse -Force
    
    # Cleanup retention (mantieni max 5 backup del giorno corrente)
    $today = Get-Date -Format "yyyy-MM-dd"
    $todayBackups = Get-ChildItem $backupDir -Directory | Where-Object { 
        $_.Name -match "checkmk-tools-$today-\d{2}-\d{2}" 
    } | Sort-Object Name -Descending
    
    $deleted = 0
    if ($todayBackups.Count -gt 5) {
        $toDelete = $todayBackups | Select-Object -Skip 5
        foreach ($backup in $toDelete) {
            Remove-Item $backup.FullName -Recurse -Force
            $deleted++
        }
    }
    
    $retentionResult = "📦 Snapshot: checkmk-tools-$timestamp`n🗃️ Retention: $($todayBackups.Count) totali, $deleted rimossi"
    Write-Host " ✅" -ForegroundColor Green
} catch {
    Write-Host " ⚠️" -ForegroundColor Yellow
    $retentionResult = "⚠️ Retention: Errore durante la gestione"
}

Write-Host "🎉 Done!" -ForegroundColor Green

# === NOTIFICA TELEGRAM FINALE ===
$errors = $results | Where-Object { $_ -like "*❌*" }
$successes = $results | Where-Object { $_ -like "*✅*" }

if ($errors.Count -eq 0) {
    # Tutto OK
    $message = @"
Backup completato con successo!

📊 RISULTATI:
$($results -join "`n")

$retentionResult
"@
    Send-BackupNotification -Message $message -Type "success"
} else {
    # Ci sono errori
    $message = @"
Backup completato con errori!

❌ ERRORI:
$($errors -join "`n")

$(if($successes) {"✅ SUCCESSI:`n$($successes -join "`n")"} else {""})

$retentionResult

🔧 Verificare la connessione ai repository
"@
    Send-BackupNotification -Message $message -Type "error"
}