#!/usr/bin/env pwsh
# southbridge.ps1 - Tunnel doppio verso srv-monitoring-us via checkmk-vps-02
# Lato srv-monitoring-us (da tmate): ssh -R 1443:127.0.0.1:443 -N root@monitor01.nethlab.it &
# Questo script fa il lato PC: local forward localhost:1443 -> checkmk-vps-02:1443

Write-Host "=== SOUTHBRIDGE ===" -ForegroundColor Cyan
Write-Host "Tunnel: localhost:1443 -> checkmk-vps-02:1443 -> srv-monitoring-us:443" -ForegroundColor Gray

# 1. Verifica che il tunnel reverse sia attivo su checkmk-vps-02
Write-Host "`n[1/3] Verifico tunnel reverse su checkmk-vps-02..." -ForegroundColor Yellow
$check = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :1443'" 2>&1
if (-not $check) {
    Write-Host "     ATTENZIONE: porta 1443 NON attiva su checkmk-vps-02!" -ForegroundColor Red
    Write-Host "     Su srv-monitoring-us lancia:" -ForegroundColor Yellow
    Write-Host "       ssh -R 1443:127.0.0.1:443 -N root@monitor01.nethlab.it &" -ForegroundColor White
    Write-Host "     In attesa (Ctrl+C per uscire)..." -ForegroundColor Gray
    $timeout = 120  # secondi massimi di attesa
    $elapsed = 0
    while ($elapsed -lt $timeout) {
        Start-Sleep -Seconds 5
        $elapsed += 5
        $check = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :1443'" 2>&1
        if ($check) { break }
        Write-Host "     ...attendo ($elapsed/$timeout sec)" -ForegroundColor DarkGray
    }
    if (-not $check) {
        Write-Host "     Timeout ($timeout sec). Tunnel reverse non attivato. Esco." -ForegroundColor Red
        exit 1
    }
}
Write-Host "     OK - porta 1443 attiva su checkmk-vps-02" -ForegroundColor Green

# 2. Libera solo il job del local forward porta 1443 (NON toccare i socket ControlMaster WSL)
Write-Host "`n[2/3] Libero localhost:1443 se occupato..." -ForegroundColor Yellow
$existing = netstat -an | findstr "127.0.0.1:1443"
if ($existing) {
    # Prima uccidi il processo ssh in WSL che tiene la porta
    wsl -d kali-linux bash -c "pkill -f 'ssh -L 1443' 2>/dev/null; true" | Out-Null
    Start-Sleep -Seconds 1
    # Poi rimuovi i job PowerShell senza aspettare che si fermino
    Get-Job | ForEach-Object {
        try { $_.StopJob() } catch {}
        try { Remove-Job -Job $_ -Force } catch {}
    }
    Write-Host "     Job precedenti rimossi" -ForegroundColor Gray
} else {
    Write-Host "     Porta libera" -ForegroundColor Gray
}

# 3. Avvia local forward in background via WSL (ControlMaster - nessuna passphrase)
Write-Host "`n[3/3] Avvio local forward localhost:1443 -> checkmk-vps-02..." -ForegroundColor Yellow
$job = Start-Job -ScriptBlock { wsl -d kali-linux bash -c "ssh -L 1443:127.0.0.1:1443 -N checkmk-vps-02" }
Start-Sleep -Seconds 2

$listen = netstat -an | findstr "127.0.0.1:1443"
if ($listen) {
    Write-Host "     OK - localhost:1443 in ascolto (Job ID: $($job.Id))" -ForegroundColor Green
    Write-Host "`n>>> Apri: https://localhost:1443 <<<" -ForegroundColor Cyan
    Write-Host "    Per chiudere il tunnel: Stop-Job $($job.Id); Remove-Job $($job.Id)" -ForegroundColor Gray
} else {
    Write-Host "     ERRORE: localhost:1443 non in ascolto. Controlla il ControlMaster WSL." -ForegroundColor Red
    Write-Host "     Lancia prima: wsl -d kali-linux ssh checkmk-vps-02  (inserisci passphrase)" -ForegroundColor Yellow
    exit 1
}
