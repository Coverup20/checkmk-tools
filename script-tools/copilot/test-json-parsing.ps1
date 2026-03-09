# Test debug - Verifica cosa legge effettivamente lo script dal JSON

$configPath = "C:\ProgramData\checkmk\agent\local\ransomware_config.json"

Write-Host "=== TEST LETTURA JSON ===" -ForegroundColor Cyan
Write-Host ""

# Mostra contenuto grezzo
Write-Host "1. Contenuto grezzo file:" -ForegroundColor Yellow
Get-Content $configPath
Write-Host ""

# Leggi come fa lo script
Write-Host "2. Dopo ConvertFrom-Json:" -ForegroundColor Yellow
$config = Get-Content $configPath -Raw | ConvertFrom-Json
Write-Host "SharePaths type: $($config.SharePaths.GetType().FullName)"
Write-Host "SharePaths count: $($config.SharePaths.Count)"
Write-Host "SharePaths[0]: [$($config.SharePaths[0])]"
Write-Host "SharePaths[0] length: $($config.SharePaths[0].Length)"
Write-Host ""

# Test accesso
Write-Host "3. Test accesso share:" -ForegroundColor Yellow
foreach ($share in $config.SharePaths) {
    Write-Host "  Testing: [$share]" -ForegroundColor Cyan
    if (Test-Path $share) {
        Write-Host "  OK - Accessibile!" -ForegroundColor Green
        Get-ChildItem $share | Select-Object -First 3 | Format-Table Name, Length
    } else {
        Write-Host "  ERRORE - NON accessibile!" -ForegroundColor Red
    }
}
Write-Host ""

# Prova con path corretto
Write-Host "4. Test con path esplicito:" -ForegroundColor Yellow
$testPath = "\\WS2022AD\test00"
Write-Host "  Testing: [$testPath]" -ForegroundColor Cyan
if (Test-Path $testPath) {
    Write-Host "  OK - Accessibile!" -ForegroundColor Green
    Get-ChildItem $testPath | Select-Object -First 3 | Format-Table Name, Length
} else {
    Write-Host "  ERRORE - NON accessibile!" -ForegroundColor Red
}

Write-Host ""
Write-Host "Premi un tasto..." -ForegroundColor Gray
$null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
