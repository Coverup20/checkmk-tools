# Fix configurazione ransomware_config.json su WS2022AD
# Corregge il path con troppi backslash

Write-Host "=== FIX RANSOMWARE CONFIG ===" -ForegroundColor Cyan

$configPath = "C:\ProgramData\checkmk\agent\local\ransomware_config.json"

# Backup del file originale
$backupPath = "$configPath.backup"
Copy-Item $configPath $backupPath -Force
Write-Host "Backup creato: $backupPath" -ForegroundColor Green

# Crea configurazione corretta
$config = @{
    SharePaths = @("\\WS2022AD\test00")
    EnableCanaryFiles = $true
    MaxFilesPerSecond = 10
    AlertThreshold = 50
    SuspiciousExtensions = @(".encrypted", ".locked", ".crypto", ".crypt")
}

# Converte in JSON e salva
$json = $config | ConvertTo-Json -Depth 10
Set-Content -Path $configPath -Value $json -Encoding UTF8 -Force

Write-Host ""
Write-Host "Nuovo contenuto:" -ForegroundColor Yellow
Get-Content $configPath
Write-Host ""

# Test immediato
Write-Host "Test script..." -ForegroundColor Yellow
& "C:\ProgramData\checkmk\agent\local\rcheck_ransomware_activity.ps1"

Write-Host ""
Write-Host "=== COMPLETATO ===" -ForegroundColor Green
Write-Host "Se vedi '0 Ransomware_Detection' sopra, il problema e' risolto!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Premi un tasto per chiudere..." -ForegroundColor Gray
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
