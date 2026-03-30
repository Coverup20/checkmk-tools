#!/usr/bin/env pwsh
# southbridge.ps1 - Tunnel doppio verso srv-monitoring-us via checkmk-vps-02
# Lato srv-monitoring-us (da tmate):
#   ssh -R 1443:127.0.0.1:443 -N root@monitor01.nethlab.it &
#   ssh -R 2222:127.0.0.1:22  -N root@monitor01.nethlab.it &
# Questo script fa il lato PC:
#   local forward localhost:1443 -> checkmk-vps-02:1443  (HTTPS)
#   local forward localhost:2222 -> checkmk-vps-02:2222  (SSH)

Write-Host "=== SOUTHBRIDGE ===" -ForegroundColor Cyan
Write-Host "Tunnel HTTPS: localhost:1443 -> checkmk-vps-02:1443 -> srv-monitoring-us:443" -ForegroundColor Gray
Write-Host "Tunnel SSH:   localhost:2222 -> checkmk-vps-02:2222 -> srv-monitoring-us:22" -ForegroundColor Gray

# 1. Verifica tunnel reverse su checkmk-vps-02 (1443 + 2222)
Write-Host "`n[1/3] Verifico tunnel reverse su checkmk-vps-02..." -ForegroundColor Yellow
$check1443 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :1443'" 2>&1
$check2222 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :2222'" 2>&1
if (-not $check1443 -or -not $check2222) {
    if (-not $check1443) {
        Write-Host "     ATTENZIONE: porta 1443 NON attiva su checkmk-vps-02!" -ForegroundColor Red
        Write-Host "       su srv-monitoring-us: ssh -R 1443:127.0.0.1:443 -N root@monitor01.nethlab.it &" -ForegroundColor White
    }
    if (-not $check2222) {
        Write-Host "     ATTENZIONE: porta 2222 NON attiva su checkmk-vps-02!" -ForegroundColor Red
        Write-Host "       su srv-monitoring-us: ssh -R 2222:127.0.0.1:22  -N root@monitor01.nethlab.it &" -ForegroundColor White
    }
    Write-Host "     In attesa (Ctrl+C per uscire)..." -ForegroundColor Gray
    $timeout = 120
    $elapsed = 0
    while ($elapsed -lt $timeout) {
        Start-Sleep -Seconds 5
        $elapsed += 5
        $check1443 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :1443'" 2>&1
        $check2222 = wsl -d kali-linux bash -c "ssh checkmk-vps-02 'ss -tlnp | grep :2222'" 2>&1
        if ($check1443 -and $check2222) { break }
        Write-Host "     ...attendo ($elapsed/$timeout sec)" -ForegroundColor DarkGray
    }
    if (-not $check1443 -or -not $check2222) {
        Write-Host "     Timeout ($timeout sec). Tunnel reverse non pronti. Esco." -ForegroundColor Red
        exit 1
    }
}
Write-Host "     OK - porta 1443 attiva su checkmk-vps-02" -ForegroundColor Green
Write-Host "     OK - porta 2222 attiva su checkmk-vps-02" -ForegroundColor Green

# 2. Libera porte locali 1443 e 2222 se occupate
Write-Host "`n[2/3] Libero porte locali se occupate..." -ForegroundColor Yellow
$existing1443 = netstat -an | findstr "127.0.0.1:1443"
$existing2222 = netstat -an | findstr "127.0.0.1:2222"
if ($existing1443 -or $existing2222) {
    wsl -d kali-linux bash -c "pkill -f 'ssh -L 1443' 2>/dev/null; pkill -f 'ssh -L 2222' 2>/dev/null; true" | Out-Null
    Start-Sleep -Seconds 1
    Get-Job | ForEach-Object {
        try { $_.StopJob() } catch {}
        try { Remove-Job -Job $_ -Force } catch {}
    }
    Write-Host "     Job precedenti rimossi" -ForegroundColor Gray
} else {
    Write-Host "     Porte libere" -ForegroundColor Gray
}

# 3. Avvia entrambi i local forward in background via WSL (ControlMaster - nessuna passphrase)
Write-Host "`n[3/3] Avvio local forward..." -ForegroundColor Yellow
$jobHttps = Start-Job -ScriptBlock { wsl -d kali-linux bash -c "ssh -L 1443:127.0.0.1:1443 -N checkmk-vps-02" }
$jobSsh   = Start-Job -ScriptBlock { wsl -d kali-linux bash -c "ssh -L 2222:127.0.0.1:2222 -N checkmk-vps-02" }
Start-Sleep -Seconds 2

$listen1443 = netstat -an | findstr "127.0.0.1:1443"
$listen2222 = netstat -an | findstr "127.0.0.1:2222"

if ($listen1443) {
    Write-Host "     OK - localhost:1443 in ascolto (Job ID: $($jobHttps.Id))" -ForegroundColor Green
} else {
    Write-Host "     ERRORE: localhost:1443 non in ascolto!" -ForegroundColor Red
}
if ($listen2222) {
    Write-Host "     OK - localhost:2222 in ascolto (Job ID: $($jobSsh.Id))" -ForegroundColor Green
} else {
    Write-Host "     ERRORE: localhost:2222 non in ascolto!" -ForegroundColor Red
}

if (-not $listen1443 -or -not $listen2222) {
    Write-Host "     Controlla il ControlMaster WSL: wsl -d kali-linux ssh checkmk-vps-02" -ForegroundColor Yellow
    exit 1
}

Write-Host "`n>>> HTTPS: https://localhost:1443 <<<" -ForegroundColor Cyan
Write-Host ">>> SSH:   ssh -p 2222 root@localhost <<<" -ForegroundColor Cyan
Write-Host "`n    Per chiudere: Stop-Job $($jobHttps.Id),$($jobSsh.Id); Remove-Job $($jobHttps.Id),$($jobSsh.Id)" -ForegroundColor Gray
