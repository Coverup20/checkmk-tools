# Setup Scheduled Task per Backup Automatico
# Esegue backup-sync-complete.ps1 ogni ora

$ErrorActionPreference = "Stop"

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       SETUP BACKUP AUTOMATICO REPOSITORY            ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

$TASK_NAME = "CheckMK-Backup-Auto"
$SCRIPT_PATH = Join-Path $PSScriptRoot "backup-sync-complete.ps1"
$LOG_PATH = "C:\CheckMK-Backups\logs"

# Verifica che lo script esista
if (-not (Test-Path $SCRIPT_PATH)) {
    Write-Host " Script non trovato: $SCRIPT_PATH" -ForegroundColor Red
    exit 1
}

# ═══════════════════════════════════════════════════════════════════
# SCELTA FREQUENZA BACKUP
# ═══════════════════════════════════════════════════════════════════

Write-Host "  Scegli la frequenza di backup automatico:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1) Ogni 15 minuti   (molto frequente)" -ForegroundColor White
Write-Host "  2) Ogni 30 minuti   (frequente)" -ForegroundColor White
Write-Host "  3) Ogni ora         (consigliato)" -ForegroundColor Green
Write-Host "  4) Ogni 2 ore       (moderato)" -ForegroundColor White
Write-Host "  5) Ogni 4 ore       (leggero)" -ForegroundColor White
Write-Host "  6) Ogni 6 ore       (minimo)" -ForegroundColor White
Write-Host ""

do {
    $scelta = Read-Host "Inserisci il numero della tua scelta (1-6)"
    $sceltaValida = $scelta -match '^[1-6]$'
    if (-not $sceltaValida) {
        Write-Host " Scelta non valida. Inserisci un numero da 1 a 6." -ForegroundColor Red
    }
} while (-not $sceltaValida)

# Imposta la frequenza in base alla scelta
$frequenzaMinuti = switch ($scelta) {
    "1" { 15 }
    "2" { 30 }
    "3" { 60 }
    "4" { 120 }
    "5" { 240 }
    "6" { 360 }
}

$frequenzaOre = $frequenzaMinuti / 60
if ($frequenzaOre -ge 1) {
    if ($frequenzaOre -eq 1) {
        $frequenzaTesto = "ogni ora"
    } else {
        $frequenzaTesto = "ogni $frequenzaOre ore"
    }
} else {
    $frequenzaTesto = "ogni $frequenzaMinuti minuti"
}

Write-Host "`n Frequenza selezionata: $frequenzaTesto" -ForegroundColor Green
Write-Host ""

# Crea cartella log se non esiste
if (-not (Test-Path $LOG_PATH)) {
    New-Item -ItemType Directory -Path $LOG_PATH -Force | Out-Null
    Write-Host " Creata cartella log: $LOG_PATH" -ForegroundColor Green
}

Write-Host " Configurazione Scheduled Task..." -ForegroundColor Yellow

# Rimuovi task esistente se presente
$existingTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "  → Rimozione task esistente..." -ForegroundColor Gray
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
}

# Configura action con logging migliorato e modalità unattended
$logFile = "`"$LOG_PATH\backup_`$(Get-Date -Format 'yyyy-MM-dd').log`""
$pwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwshPath) { $pwshPath = "C:\Program Files\PowerShell\7\pwsh.exe" }
$action = New-ScheduledTaskAction `
    -Execute $pwshPath `
    -Argument "-NoProfile -ExecutionPolicy Bypass -Command `"& '$SCRIPT_PATH' -Unattended *>&1 | Tee-Object -FilePath $logFile -Append`""

# Configura trigger con la frequenza scelta
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes $frequenzaMinuti)

# Configura settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable:$false `
    -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew `
    -WakeToRun:$false

# Configura principal con S4U (funziona anche senza login interattivo)
# IMPORTANTE: S4U permette esecuzione anche con utente disconnesso/lock screen
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

# Registra task
try {
    Register-ScheduledTask `
        -TaskName $TASK_NAME `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Backup automatico $frequenzaTesto del repository checkmk-tools (funziona anche con utente disconnesso)" `
        -Force | Out-Null
    
    Write-Host " Scheduled Task creato con successo!" -ForegroundColor Green
} catch {
    Write-Host " Errore nella creazione del task: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║               CONFIGURAZIONE COMPLETATA              ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

Write-Host " Dettagli configurazione:" -ForegroundColor Cyan
Write-Host "   Task Name: $TASK_NAME" -ForegroundColor Gray
Write-Host "   Script: $SCRIPT_PATH" -ForegroundColor Gray
Write-Host "   Frequenza: $frequenzaTesto" -ForegroundColor Yellow
Write-Host "   Log: $LOG_PATH" -ForegroundColor Gray
Write-Host "   User: $env:USERDOMAIN\$env:USERNAME" -ForegroundColor Gray

Write-Host "`n Comandi utili:" -ForegroundColor Yellow
Write-Host "   Verifica task:" -ForegroundColor Gray
Write-Host "     Get-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Avvia manualmente:" -ForegroundColor Gray
Write-Host "     Start-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Disabilita temporaneamente:" -ForegroundColor Gray
Write-Host "     Disable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Riabilita:" -ForegroundColor Gray
Write-Host "     Enable-ScheduledTask -TaskName '$TASK_NAME'" -ForegroundColor White
Write-Host "`n   Rimuovi task:" -ForegroundColor Gray
Write-Host "     Unregister-ScheduledTask -TaskName '$TASK_NAME' -Confirm:`$false" -ForegroundColor White
Write-Host "`n   Visualizza log ultima esecuzione:" -ForegroundColor Gray
Write-Host "     Get-Content '$LOG_PATH\backup_$(Get-Date -Format 'yyyy-MM-dd').log'" -ForegroundColor White

Write-Host "`n Il backup automatico partirà tra 2 minuti e poi $frequenzaTesto!" -ForegroundColor Green
Write-Host ""
