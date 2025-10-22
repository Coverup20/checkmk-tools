#!/usr/bin/env pwsh
# Script per salvare permanentemente le credenziali GitLab in Windows Credential Manager
# Evita di dover reinserire il token ogni volta

Write-Host "🔐 Configurazione Credenziali GitLab" -ForegroundColor Cyan
Write-Host "=" * 40 -ForegroundColor Gray

Write-Host "`n💡 Questo script forza il salvataggio del token GitLab" -ForegroundColor Yellow
Write-Host "   nelle credenziali di Windows per evitare richieste future." -ForegroundColor Gray

# Test connessione GitLab
Write-Host "`n🔍 Test connessione GitLab..." -ForegroundColor Cyan
$testResult = git ls-remote gitlab HEAD 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ GitLab già configurato correttamente!" -ForegroundColor Green
    Write-Host "   Le credenziali sono salvate in Windows Credential Manager" -ForegroundColor Gray
} else {
    Write-Host "⚠️  GitLab richiede autenticazione" -ForegroundColor Yellow
    Write-Host "   Output: $testResult" -ForegroundColor DarkGray
    
    Write-Host "`n🔧 Forzatura salvataggio credenziali..." -ForegroundColor Cyan
    Write-Host "   (Potrebbe aprire una finestra di autenticazione)" -ForegroundColor Yellow
    
    # Forza l'autenticazione e il salvataggio
    git push gitlab main 2>&1 | Out-Host
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Credenziali salvate con successo!" -ForegroundColor Green
    } else {
        Write-Host "❌ Errore nel salvataggio credenziali" -ForegroundColor Red
    }
}

# Mostra credenziali salvate (senza il token)
Write-Host "`n📋 Credenziali Git salvate in Windows:" -ForegroundColor Cyan
try {
    $gitCredentials = cmdkey /list | Select-String "git:" -A 1 -B 1
    if ($gitCredentials) {
        $gitCredentials | ForEach-Object { Write-Host "   $_" -ForegroundColor Gray }
    } else {
        Write-Host "   Nessuna credenziale Git trovata" -ForegroundColor DarkGray
    }
} catch {
    Write-Host "   Non riesco a leggere le credenziali" -ForegroundColor DarkGray
}

Write-Host "`n💡 SUGGERIMENTI:" -ForegroundColor Cyan
Write-Host "   • Se si apre una finestra di autenticazione, inserisci:" -ForegroundColor Gray
Write-Host "     Username: il tuo username GitLab" -ForegroundColor Gray
Write-Host "     Password: il token glpat-xxxx (non la tua password GitLab)" -ForegroundColor Gray
Write-Host "   • Spunta 'Ricorda credenziali' se appare l'opzione" -ForegroundColor Gray
Write-Host "   • Le credenziali sono salvate in: Pannello di Controllo → Credential Manager" -ForegroundColor Gray

Write-Host "`n🎉 Configurazione completata!" -ForegroundColor Green