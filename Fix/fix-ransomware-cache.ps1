<#
.SYNOPSIS
    Script per pulire la cache e verificare lo script ransomware su WS2022AD
.DESCRIPTION
    Esegui questo script direttamente su WS2022AD per:
    - Rimuovere cache obsolete
    - Verificare script installato
    - Riavviare servizio CheckMK
    - Testare output
.NOTES
    Eseguire come Administrator
#>

Write-Host "=== FIX RANSOMWARE CACHE - WS2022AD ===" -ForegroundColor Cyan
Write-Host "Data: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n" -ForegroundColor Gray

# 1. Verifica e rimuovi cache utente corrente
Write-Host "[1/6] Verifica cache utente corrente..." -ForegroundColor Yellow
$userCache = "$env:TEMP\ransomware_script_cache.ps1"
if (Test-Path $userCache) {
    $age = (Get-Date) - (Get-Item $userCache).LastWriteTime
    Write-Host "  ✓ Cache trovata: età $([int]$age.TotalMinutes) minuti" -ForegroundColor Cyan
    Remove-Item $userCache -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Cache rimossa!" -ForegroundColor Green
} else {
    Write-Host "  ✓ Nessuna cache utente" -ForegroundColor Gray
}

# 2. Verifica e rimuovi cache SYSTEM
Write-Host "`n[2/6] Verifica cache SYSTEM (CheckMK Agent)..." -ForegroundColor Yellow
$systemCache = "C:\Windows\System32\config\systemprofile\AppData\Local\Temp\ransomware_script_cache.ps1"
if (Test-Path $systemCache) {
    $age = (Get-Date) - (Get-Item $systemCache).LastWriteTime
    Write-Host "  ✓ Cache SYSTEM trovata: età $([int]$age.TotalMinutes) minuti" -ForegroundColor Cyan
    Remove-Item $systemCache -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ Cache SYSTEM rimossa!" -ForegroundColor Green
} else {
    Write-Host "  ✓ Nessuna cache SYSTEM" -ForegroundColor Gray
}

# 3. Verifica script installato
Write-Host "`n[3/6] Verifica script installati..." -ForegroundColor Yellow
$scripts = Get-ChildItem "C:\ProgramData\checkmk\agent\local\" | Where-Object { $_.Name -like "*ransomware*" }
if ($scripts) {
    foreach ($script in $scripts) {
        Write-Host "  ✓ $($script.Name) - $($script.Length) bytes - $($script.LastWriteTime)" -ForegroundColor Cyan
    }
} else {
    Write-Host "  ✗ NESSUNO SCRIPT RANSOMWARE TROVATO!" -ForegroundColor Red
}

# 4. Verifica file di configurazione
Write-Host "`n[4/6] Verifica configurazione..." -ForegroundColor Yellow
$configFile = "C:\ProgramData\checkmk\agent\local\ransomware_config.json"
if (Test-Path $configFile) {
    $config = Get-Content $configFile -Raw
    Write-Host "  ✓ Config trovato: $((Get-Item $configFile).Length) bytes" -ForegroundColor Green
    Write-Host "  Contenuto:" -ForegroundColor Gray
    Write-Host $config -ForegroundColor White
} else {
    Write-Host "  ✗ CONFIG NON TROVATO!" -ForegroundColor Red
}

# 5. Riavvia servizio CheckMK
Write-Host "`n[5/6] Riavvio servizio CheckMK..." -ForegroundColor Yellow
try {
    Restart-Service CheckMkService -Force -ErrorAction Stop
    Start-Sleep -Seconds 3
    $service = Get-Service CheckMkService
    Write-Host "  ✓ Servizio: $($service.Status)" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Errore riavvio servizio: $_" -ForegroundColor Red
}

# 6. Test output CheckMK Agent
Write-Host "`n[6/6] Test output CheckMK Agent..." -ForegroundColor Yellow
try {
    $agentPath = "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe"
    if (Test-Path $agentPath) {
        Write-Host "  Esecuzione agent..." -ForegroundColor Cyan
        $output = & $agentPath test 2>&1 | Select-String -Pattern "Ransomware" -Context 0,3
        if ($output) {
            Write-Host "  ✓ Output trovato:" -ForegroundColor Green
            $output | ForEach-Object { Write-Host "    $_" -ForegroundColor White }
        } else {
            Write-Host "  ✗ NESSUN OUTPUT RANSOMWARE!" -ForegroundColor Red
        }
    } else {
        Write-Host "  ✗ Agent non trovato in: $agentPath" -ForegroundColor Red
    }
} catch {
    Write-Host "  ✗ Errore test agent: $_" -ForegroundColor Red
}

Write-Host "`n=== COMPLETATO ===" -ForegroundColor Green
Write-Host "Prossimi passi:" -ForegroundColor Yellow
Write-Host "1. Se vedi errori sopra, correggili" -ForegroundColor White
Write-Host "2. Attendi 60 secondi per il prossimo check" -ForegroundColor White
Write-Host "3. Verifica su CheckMK Web GUI" -ForegroundColor White
Write-Host "`nPremi un tasto per chiudere..." -ForegroundColor Gray
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
