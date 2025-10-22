# Fix definitivo configurazione ransomware_config.json
# Crea JSON manualmente per evitare escape automatico

Write-Host "=== FIX RANSOMWARE CONFIG - VERSIONE DEFINITIVA ===" -ForegroundColor Cyan

$configPath = "C:\ProgramData\checkmk\agent\local\ransomware_config.json"

# Backup
Copy-Item $configPath "$configPath.old" -Force -ErrorAction SilentlyContinue
Write-Host "Backup creato" -ForegroundColor Green

# JSON corretto scritto manualmente (2 backslash, non 4!)
$jsonContent = @'
{
    "SharePaths": ["\\WS2022AD\test00"],
    "EnableCanaryFiles": true,
    "MaxFilesPerSecond": 10,
    "AlertThreshold": 50,
    "SuspiciousExtensions": [".encrypted", ".locked", ".crypto", ".crypt"]
}
'@

# Salva il file
Set-Content -Path $configPath -Value $jsonContent -Encoding UTF8 -Force

Write-Host ""
Write-Host "Nuovo contenuto salvato:" -ForegroundColor Yellow
Get-Content $configPath
Write-Host ""

# Test immediato
Write-Host "Test script (attendi 5 secondi)..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
$output = & "C:\ProgramData\checkmk\agent\local\rcheck_ransomware_activity.ps1" 2>&1
Write-Host ""
Write-Host "Output script:" -ForegroundColor Cyan
$output | Select-String "Ransomware" | ForEach-Object { Write-Host $_ -ForegroundColor White }

Write-Host ""
if ($output -match "0 Ransomware") {
    Write-Host "=== SUCCESS! Script funziona correttamente ===" -ForegroundColor Green
} else {
    Write-Host "=== ATTENZIONE: Verifica l'output sopra ===" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Premi un tasto per chiudere..." -ForegroundColor Gray
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
