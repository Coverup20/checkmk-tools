#!/usr/bin/env pwsh
# Test Telegram Notification per Backup System
# Usa le API trovate negli script CheckMK esistenti

Write-Host "📱 Test Notifica Telegram..." -ForegroundColor Cyan

# === CONFIG da script CheckMK ===
$TOKEN = $env:TELEGRAM_TOKEN
$CHAT_ID = $env:TELEGRAM_CHAT_ID
if (-not $TOKEN -or -not $CHAT_ID) {
    Write-Host "❌ Errore: TELEGRAM_TOKEN o TELEGRAM_CHAT_ID non impostati come variabili d'ambiente." -ForegroundColor Red
    exit 1
}
$API_URL = "https://api.telegram.org/bot$TOKEN/sendMessage"

# Funzione per inviare messaggio
function Send-TelegramMessage {
    param(
        [string]$Message,
        [string]$Type = "info"
    )
    
    # Emoji per tipo messaggio
    $emoji = switch ($Type) {
        "success" { "✅" }
        "error" { "❌" }  
        "warning" { "⚠️" }
        "info" { "📱" }
        default { "📱" }
    }
    
    # Prefisso per riconoscere i messaggi backup
    $fullMessage = "$emoji [BACKUP-TEST] $Message`n`n⏰ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    
    try {
        $body = @{
            chat_id = $CHAT_ID
            text = $fullMessage
            parse_mode = "HTML"
        }
        
        Write-Host "   📤 Invio messaggio..." -NoNewline
        $response = Invoke-RestMethod -Uri $API_URL -Method Post -Body $body
        
        if ($response.ok) {
            Write-Host " ✅" -ForegroundColor Green
            return $true
        } else {
            Write-Host " ❌" -ForegroundColor Red
            Write-Host "   Errore: $($response.description)" -ForegroundColor Red
            return $false
        }
    }
    catch {
        Write-Host " ❌" -ForegroundColor Red
        Write-Host "   Exception: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# === TEST MESSAGES ===

Write-Host "`n1️⃣ Test messaggio di successo..."
$success = Send-TelegramMessage -Message "Test notifica backup completato con successo!" -Type "success"

Start-Sleep 2

Write-Host "`n2️⃣ Test messaggio di errore..."
$error = Send-TelegramMessage -Message "Test notifica backup con errori rilevati!" -Type "error"

Start-Sleep 2

Write-Host "`n3️⃣ Test messaggio completo..."
$complexMessage = @"
Backup System Test

📊 RISULTATI:
🐙 GitHub: ✅ OK
🦊 GitLab: ✅ OK  
💾 Locale: ✅ OK

📦 Snapshot: checkmk-tools-test
🗃️ Retention: 4 totali, 0 rimossi
"@

$complex = Send-TelegramMessage -Message $complexMessage -Type "info"

# === RISULTATI ===
Write-Host "`n📋 RISULTATI TEST:" -ForegroundColor Yellow
Write-Host "   ✅ Successo: $(if($success){'OK'}else{'FAILED'})"
Write-Host "   ❌ Errore: $(if($error){'OK'}else{'FAILED'})"  
Write-Host "   📊 Complesso: $(if($complex){'OK'}else{'FAILED'})"

if ($success -and $error -and $complex) {
    Write-Host "`n🎉 TUTTI I TEST PASSATI! Telegram funziona correttamente." -ForegroundColor Green
    Write-Host "💡 Ora posso integrare le notifiche nei script backup." -ForegroundColor Cyan
} else {
    Write-Host "`n⚠️ ALCUNI TEST FALLITI! Verifica configurazione Telegram." -ForegroundColor Yellow
}