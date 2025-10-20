
# Backup & Sync Multi-Repo con Notifica Telegram
$ErrorActionPreference = "Continue"
$snapshotName = "checkmk-tools-$(Get-Date -Format 'yyyy-MM-dd-HH-mm')"
$backupDir = "C:\Backup\CheckMK"
$retention = 7
$telegramToken = "8264716040:AAHPjzYJz7h8pV9hzjaf45-Mrv2gf8tMXmQ"
$telegramChatId = "381764604"

function Send-Telegram {
    param([string]$msg)
    $body = @{ chat_id = $telegramChatId; text = $msg }
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$telegramToken/sendMessage" -Method Post -Body $body | Out-Null
    } catch {}
}

Write-Host "=== BACKUP & SYNC MULTI-REPO ===" -ForegroundColor Cyan
Write-Host "Snapshot: $snapshotName" -ForegroundColor Yellow

# 1. Commit & Push su GitHub
git add -A
git commit -m "Backup $snapshotName"
git push origin main
$githubOK = $?

# 2. Push su GitLab Mirror
git push gitlab main
$gitlabOK = $?

# 3. Backup Locale
if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir | Out-Null }
Copy-Item -Path . -Destination "$backupDir\$snapshotName" -Recurse -Force
$localOK = $?

# 4. Retention: mantieni solo gli ultimi $retention backup
$snapshots = Get-ChildItem $backupDir | Sort-Object Name -Descending
if ($snapshots.Count -gt $retention) {
    $toRemove = $snapshots | Select-Object -Skip $retention
    foreach ($r in $toRemove) { Remove-Item $r.FullName -Recurse -Force }
}

# 5. Notifica Telegram
$msg = "✅ [BACKUP-COMPLETE] Backup completo sincronizzato!`n`nRISULTATI:`n"
if ($githubOK) { $msg += "✅ GitHub (principale) - OK`n" } else { $msg += "❌ GitHub - ERRORE`n" }
if ($localOK)  { $msg += "✅ Backup Locale - OK`n" } else { $msg += "❌ Backup Locale - ERRORE`n" }
if ($gitlabOK) { $msg += "✅ GitLab Mirror - OK`n" } else { $msg += "❌ GitLab Mirror - ERRORE`n" }
$msg += "`n📦 Snapshot: $snapshotName`nRetention: $($snapshots.Count) totali, $($toRemove.Count) rimossi`n"
$msg += "🖴 Backup dir: $backupDir`n"
$msg += "`n📋 Stato: " + ($(if ($githubOK -and $localOK -and $gitlabOK) { "Perfetto ✅" } else { "Problemi ❌" }))
$msg += "`n� $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Send-Telegram $msg

Write-Host "=== BACKUP & SYNC COMPLETATO ===" -ForegroundColor Green