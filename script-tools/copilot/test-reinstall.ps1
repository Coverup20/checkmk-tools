# Simula input utente per test
$hostName = "NB-Marzio"
$remotePort = 6010  
$serverAddr = "monitor.nethlab.it"
$token = "conduit-reenact-talon-macarena-demotion-vaguely"

Write-Host "=== TEST REINSTALLAZIONE AUTOMATICA ===" -ForegroundColor Green
Write-Host "Hostname: $hostName"
Write-Host "Remote Port: $remotePort"
Write-Host "Server: $serverAddr"
Write-Host "Token: [NASCOSTO]"
Write-Host ""

# Carica funzioni dallo script principale
. "C:\Users\Marzio\Desktop\CheckMK\checkmk-tools\script-tools\full\install-frpc-pc.ps1" -SkipMain 2>$null

# Esegui installazione con valori predefiniti
try {
    Install-Frpc
    Write-FrpcConfig -HostName $hostName -ServerAddr $serverAddr -Token $token -RemotePort $remotePort
    Write-Host "`n✓ File configurazione creato" -ForegroundColor Green
    
    # Test esecuzione
    cd "C:\Program Files\frp"
    $proc = Start-Process ".\frpc.exe" -ArgumentList "-c",".\frpc.toml" -PassThru -NoNewWindow
    Start-Sleep -Seconds 5
    
    if($proc.HasExited) {
        Write-Host "✗ ERRORE: Processo terminato" -ForegroundColor Red
        Get-Content ".\frpc.log" -Tail 10
    } else {
        Write-Host "✓ Processo attivo (PID: $($proc.Id))" -ForegroundColor Green
        Get-Content ".\frpc.log" -Tail 5
        Stop-Process -Id $proc.Id -Force
        
        # Crea task scheduler
        Write-Host "`nCreo Task Scheduler..." -ForegroundColor Cyan
        $action = New-ScheduledTaskAction -Execute "C:\Program Files\frp\frpc.exe" -Argument ''-c "C:\Program Files\frp\frpc.toml"'' -WorkingDirectory "C:\Program Files\frp"
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        Register-ScheduledTask -TaskName "FRPC Client" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
        
        Start-ScheduledTask -TaskName "FRPC Client"
        Start-Sleep -Seconds 3
        
        Get-Process -Name frpc | Select-Object Id,ProcessName,StartTime
        Write-Host "`n✓ REINSTALLAZIONE COMPLETATA!" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ ERRORE: $($_.Exception.Message)" -ForegroundColor Red
}
