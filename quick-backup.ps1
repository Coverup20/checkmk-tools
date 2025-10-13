#!/usr/bin/env pwsh
# Quick Backup Script - Versione semplificata

Write-Host "🔄 Quick Backup..." -ForegroundColor Cyan

# Push su GitHub
Write-Host "📡 GitHub..." -NoNewline
git push origin main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
} else { 
    Write-Host " ❌" -ForegroundColor Red 
}

# Push su backup locale
Write-Host "💾 Locale..." -NoNewline  
git push backup main *>$null
if ($LASTEXITCODE -eq 0) { 
    Write-Host " ✅" -ForegroundColor Green 
} else { 
    Write-Host " ❌" -ForegroundColor Red 
}

Write-Host "🎉 Done!" -ForegroundColor Green