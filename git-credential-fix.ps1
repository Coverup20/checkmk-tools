#!/usr/bin/env pwsh
# Fix per Windows Credential Manager - Risolve problemi di autenticazione Git

Write-Host "🔧 Git Credential Manager - Diagnostica e Fix" -ForegroundColor Cyan

Write-Host "`n📊 STATO ATTUALE:" -ForegroundColor Yellow

# 1. Verifica configurazione Git
Write-Host "`n🔍 Configurazione Git Credential Helper:" -ForegroundColor White
git config --list | findstr credential | ForEach-Object { Write-Host "   $_" -ForegroundColor Gray }

# 2. Test remote
Write-Host "`n🌐 Test Remote GitLab:" -ForegroundColor White
$testResult = git ls-remote gitlab HEAD 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "   ✅ Connessione OK" -ForegroundColor Green
} else {
    Write-Host "   ❌ Errore: $testResult" -ForegroundColor Red
}

# 3. Mostra credential manager
Write-Host "`n💾 Windows Credential Manager:" -ForegroundColor White
try {
    $gitCreds = cmdkey /list 2>$null | Select-String "gitlab" -Context 1
    if ($gitCreds) {
        $gitCreds | ForEach-Object { Write-Host "   $_" -ForegroundColor Gray }
    } else {
        Write-Host "   Nessuna credenziale GitLab trovata" -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "   Errore lettura credenziali" -ForegroundColor DarkRed
}

Write-Host "`n🛠️  AZIONI DISPONIBILI:" -ForegroundColor Cyan
Write-Host "1. 🔄 Reset credenziali GitLab" -ForegroundColor White
Write-Host "2. 🧪 Test push forzato" -ForegroundColor White
Write-Host "3. 📋 Mostra configurazione Git completa" -ForegroundColor White
Write-Host "4. ❌ Esci" -ForegroundColor White

$choice = Read-Host "`nScegli [1-4]"

switch ($choice) {
    "1" {
        Write-Host "`n🔄 Reset credenziali GitLab..." -ForegroundColor Yellow
        
        # Rimuovi dal credential manager
        Write-Host "   Rimozione credenziali esistenti..." -ForegroundColor Gray
        cmdkey /delete:git:https://gitlab.com 2>$null
        
        # Reset configurazione locale Git per GitLab
        Write-Host "   Reset configurazione Git..." -ForegroundColor Gray
        git config --unset credential.https://gitlab.com.username 2>$null
        
        # Test nuovo push (forzerà autenticazione)
        Write-Host "   Test nuovo push (forzerà autenticazione)..." -ForegroundColor Gray
        git push gitlab main
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Credenziali reset e salvate con successo!" -ForegroundColor Green
        } else {
            Write-Host "❌ Errore nel reset credenziali" -ForegroundColor Red
        }
    }
    
    "2" {
        Write-Host "`n🧪 Test push forzato..." -ForegroundColor Yellow
        git push gitlab main --verbose
    }
    
    "3" {
        Write-Host "`n📋 Configurazione Git completa:" -ForegroundColor Yellow
        git config --list | Sort-Object | ForEach-Object { Write-Host "   $_" -ForegroundColor Gray }
    }
    
    "4" {
        Write-Host "`n👋 Uscita..." -ForegroundColor Green
        exit 0
    }
    
    default {
        Write-Host "`n❌ Scelta non valida" -ForegroundColor Red
    }
}

Write-Host "`n💡 NOTA: Se si apre una finestra di autenticazione:" -ForegroundColor Cyan
Write-Host "   • Username: il tuo username GitLab" -ForegroundColor Gray
Write-Host "   • Password: glpat-dAIcIuWnTiY1Wj-iV76IzG86MQp1OmlmN3BrCw.01.1203ybcco" -ForegroundColor Gray
Write-Host "   • Spunta sempre 'Ricorda credenziali'" -ForegroundColor Gray