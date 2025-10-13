#!/usr/bin/env pwsh
# Setup Remote Aggiuntivi per Backup Multi-Piattaforma
# Configura GitLab, Codeberg e SourceForge come remote di backup

Write-Host "🔧 Setup Remote Aggiuntivi per CheckMK Tools" -ForegroundColor Cyan
Write-Host "=" * 50 -ForegroundColor Gray

# Verifica che siamo nella directory giusta
if (-not (Test-Path ".git")) {
    Write-Host "❌ Errore: Non sono nella directory del repository Git!" -ForegroundColor Red
    exit 1
}

# Mostra remote attuali
Write-Host "`n📡 Remote attualmente configurati:" -ForegroundColor Yellow
git remote -v

# Funzione per aggiungere remote
function Add-GitRemote {
    param($name, $url, $description)
    
    $existing = git remote | Where-Object { $_ -eq $name }
    if ($existing) {
        Write-Host "⚠️  Remote '$name' già esistente, lo sovrascrivo..." -ForegroundColor Yellow
        git remote remove $name
    }
    
    Write-Host "➕ Aggiungendo $description..." -ForegroundColor Green
    git remote add $name $url
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ $description configurato con successo!" -ForegroundColor Green
        return $true
    } else {
        Write-Host "❌ Errore nella configurazione di $description" -ForegroundColor Red
        return $false
    }
}

# Configurazione GitLab
Write-Host "`n🦊 CONFIGURAZIONE GITLAB" -ForegroundColor Cyan
Write-Host "1. Vai su https://gitlab.com" -ForegroundColor Gray
Write-Host "2. Crea un nuovo progetto o importa da GitHub" -ForegroundColor Gray
Write-Host "3. Copia l'URL del repository" -ForegroundColor Gray

$gitlabUrl = Read-Host "`nInserisci l'URL completo del repository GitLab (o ENTER per saltare)"
if ($gitlabUrl -and $gitlabUrl -ne "") {
    Add-GitRemote "gitlab" $gitlabUrl "GitLab Mirror"
} else {
    Write-Host "⏭️  GitLab saltato" -ForegroundColor DarkYellow
}

# Configurazione Codeberg
Write-Host "`n🌿 CONFIGURAZIONE CODEBERG" -ForegroundColor Cyan
Write-Host "1. Vai su https://codeberg.org" -ForegroundColor Gray
Write-Host "2. Registrati (gratuito e open source)" -ForegroundColor Gray
Write-Host "3. Crea un nuovo repository 'checkmk-tools'" -ForegroundColor Gray
Write-Host "4. Copia l'URL del repository" -ForegroundColor Gray

$codebergUrl = Read-Host "`nInserisci l'URL completo del repository Codeberg (o ENTER per saltare)"
if ($codebergUrl -and $codebergUrl -ne "") {
    Add-GitRemote "codeberg" $codebergUrl "Codeberg Backup"
} else {
    Write-Host "⏭️  Codeberg saltato" -ForegroundColor DarkYellow
}

# Configurazione SourceForge
Write-Host "`n🔧 CONFIGURAZIONE SOURCEFORGE" -ForegroundColor Cyan
Write-Host "1. Vai su https://sourceforge.net" -ForegroundColor Gray
Write-Host "2. Crea un nuovo progetto 'checkmk-tools'" -ForegroundColor Gray
Write-Host "3. Abilita Git nel progetto" -ForegroundColor Gray
Write-Host "4. L'URL sarà: git://git.code.sf.net/p/PROGETTO/code" -ForegroundColor Gray

$sourceforgeUrl = Read-Host "`nInserisci l'URL completo del repository SourceForge (o ENTER per saltare)"
if ($sourceforgeUrl -and $sourceforgeUrl -ne "") {
    Add-GitRemote "sourceforge" $sourceforgeUrl "SourceForge Backup"
} else {
    Write-Host "⏭️  SourceForge saltato" -ForegroundColor DarkYellow
}

# Riepilogo finale
Write-Host "`n📊 RIEPILOGO CONFIGURAZIONE" -ForegroundColor Cyan
Write-Host "Remote configurati:" -ForegroundColor Green
git remote -v | ForEach-Object {
    if ($_ -match "\(push\)") {
        $parts = $_ -split "`t"
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
        
        Write-Host "  $emoji $name`: $url" -ForegroundColor Gray
    }
}

Write-Host "`n🎉 Configurazione completata!" -ForegroundColor Green
Write-Host "💡 Ora puoi usare 'backup-sync-complete.ps1' per sincronizzare su tutte le piattaforme" -ForegroundColor Cyan