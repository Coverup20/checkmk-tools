# ===================================================================
# 🔄 INTEGRAZIONE con deploy-vps-secure.ps1
# ===================================================================
# Quick launcher che usa la configurazione esistente del deploy-vps-secure.ps1
# per avviare direttamente il testing di mail_realip_hybrid
# ===================================================================

Write-Host "🔄 QUICK LAUNCHER - mail_realip_hybrid Testing" -ForegroundColor Cyan
Write-Host "Integrazione con deploy-vps-secure.ps1 esistente" -ForegroundColor Gray

# Verifica se esiste configurazione deploy-vps-secure.ps1
$existingScript = "deploy-vps-secure.ps1" 
if (-not (Test-Path $existingScript)) {
    Write-Host "❌ Script $existingScript non trovato nella directory corrente" -ForegroundColor Red
    Write-Host "💡 Suggerimento: copia deploy-vps-secure.ps1 qui o usa test-mail-realip-hybrid.ps1 standalone" -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Trovato $existingScript" -ForegroundColor Green

# Cerca configurazioni VPS nel file esistente
try {
    $scriptContent = Get-Content $existingScript -Raw
    
    # Estrai configurazioni di esempio dal script esistente
    if ($scriptContent -match 'VPS.*IP.*=.*"([^"]+)"') {
        $defaultVpsIP = $matches[1]
        Write-Host "📍 IP VPS rilevato: $defaultVpsIP" -ForegroundColor Cyan
    }
    
    if ($scriptContent -match 'SSH.*User.*=.*"([^"]+)"') {
        $defaultSshUser = $matches[1]
        Write-Host "👤 SSH User rilevato: $defaultSshUser" -ForegroundColor Cyan
    }
    
    if ($scriptContent -match 'Site.*CheckMK.*=.*"([^"]+)"') {
        $defaultSite = $matches[1]
        Write-Host "🏷️ Site CheckMK rilevato: $defaultSite" -ForegroundColor Cyan
    }
    
} catch {
    Write-Host "⚠️ Impossibile leggere configurazione esistente" -ForegroundColor Yellow
}

# Menu opzioni
Write-Host "`n🎯 OPZIONI LAUNCHER:" -ForegroundColor Yellow
Write-Host "1. 🚀 Launch test-mail-realip-hybrid.ps1 (configurazione manuale)" -ForegroundColor White
Write-Host "2. ⚡ Quick Start con configurazione esistente (se rilevata)" -ForegroundColor White
Write-Host "3. 📋 Visualizza configurazione rilevata" -ForegroundColor White
Write-Host "0. ❌ Exit" -ForegroundColor Red

do {
    $choice = Read-Host "`nScegli opzione [0-3]"
} while ($choice -notmatch '^[0-3]$')

switch ($choice) {
    "1" {
        Write-Host "`n🚀 Avvio test-mail-realip-hybrid.ps1..." -ForegroundColor Green
        & ".\test-mail-realip-hybrid.ps1"
    }
    
    "2" {
        if ($defaultVpsIP -and $defaultSshUser -and $defaultSite) {
            Write-Host "`n⚡ Quick Start con configurazione rilevata..." -ForegroundColor Green
            
            # Crea configurazione temporanea
            $quickConfig = @{
                VpsIP = $defaultVpsIP
                SshUser = $defaultSshUser
                SiteCheckMK = $defaultSite
                SshKeyPath = "C:\Users\$env:USERNAME\.ssh\id_rsa"  # Path standard
            }
            
            Write-Host "📋 Configurazione Quick Start:" -ForegroundColor Cyan
            Write-Host "   VPS: $($quickConfig.VpsIP)" -ForegroundColor White
            Write-Host "   User: $($quickConfig.SshUser)" -ForegroundColor White
            Write-Host "   Site: $($quickConfig.SiteCheckMK)" -ForegroundColor White
            Write-Host "   SSH Key: $($quickConfig.SshKeyPath)" -ForegroundColor White
            
            $confirm = Read-Host "`nUsare questa configurazione? [Y/n]"
            if ($confirm -ne 'n') {
                # Salva configurazione e avvia script
                try {
                    $quickConfig | ConvertTo-Json | Set-Content "vps_config.json"
                    Write-Host "💾 Configurazione salvata" -ForegroundColor Green
                    & ".\test-mail-realip-hybrid.ps1"
                } catch {
                    Write-Host "❌ Errore salvataggio configurazione: $_" -ForegroundColor Red
                }
            }
        } else {
            Write-Host "❌ Configurazione incompleta rilevata" -ForegroundColor Red
            Write-Host "💡 Usa opzione 1 per configurazione manuale" -ForegroundColor Yellow
        }
    }
    
    "3" {
        Write-Host "`n📋 CONFIGURAZIONE RILEVATA:" -ForegroundColor Yellow
        Write-Host "Script analizzato: $existingScript" -ForegroundColor White
        if ($defaultVpsIP) { Write-Host "   VPS IP: $defaultVpsIP" -ForegroundColor Green } else { Write-Host "   VPS IP: Non rilevato" -ForegroundColor Red }
        if ($defaultSshUser) { Write-Host "   SSH User: $defaultSshUser" -ForegroundColor Green } else { Write-Host "   SSH User: Non rilevato" -ForegroundColor Red }
        if ($defaultSite) { Write-Host "   Site CheckMK: $defaultSite" -ForegroundColor Green } else { Write-Host "   Site CheckMK: Non rilevato" -ForegroundColor Red }
        
        Write-Host "`n💡 Per configurazione completa usa opzione 1" -ForegroundColor Cyan
    }
    
    "0" {
        Write-Host "`n👋 Uscita..." -ForegroundColor Green
        exit 0
    }
}

Write-Host "`n✅ Launcher completato!" -ForegroundColor Green