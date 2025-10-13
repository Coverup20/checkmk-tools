#!/usr/bin/env pwsh
# Quick Backup Script - Versione con GitLab

Write-Host "🔄 Quick Backup..." -ForegroundColor Cyan

# Push su GitHub
Write-Host "� GitHub..." -NoNewline
git push origin main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
} else { 
    Write-Host " ❌" -ForegroundColor Red 
}

# Push su GitLab
Write-Host "🦊 GitLab..." -NoNewline
git push gitlab main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
} else { 
    Write-Host " ❌" -ForegroundColor Red 
}

# Push su backup locale
Write-Host "💾 Locale..." -NoNewline  
git push backup main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
} else { 
    Write-Host " ❌" -ForegroundColor Red 
}

# 🆕 BACKUP RETENTION SYSTEM
Write-Host "📦 Retention..." -NoNewline
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
    
    if ($todayBackups.Count -gt 5) {
        $toDelete = $todayBackups | Select-Object -Skip 5
        foreach ($backup in $toDelete) {
            Remove-Item $backup.FullName -Recurse -Force
        }
    }
    
    Write-Host " ✅" -ForegroundColor Green
} catch {
    Write-Host " ⚠️" -ForegroundColor Yellow
}

Write-Host "🎉 Done!" -ForegroundColor Green