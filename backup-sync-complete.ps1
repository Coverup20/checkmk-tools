#!/usr/bin/env pwsh
# Script di Backup Multi-Piattaforma Completo
# Sincronizza su GitHub, GitLab, Codeberg e backup locale

Write-Host "🔄 Avvio sincronizzazione backup completa..." -ForegroundColor Cyan
Write-Host "📅 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray

$ErrorActionPreference = "Continue"
$success = 0
$total = 0

# Configurazione remote (aggiorna con i tuoi URL)
$remotes = @(
    @{ Name = "origin"; Description = "GitHub (principale)"; Required = $true },
    @{ Name = "backup"; Description = "Backup Locale"; Required = $true },
    @{ Name = "gitlab"; Description = "GitLab Mirror"; Required = $false },
    @{ Name = "codeberg"; Description = "Codeberg Backup"; Required = $false },
    @{ Name = "sourceforge"; Description = "SourceForge Backup"; Required = $false }
)

# Funzione per test e push
function Push-Remote {
    param($remoteName, $remoteDescription, $isRequired = $false)
    
    $script:total++
    Write-Host "`n📡 Sincronizzazione con $remoteDescription..." -ForegroundColor Yellow
    
    try {
        # Verifica che il remote esista
        $remoteExists = git remote | Where-Object { $_ -eq $remoteName }
        if (-not $remoteExists) {
            Write-Host "⚠️  $remoteDescription - Remote non configurato" -ForegroundColor $(if ($isRequired) { "Red" } else { "DarkYellow" })
            if ($isRequired) {
                Write-Host "❌ $remoteDescription - RICHIESTO ma mancante!" -ForegroundColor Red
            }
            return
        }

        # Test connessione
        $testResult = git ls-remote $remoteName HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {
            # Push
            $pushResult = git push $remoteName main 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✅ $remoteDescription - OK" -ForegroundColor Green
                $script:success++
            } else {
                if ($pushResult -match "up.to.date") {
                    Write-Host "✅ $remoteDescription - Up to date" -ForegroundColor Green
                    $script:success++
                } else {
                    Write-Host "❌ $remoteDescription - Errore push: $pushResult" -ForegroundColor Red
                }
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
    $response = Read-Host "`nVuoi continuare comunque? [y/N]"
    if ($response -notmatch "^[yY]") {
        Write-Host "❌ Backup annullato dall'utente" -ForegroundColor Red
        exit 1
    }
}

# Esegui backup su tutti i remote configurati
foreach ($remote in $remotes) {
    Push-Remote $remote.Name $remote.Description $remote.Required
}

# Riepilogo
Write-Host "`n📊 RIEPILOGO BACKUP" -ForegroundColor Cyan
Write-Host "✅ Successi: $success/$total" -ForegroundColor $(if ($success -eq $total) { "Green" } elseif ($success -gt 0) { "Yellow" } else { "Red" })

if ($success -eq $total) {
    Write-Host "🎉 Backup completato con successo su tutte le piattaforme!" -ForegroundColor Green
} elseif ($success -gt 0) {
    Write-Host "⚠️  Backup parziale - Alcuni remote non disponibili" -ForegroundColor Yellow
} else {
    Write-Host "❌ Backup fallito - Nessun remote raggiungibile" -ForegroundColor Red
}

# Lista repository
Write-Host "`n📍 Repository configurati:" -ForegroundColor Gray
$configuredRemotes = git remote -v | Where-Object { $_ -match "\(push\)" }
foreach ($line in $configuredRemotes) {
    $parts = $line -split "`t"
    $name = $parts[0]
    $url = $parts[1] -replace " \(push\)", ""
    
    $emoji = switch ($name) {
        "origin" { "🐙" }
        "gitlab" { "🦊" }
        "codeberg" { "🌿" }
        "sourceforge" { "🔧" }
        "backup" { "💾" }
        default { "📡" }
    }
    
    Write-Host "   $emoji $name`: $url" -ForegroundColor Gray
}

# Suggerimenti per remote mancanti
$allRemotes = git remote
$missingRemotes = $remotes | Where-Object { $_.Name -notin $allRemotes -and -not $_.Required }
if ($missingRemotes) {
    Write-Host "`n💡 Remote opzionali non configurati:" -ForegroundColor DarkCyan
    foreach ($missing in $missingRemotes) {
        Write-Host "   • $($missing.Description)" -ForegroundColor DarkGray
    }
    Write-Host "   Usa setup-additional-remotes.ps1 per configurarli" -ForegroundColor DarkGray
}