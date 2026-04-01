# Fix Python 3.6 compatibility - rimuove reconfigure() non supportato

$scriptDir = "C:\Users\Marzio\Desktop\CheckMK\checkmk-tools\script-check-ns7\remote"
$files = Get-ChildItem "$scriptDir\*.py" -File

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw
    
    # Rimuove le righe reconfigure() che non funzionano su Python 3.6
    $newContent = $content -replace "if sys\.stdout\.encoding != 'utf-8':\r?\n\s+sys\.stdout\.reconfigure\(encoding='utf-8', errors='replace'\)\r?\n", ""
    $newContent = $newContent -replace "if sys\.stderr\.encoding != 'utf-8':\r?\n\s+sys\.stderr\.reconfigure\(encoding='utf-8', errors='replace'\)\r?\n", ""
    
    if ($content -ne $newContent) {
        Set-Content -Path $file.FullName -Value $newContent -NoNewline
        Write-Host "Fixed: $($file.Name)" -ForegroundColor Yellow
    }
}

Write-Host "`n Completato: Fix compatibilità Python 3.6" -ForegroundColor Green
Write-Host "  os.environ['PYTHONIOENCODING'] sufficiente per Python 3.6" -ForegroundColor Cyan
