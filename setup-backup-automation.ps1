#!/usr/bin/env pwsh
# Setup Task Scheduler per Backup Automatico CheckMK
# Configura backup-sync-complete.ps1 alle 01:00 ogni giorno

Write-Host "🕐 Setup Task Scheduler - Backup CheckMK..." -ForegroundColor Cyan

# Verifica permessi Admin
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "❌ Errore: Questo script richiede privilegi di amministratore!" -ForegroundColor Red
    Write-Host "💡 Fai clic destro su PowerShell e seleziona 'Esegui come amministratore'" -ForegroundColor Yellow
    exit 1
}

# Configurazione task
$TaskName = "CheckMK-Backup-Complete-Daily"
$ScriptPath = "$PSScriptRoot\backup-sync-complete.ps1"
$WorkingDir = $PSScriptRoot

# Verifica che lo script esista
if (-not (Test-Path $ScriptPath)) {
    Write-Host "❌ Errore: Script $ScriptPath non trovato!" -ForegroundColor Red
    exit 1
}

Write-Host "📋 Configurazione:" -ForegroundColor Yellow
Write-Host "   📄 Script: $ScriptPath" -ForegroundColor Gray
Write-Host "   📁 Directory: $WorkingDir" -ForegroundColor Gray
Write-Host "   🕐 Orario: 01:00 ogni giorno" -ForegroundColor Gray
Write-Host "   👤 Utente: $env:USERNAME" -ForegroundColor Gray

# Rimuovi task esistente se presente
try {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existingTask) {
        Write-Host "🗑️  Rimozione task esistente..." -NoNewline
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host " ✅" -ForegroundColor Green
    }
} catch {
    # Task non esistente, continua
}

# Crea azione task
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`"" -WorkingDirectory $WorkingDir

# Crea trigger (ogni giorno alle 01:00)
$Trigger = New-ScheduledTaskTrigger -Daily -At "01:00"

# Configurazione task
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)

# Crea principale (current user)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Write-Host "🔧 Creazione task schedulato..." -NoNewline

try {
    # Registra il task
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description "Backup CheckMK automatico giornaliero alle 01:00"
    
    Write-Host " ✅" -ForegroundColor Green
    
    # Verifica che sia stato creato
    $createdTask = Get-ScheduledTask -TaskName $TaskName
    Write-Host "✅ Task creato con successo!" -ForegroundColor Green
    Write-Host "   📅 Prossima esecuzione: $($createdTask.Triggers[0].StartBoundary)" -ForegroundColor Gray
    
    # Test opzionale
    Write-Host "`n🧪 Vuoi testare il task ora? [y/N]: " -NoNewline -ForegroundColor Yellow
    $test = Read-Host
    
    if ($test -eq "y" -or $test -eq "Y") {
        Write-Host "🔄 Esecuzione test del task..." -ForegroundColor Cyan
        Start-ScheduledTask -TaskName $TaskName
        
        Start-Sleep 5
        
        $taskInfo = Get-ScheduledTask -TaskName $TaskName
        Write-Host "📊 Stato task: $($taskInfo.State)" -ForegroundColor $(if($taskInfo.State -eq "Ready") { "Green" } else { "Yellow" })
        
        if ($taskInfo.State -eq "Ready") {
            Write-Host "✅ Test completato! Controlla se hai ricevuto la notifica Telegram." -ForegroundColor Green
        }
    }
    
} catch {
    Write-Host " ❌" -ForegroundColor Red
    Write-Host "❌ Errore nella creazione del task: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`n🎉 Setup completato!" -ForegroundColor Green
Write-Host "📱 Il backup completo partirà automaticamente alle 01:00 ogni giorno" -ForegroundColor Cyan
Write-Host "🔧 Per gestire il task: Pannello di controllo → Utilità di pianificazione → $TaskName" -ForegroundColor Gray

# Mostra summary
Write-Host "`n📋 SUMMARY:" -ForegroundColor Yellow
Write-Host "   🕐 Backup automatico: ATTIVO alle 01:00" -ForegroundColor Green
Write-Host "   📱 Notifiche Telegram: ATTIVE (solo repository essenziali)" -ForegroundColor Green  
Write-Host "   🗂️ Task Scheduler: $TaskName" -ForegroundColor Gray
Write-Host "   💾 Backup manuali: Sempre disponibili con quick-backup.ps1" -ForegroundColor Gray