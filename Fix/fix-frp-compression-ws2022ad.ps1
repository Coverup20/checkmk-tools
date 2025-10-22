#
# Script per disabilitare la compressione FRP su WS2022AD
# Da eseguire su WS2022AD tramite PowerShell Remoting
#

$ErrorActionPreference = "Stop"

Write-Host "=== FIX FRP COMPRESSION su WS2022AD ===" -ForegroundColor Cyan
Write-Host ""

# 1. Backup del file di configurazione
Write-Host "1. Backup configurazione FRP..." -ForegroundColor Yellow
$frpcConfig = "C:\frp\frpc.toml"
$backupConfig = "C:\frp\frpc.toml.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

if (Test-Path $frpcConfig) {
    Copy-Item $frpcConfig $backupConfig -Force
    Write-Host "   Backup creato: $backupConfig" -ForegroundColor Green
} else {
    Write-Host "   ERRORE: File $frpcConfig non trovato!" -ForegroundColor Red
    exit 1
}

# 2. Leggi configurazione attuale
Write-Host ""
Write-Host "2. Configurazione attuale:" -ForegroundColor Yellow
Get-Content $frpcConfig
Write-Host ""

# 3. Aggiungi o modifica la sezione transport
Write-Host "3. Modifica configurazione per disabilitare compressione..." -ForegroundColor Yellow

$config = Get-Content $frpcConfig -Raw

# Verifica se esiste già la sezione [transport]
if ($config -match '\[transport\]') {
    Write-Host "   Sezione [transport] già presente" -ForegroundColor Yellow
    
    # Verifica se useCompression è già presente
    if ($config -match 'useCompression\s*=') {
        # Sostituisci il valore esistente
        $config = $config -replace 'useCompression\s*=\s*(true|false)', 'useCompression = false'
        Write-Host "   Modificato useCompression = false" -ForegroundColor Green
    } else {
        # Aggiungi useCompression nella sezione transport
        $config = $config -replace '(\[transport\])', "`$1`r`nuseCompression = false"
        Write-Host "   Aggiunto useCompression = false" -ForegroundColor Green
    }
} else {
    # Aggiungi l'intera sezione transport alla fine
    $config += "`r`n`r`n[transport]`r`nuseCompression = false`r`n"
    Write-Host "   Aggiunta sezione [transport] con useCompression = false" -ForegroundColor Green
}

# 4. Salva la configurazione modificata
$config | Set-Content $frpcConfig -Force -NoNewline
Write-Host ""
Write-Host "4. Nuova configurazione salvata:" -ForegroundColor Yellow
Get-Content $frpcConfig
Write-Host ""

# 5. Riavvia il servizio FRP
Write-Host "5. Riavvio servizio FRPC..." -ForegroundColor Yellow

$service = Get-Service -Name "frpc" -ErrorAction SilentlyContinue
if ($service) {
    Restart-Service -Name "frpc" -Force
    Start-Sleep -Seconds 3
    
    $status = Get-Service -Name "frpc"
    if ($status.Status -eq "Running") {
        Write-Host "   ✓ Servizio FRPC riavviato con successo" -ForegroundColor Green
    } else {
        Write-Host "   ✗ ERRORE: Servizio FRPC non è running!" -ForegroundColor Red
        Write-Host "   Status: $($status.Status)" -ForegroundColor Red
    }
} else {
    Write-Host "   ✗ Servizio 'frpc' non trovato!" -ForegroundColor Red
    Write-Host "   Prova con NSSM:" -ForegroundColor Yellow
    Write-Host "   nssm stop frpc" -ForegroundColor White
    Write-Host "   nssm start frpc" -ForegroundColor White
}

Write-Host ""
Write-Host "=== VERIFICA CONNESSIONE ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Attendi 10 secondi per stabilizzare la connessione..."
Start-Sleep -Seconds 10

# 6. Test connessione agent locale
Write-Host ""
Write-Host "6. Test agent locale (porta 6556):" -ForegroundColor Yellow
try {
    $tcpClient = New-Object System.Net.Sockets.TcpClient
    $tcpClient.Connect("127.0.0.1", 6556)
    $stream = $tcpClient.GetStream()
    $reader = New-Object System.IO.StreamReader($stream)
    
    $output = ""
    $timeout = [DateTime]::Now.AddSeconds(5)
    while ([DateTime]::Now -lt $timeout -and $output.Length -lt 500) {
        if ($stream.DataAvailable) {
            $output += $reader.ReadLine() + "`r`n"
        }
        Start-Sleep -Milliseconds 100
    }
    
    $tcpClient.Close()
    
    if ($output.Length -gt 0) {
        Write-Host "   ✓ Agent risponde localmente" -ForegroundColor Green
        Write-Host "   Prime righe:" -ForegroundColor Gray
        $output.Split("`r`n") | Select-Object -First 5 | ForEach-Object { Write-Host "     $_" }
    } else {
        Write-Host "   ✗ Agent non risponde" -ForegroundColor Red
    }
} catch {
    Write-Host "   ✗ Errore connessione: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== PROSSIMI PASSI ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Sul server CheckMK, esegui:" -ForegroundColor Yellow
Write-Host "  su - monitoring -c 'cmk -d WS2022AD'" -ForegroundColor White
Write-Host ""
Write-Host "Dovresti vedere l'output dell'agent invece di 'Empty output'" -ForegroundColor Green
Write-Host ""
