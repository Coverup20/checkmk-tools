# ...existing code...
# Script di Backup Multi-Piattaforma Completo + Notifiche Telegram
# Sincronizza su GitHub, GitLab, Codeberg, Backup Locale e Share di Rete

Write-Host "🔄 Avvio sincronizzazione backup completa..." -ForegroundColor Cyan
Write-Host "📅 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray

$ErrorActionPreference = "Continue"
$success = 0
$total = 0

# === TELEGRAM CONFIG ===
$TELEGRAM_TOKEN = "8264716040:AAHPjzYJz7h8pV9hzjaf45-Mrv2gf8tMXmQ"
$TELEGRAM_CHAT_ID = "381764604"
$TELEGRAM_ENABLED = $true  # Set to $false to disable notifications

# === NETWORK SHARE CONFIG ===
$NETWORK_SHARE = "\\192.168.10.132\usbshare"
$NETWORK_SHARE_ENABLED = $true  # Set to $false to disable network backup
$NETWORK_BACKUP_PATH = "$NETWORK_SHARE\CheckMK-Backups"

# Funzione notifica Telegram
function Send-BackupNotification {
    param(
        [string]$Message,
        [string]$Type = "info"
    )
    
    if (-not $TELEGRAM_ENABLED) { return }
    
    $emoji = ""
    $fullMessage = "[BACKUP-COMPLETE] $Message`n`n$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    
    try {
        $body = @{
            chat_id = $TELEGRAM_CHAT_ID
            text = $fullMessage
        }
        
        $null = Invoke-RestMethod -Uri "https://api.telegram.org/bot$TELEGRAM_TOKEN/sendMessage" -Method Post -Body $body -ErrorAction SilentlyContinue
    }
    catch {
        # Silent fail - backup deve continuare anche se notifica fallisce
    }
}

# Arrays per tracking risultati dettagliati
$backupResults = @()
$retentionInfo = ""

# Configurazione remote (aggiorna con i tuoi URL)
$remotes = @(
    @{ Name = "origin"; Description = "GitHub (principale)"; Required = $true },
    @{ Name = "backup"; Description = "Backup Locale"; Required = $true },
    @{ Name = "gitlab"; Description = "GitLab Mirror"; Required = $true },
    @{ Name = "codeberg"; Description = "Codeberg Backup"; Required = $false },
    @{ Name = "sourceforge"; Description = "SourceForge Backup"; Required = $false }
)

# Funzione per test e push
function Push-Remote {
    param($remoteName, $remoteDescription, $isRequired = $false)
    
    $script:total++
    Write-Host "`n📡 Sincronizzazione con $remoteDescription..." -ForegroundColor Yellow
    
    try {
        # Verifica che il remote esista
        $remoteExists = git remote | Where-Object { $_ -eq $remoteName }
        if (-not $remoteExists) {
    Write-Host "⚠️  $remoteDescription - Remote non configurato" -ForegroundColor $(if ($isRequired) { "Red" } else { "DarkYellow" })
            if ($isRequired) {
                Write-Host "❌ $remoteDescription - RICHIESTO ma mancante!" -ForegroundColor Red
                $script:backupResults += "❌ $remoteDescription - REQUIRED but missing"
            } else {
                $script:backupResults += "⚠️ $remoteDescription - Not configured (optional)"
            }
            return
        }

        # Test connessione
        $testResult = git ls-remote $remoteName HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            # Push
            $pushResult = git push $remoteName main 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ $remoteDescription - OK" -ForegroundColor Green
                $script:success++
                $script:backupResults += "✅ $remoteDescription - OK"
            } else {
                if ($pushResult -match "up.to.date") {
                    Write-Host "✅ $remoteDescription - Up to date" -ForegroundColor Green
                    $script:success++
                    $script:backupResults += "✅ $remoteDescription - Up to date"
                } else {
                    Write-Host "❌ $remoteDescription - Errore push: $pushResult" -ForegroundColor Red
                    $script:backupResults += "❌ $remoteDescription - Push failed"
                }
            }
        } else {
            Write-Host "❌ $remoteDescription - Errore connessione" -ForegroundColor Red
            $script:backupResults += "❌ $remoteDescription - Connection failed"
        }
    } catch {
    Write-Host "❌ $remoteDescription - Errore: $_" -ForegroundColor Red
    $script:backupResults += "❌ $remoteDescription - Exception: $($_.Exception.Message)"
    }
}

# Verifica che siamo nella directory giusta
if (-not (Test-Path ".git")) {
    Write-Host "❌ Errore: Non sono nella directory del repository Git!" -ForegroundColor Red
    exit 1
}

# ...continua senza controllo commit...

# Esegui backup su tutti i remote configurati
foreach ($remote in $remotes) {
    Push-Remote $remote.Name $remote.Description $remote.Required
}

# Riepilogo
Write-Host "`n📊 RIEPILOGO BACKUP" -ForegroundColor Cyan
Write-Host "✅ Successi: $success/$total" -ForegroundColor $(if ($success -eq $total) { "Green" } elseif ($success -gt 0) { "Yellow" } else { "Red" })

if ($success -eq $total) {
    Write-Host "🎉 Backup completato con successo su tutte le piattaforme!" -ForegroundColor Green
} elseif ($success -gt 0) {
    Write-Host "⚠️  Backup parziale - Alcuni remote non disponibili" -ForegroundColor Yellow
} else {
    Write-Host "❌ Backup fallito - Nessun remote raggiungibile" -ForegroundColor Red
}

# Lista repository
Write-Host "`n📍 Repository configurati:" -ForegroundColor Gray
$configuredRemotes = git remote -v | Where-Object { $_ -match "\(push\)" }
foreach ($line in $configuredRemotes) {
    $parts = $line -split "`t"
    $name = $parts[0]
    $url = $parts[1] -replace " \(push\)", ""
    
    Write-Host "   ${name}: ${url}" -ForegroundColor Gray
}

# Suggerimenti per remote mancanti
$allRemotes = git remote
$missingRemotes = $remotes | Where-Object { $_.Name -notin $allRemotes -and -not $_.Required }
if ($missingRemotes) {
    Write-Host "\nRemote opzionali non configurati:" -ForegroundColor DarkCyan
    foreach ($missing in $missingRemotes) {
        Write-Host "   - $($missing.Description)" -ForegroundColor DarkGray
    }
    Write-Host "   Usa setup-additional-remotes.ps1 per configurarli" -ForegroundColor DarkGray
}

# === NETWORK SHARE BACKUP ===
Write-Host "`n🌐 Backup su Share di Rete..." -ForegroundColor Cyan

if ($NETWORK_SHARE_ENABLED) {
    Write-Host "`n📦 Backup su share di rete" -ForegroundColor Cyan
    Write-Host "   Share: $NETWORK_SHARE" -ForegroundColor Gray
    
    # Richiesta conferma
    $confirmation = Read-Host "   Vuoi eseguire il backup su share di rete? (S/N) [S]"
    if ([string]::IsNullOrWhiteSpace($confirmation)) { $confirmation = "S" }
    
    if ($confirmation -notmatch "^[Ss]") {
        Write-Host "   ⏭️  Backup su share di rete SKIPPATO dall'utente" -ForegroundColor Yellow
        $script:backupResults += "⏭️ Share di rete - SKIPPED by user"
    } else {
    try {
        # Verifica accessibilità della share
        if (Test-Path $NETWORK_SHARE) {
            Write-Host "   ✅ Share di rete raggiungibile: $NETWORK_SHARE" -ForegroundColor Green
            
            # Crea directory di backup se non esiste
            if (-not (Test-Path $NETWORK_BACKUP_PATH)) {
                New-Item -ItemType Directory -Path $NETWORK_BACKUP_PATH -Force | Out-Null
                Write-Host "   📁 Cartella backup creata: $NETWORK_BACKUP_PATH" -ForegroundColor Gray
            }
            
            # Crea snapshot con timestamp
            $timestamp = Get-Date -Format "yyyy-MM-dd-HH-mm-ss"
            $networkBackupSnapshot = "$NETWORK_BACKUP_PATH\checkmk-tools-$timestamp"
            $sourceDir = (Get-Location).Path
            
            Write-Host "   📋 Creando snapshot: checkmk-tools-$timestamp" -ForegroundColor Gray
            
            # Copia i file (escludendo .git e file temporanei)
            $excludePatterns = @('.git', '.gitignore', '__pycache__', '*.log', 'Backup', '.tmp')
            
            Get-ChildItem -Path $sourceDir -Recurse -File | ForEach-Object {
                $shouldExclude = $false
                foreach ($pattern in $excludePatterns) {
                    if ($_.FullName -match [regex]::Escape($pattern)) {
                        $shouldExclude = $true
                        break
                    }
                }
                
                if (-not $shouldExclude) {
                    $relativePath = $_.FullName.Substring($sourceDir.Length + 1)
                    $destPath = Join-Path $networkBackupSnapshot $relativePath
                    $destDir = Split-Path $destPath
                    
                    if (-not (Test-Path $destDir)) {
                        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
                    }
                    
                    Copy-Item -Path $_.FullName -Destination $destPath -Force
                }
            }
            
            $script:backupResults += "✅ Share di rete - OK (snapshot: checkmk-tools-$timestamp)"
            Write-Host "   ✅ Snapshot completato su share di rete" -ForegroundColor Green
            
            # NETWORK SHARE RETENTION
            Write-Host "   🗂️  Retention snapshot di rete..." -ForegroundColor Gray
            
            $allNetworkBackups = Get-ChildItem $NETWORK_BACKUP_PATH -Directory | Where-Object { 
                $_.Name -match "checkmk-tools-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}" 
            } | Sort-Object Name -Descending
            
            $today = Get-Date -Format "yyyy-MM-dd"
            
            # Separa backup per data
            $todayNetworkBackups = $allNetworkBackups | Where-Object { $_.Name -match "checkmk-tools-$today-\d{2}-\d{2}-\d{2}" }
            $olderNetworkBackups = $allNetworkBackups | Where-Object { 
                $_.Name -notmatch "checkmk-tools-$today-\d{2}-\d{2}-\d{2}" 
            }
            
            $deletedNetwork = 0
            
            # Oggi: mantieni max 3
            if ($todayNetworkBackups.Count -gt 3) {
                $toDelete = $todayNetworkBackups | Select-Object -Skip 3
                foreach ($backup in $toDelete) {
                    Remove-Item $backup.FullName -Recurse -Force
                    $deletedNetwork++
                }
                Write-Host "   🗑️  Rimossi $($toDelete.Count) snapshot di oggi (mantenuti 3)" -ForegroundColor DarkYellow
            }
            
            # Più vecchi: mantieni 1 per giorno
            $olderByDateNetwork = $olderNetworkBackups | Group-Object { ($_.Name -split '-')[1..3] -join '-' }
            foreach ($dateGroup in $olderByDateNetwork) {
                if ($dateGroup.Group.Count -gt 1) {
                    $toDelete = $dateGroup.Group | Select-Object -Skip 1
                    foreach ($backup in $toDelete) {
                        Remove-Item $backup.FullName -Recurse -Force
                        $deletedNetwork++
                    }
                }
            }
            
            $remainingNetwork = (Get-ChildItem $NETWORK_BACKUP_PATH -Directory).Count
            Write-Host "   ✅ Retention share completata: $remainingNetwork snapshot totali, $deletedNetwork rimossi" -ForegroundColor Green
            
        } else {
            Write-Host "   ⚠️  Share di rete NON raggiungibile: $NETWORK_SHARE" -ForegroundColor Yellow
            Write-Host "   💡 Verifica: Network path, credenziali di accesso, stato della rete" -ForegroundColor Gray
            $script:backupResults += "⚠️ Share di rete - Non raggiungibile"
        }
    } catch {
        Write-Host "   ❌ Errore backup share di rete: $($_.Exception.Message)" -ForegroundColor Red
        $script:backupResults += "❌ Share di rete - Errore: $($_.Exception.Message)"
    }
    } # Chiusura else della conferma
} else {
    Write-Host "   ⏭️  Backup share di rete disabilitato" -ForegroundColor DarkGray
}

# 🆕 ADVANCED BACKUP RETENTION SYSTEM
Write-Host "`n📦 Sistema Retention Avanzato (Locale)..." -ForegroundColor Cyan

try {
    $timestamp = Get-Date -Format "yyyy-MM-dd-HH-mm"
    $backupDir = "C:\Users\Marzio\Desktop\Backup\CheckMK"
    $currentBackup = "$backupDir\checkmk-tools-$timestamp"
    
    # Crea directory se non esiste
    if (-not (Test-Path $backupDir)) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    }
    
    Write-Host "   📁 Creando snapshot: checkmk-tools-$timestamp" -ForegroundColor Gray
    
    # Copia snapshot corrente
    $sourceDir = (Get-Location).Path
    Copy-Item -Path $sourceDir -Destination $currentBackup -Recurse -Force
    
    # RETENTION LOGIC AVANZATA
    $allBackups = Get-ChildItem $backupDir -Directory | Where-Object { 
        $_.Name -match "checkmk-tools-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}" 
    } | Sort-Object Name -Descending
    
    $today = Get-Date -Format "yyyy-MM-dd"
    $yesterday = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
    
    # Separa backup per data
    $todayBackups = $allBackups | Where-Object { $_.Name -match "checkmk-tools-$today-\d{2}-\d{2}" }
    $yesterdayBackups = $allBackups | Where-Object { $_.Name -match "checkmk-tools-$yesterday-\d{2}-\d{2}" }
    $olderBackups = $allBackups | Where-Object { 
        $_.Name -notmatch "checkmk-tools-$today-\d{2}-\d{2}" -and 
        $_.Name -notmatch "checkmk-tools-$yesterday-\d{2}-\d{2}" 
    }
    
    $deleted = 0
    
    # Oggi: mantieni max 5
    if ($todayBackups.Count -gt 5) {
        $toDelete = $todayBackups | Select-Object -Skip 5
        foreach ($backup in $toDelete) {
            Remove-Item $backup.FullName -Recurse -Force
            $deleted++
        }
    Write-Host "   🗑️  Rimossi $($toDelete.Count) backup di oggi (mantenuti 5)" -ForegroundColor DarkYellow
    }
    
    # Ieri: mantieni max 2 (mattina/sera)
    if ($yesterdayBackups.Count -gt 2) {
        $toDelete = $yesterdayBackups | Select-Object -Skip 2
        foreach ($backup in $toDelete) {
            Remove-Item $backup.FullName -Recurse -Force
            $deleted++
        }
    Write-Host "   🗑️  Rimossi $($toDelete.Count) backup di ieri (mantenuti 2)" -ForegroundColor DarkYellow
    }
    
    # Più vecchi: mantieni 1 per giorno (raggruppa per data)
    $olderByDate = $olderBackups | Group-Object { ($_.Name -split '-')[1..3] -join '-' }
    foreach ($dateGroup in $olderByDate) {
        if ($dateGroup.Group.Count -gt 1) {
            $toDelete = $dateGroup.Group | Select-Object -Skip 1
            foreach ($backup in $toDelete) {
                Remove-Item $backup.FullName -Recurse -Force
                $deleted++
            }
            Write-Host "   🗑️  Rimossi $($toDelete.Count) backup del $($dateGroup.Name) (mantenuto 1)" -ForegroundColor DarkYellow
        }
    }
    
    $remaining = (Get-ChildItem $backupDir -Directory).Count
    Write-Host "   ✅ Retention completata: $remaining backup totali, $deleted rimossi" -ForegroundColor Green
    
    # Cattura info retention per notifica
    $script:retentionInfo = "📦 Snapshot: checkmk-tools-$timestamp`n🗃️ Retention: $remaining totali, $deleted rimossi`n📁 Backup dir: $backupDir"
    
    # Salva log retention
    $logFile = "$backupDir\retention.log"
    $logEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - Backup: $timestamp, Rimossi: $deleted, Totali: $remaining"
    Add-Content -Path $logFile -Value $logEntry
    
} catch {
    Write-Host "   ⚠️  Errore retention: $($_.Exception.Message)" -ForegroundColor Yellow
    $script:retentionInfo = "⚠️ Retention: Errore durante la gestione"
}

# === NOTIFICA TELEGRAM FINALE ===
Write-Host "`n📱 Invio notifica Telegram..." -ForegroundColor Cyan

# Filtra solo repository essenziali per notifica (rimuovi Codeberg/SourceForge)
$essentialResults = $backupResults | Where-Object { 
    $_ -notlike "*Codeberg*" -and $_ -notlike "*SourceForge*" 
}

$errors = $essentialResults | Where-Object { $_ -like "*❌*" }
$successes = $essentialResults | Where-Object { $_ -like "*✅*" }
$essentialCount = $essentialResults.Count

if ($errors.Count -eq 0) {
    # Tutto OK sui repository essenziali
    $message = @"
Backup completo sincronizzato!

📊 RISULTATI:
$($successes -join "`n")

$retentionInfo

🎯 Stato: Perfetto ✅
"@
    Send-BackupNotification -Message $message -Type "success"
} else {
    # Ci sono errori critici sui repository essenziali
    $message = @"
Backup completo con ERRORI!

❌ ERRORI CRITICI:
$($errors -join "`n")

$(if($successes) {"✅ SUCCESSI:`n$($successes -join "`n")"} else {""})

$retentionInfo

🔧 Azione richiesta: Verificare repository falliti
"@
    Send-BackupNotification -Message $message -Type "error"
}