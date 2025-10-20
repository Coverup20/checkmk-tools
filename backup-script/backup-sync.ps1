#!/usr/bin/env pwsh
# Script di Backup Multi-Remote per CheckMK Tools
# Sincronizza su GitHub (origin) e Backup locale

Write-Host "🔄 Avvio sincronizzazione backup..." -ForegroundColor Cyan
Write-Host "📅 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray

$ErrorActionPreference = "Continue"
$success = 0
$total = 0

# Funzione per test e push
function Push-Remote {
    param($remoteName, $remoteDescription)
    
    $total++
    Write-Host "`n📡 Sincronizzazione con $remoteDescription..." -ForegroundColor Yellow
    
    try {
        # Test connessione
        git ls-remote $remoteName HEAD *>$null
        if ($LASTEXITCODE -eq 0) {
            # Push
            git push $remoteName main
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ $remoteDescription - OK" -ForegroundColor Green
                $script:success++
            } else {
                Write-Host "❌ $remoteDescription - Errore push" -ForegroundColor Red
            }
        } else {
            Write-Host "❌ $remoteDescription - Errore connessione" -ForegroundColor Red
        }
    } catch {
        Write-Host "❌ $remoteDescription - Errore: $_" -ForegroundColor Red
    }
}

# Verifica che siamo nella directory giusta
if (-not (Test-Path ".git")) {
    Write-Host "❌ Errore: Non sono nella directory del repository Git!" -ForegroundColor Red
    exit 1
}

# Verifica stato repository
$status = git status --porcelain
if ($status) {
    Write-Host "⚠️  Attenzione: Ci sono modifiche non committate:" -ForegroundColor Yellow
    git status --short
    Write-Host "`n🔄 Procedo comunque con il backup..." -ForegroundColor Cyan
}

# Esegui backup
Push-Remote "origin" "GitHub (origin)"
Push-Remote "backup" "Backup Locale"

# TODO: Aggiungi GitLab quando configurato
# Push-Remote "gitlab" "GitLab Mirror"

# Riepilogo
Write-Host "`n📊 RIEPILOGO BACKUP" -ForegroundColor Cyan
Write-Host "✅ Successi: $success/$total" -ForegroundColor $(if ($success -eq $total) { "Green" } else { "Yellow" })

if ($success -eq $total) {
    Write-Host "🎉 Backup completato con successo!" -ForegroundColor Green
} else {
    Write-Host "⚠️  Backup parziale - Controlla i log sopra" -ForegroundColor Yellow
}

Write-Host "`n📍 Repository salvati in:" -ForegroundColor Gray
Write-Host "   • GitHub: https://github.com/Coverup20/checkmk-tools" -ForegroundColor Gray
Write-Host "   • Locale: c:\Users\Marzio\Desktop\CheckMK-Backup.git" -ForegroundColor Gray