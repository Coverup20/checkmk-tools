# CheckMK Email Backup Script
# Backup completo della configurazione esistente prima del deployment
# PSScriptAnalyzer disable mixed content analysis for bash sections

Write-Host "=== CHECKMK EMAIL CONFIGURATION BACKUP ===" -ForegroundColor Cyan
Write-Host "Backup configurazione esistente mail_realip_00" -ForegroundColor Gray

# Parametri di configurazione
[CmdletBinding()]
param(
    [string]$CheckMKServer = "",
    [string]$CheckMKSite = "",
    [string]$CheckMKUser = "",
    [string]$BackupDir = "backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
)

# Richiedi parametri se non forniti
if (-not $CheckMKServer) {
    $CheckMKServer = Read-Host "Server CheckMK (es: checkmk.domain.com)"
}
if (-not $CheckMKSite) {
    $CheckMKSite = Read-Host "Site CheckMK (es: monitoring)"
}
if (-not $CheckMKUser) {
    $CheckMKUser = Read-Host "Username SSH (es: cmkadmin)"
}

Write-Host "`n📁 CONFIGURAZIONE BACKUP:" -ForegroundColor Yellow
Write-Host "Server: $CheckMKServer" -ForegroundColor Cyan
Write-Host "Site: $CheckMKSite" -ForegroundColor Cyan
Write-Host "User: $CheckMKUser" -ForegroundColor Cyan
Write-Host "Backup Dir: $BackupDir" -ForegroundColor Cyan

# Crea directory di backup locale
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
    Write-Host "`n✅ Directory backup creata: $BackupDir" -ForegroundColor Green
}

Write-Host "`n🔍 INVENTARIO CONFIGURAZIONE ESISTENTE:" -ForegroundColor Yellow

# Script per inventario remoto
$inventoryScript = @"
#!/bin/bash
SITE="$CheckMKSite"
echo "=== INVENTARIO CONFIGURAZIONE CHECKMK ==="
echo "Site: \$SITE"
echo "Data: `$(date)"
echo ""

echo "📄 SCRIPT NOTIFICA ESISTENTI:"
if [ -d "/opt/omd/sites/\$SITE/local/share/check_mk/notifications/" ]; then
    ls -la /opt/omd/sites/\$SITE/local/share/check_mk/notifications/ | grep -E "(mail|email)"
else
    echo "Directory notifications non esistente"
fi
echo ""

echo "📋 CONFIGURAZIONE NOTIFICHE:"
if [ -f "/opt/omd/sites/\$SITE/etc/check_mk/conf.d/wato/notifications.mk" ]; then
    echo "File notifications.mk trovato"
    wc -l /opt/omd/sites/\$SITE/etc/check_mk/conf.d/wato/notifications.mk
else
    echo "File notifications.mk non trovato"
fi
echo ""

echo "🏷️ CONFIGURAZIONE HOST LABELS:"
find /opt/omd/sites/\$SITE/etc/check_mk/conf.d/ -name "*.mk" -exec grep -l "real_ip\|host_labels" {} \; 2>/dev/null || echo "Nessun label real_ip trovato"
echo ""

echo "📧 REGOLE EMAIL ATTIVE:"
if [ -f "/opt/omd/sites/\$SITE/etc/check_mk/conf.d/wato/notifications.mk" ]; then
    grep -E "(mail|email|smtp)" /opt/omd/sites/\$SITE/etc/check_mk/conf.d/wato/notifications.mk 2>/dev/null | head -5 || echo "Nessuna regola email trovata"
fi
echo ""

echo "=== FINE INVENTARIO ==="
"@

# Salva script inventario
$inventoryScript | Out-File -FilePath "$BackupDir\inventory_script.sh" -Encoding ASCII

Write-Host "📊 Esecuzione inventario remoto..." -ForegroundColor Cyan

# Esegui inventario su server
try {
    $scriptContent = Get-Content "$BackupDir\inventory_script.sh" -Raw
    $inventoryResult = & ssh "$CheckMKUser@$CheckMKServer" "bash -c '$scriptContent'"
    $inventoryResult | Out-File -FilePath "$BackupDir\inventory_output.txt" -Encoding UTF8
    Write-Host "✅ Inventario completato" -ForegroundColor Green
    
    # Mostra risultati
    Write-Host "`n📋 RISULTATI INVENTARIO:" -ForegroundColor Yellow
    $inventoryResult | ForEach-Object { Write-Host $_ -ForegroundColor White }
    
} catch {
    Write-Host "❌ Errore inventario: $_" -ForegroundColor Red
}

Write-Host "`n💾 BACKUP FILE CONFIGURAZIONE:" -ForegroundColor Yellow

# Lista file da fare backup
$backupFiles = @(
    @{
        "Remote" = "/opt/omd/sites/$CheckMKSite/local/share/check_mk/notifications/mail_realip_00"
        "Local" = "$BackupDir\mail_realip_00_backup"
        "Description" = "Script email originale"
    },
    @{
        "Remote" = "/opt/omd/sites/$CheckMKSite/etc/check_mk/conf.d/wato/notifications.mk"
        "Local" = "$BackupDir\notifications_backup.mk"
        "Description" = "Configurazione regole notifica"
    },
    @{
        "Remote" = "/opt/omd/sites/$CheckMKSite/etc/check_mk/conf.d/wato/hosts.mk"
        "Local" = "$BackupDir\hosts_backup.mk"
        "Description" = "Configurazione host e label"
    },
    @{
        "Remote" = "/opt/omd/sites/$CheckMKSite/var/log/notify.log"
        "Local" = "$BackupDir\notify_log_backup.log"
        "Description" = "Log notifiche (ultime 1000 righe)"
    }
)

foreach ($file in $backupFiles) {
    Write-Host "📄 Backup: $($file.Description)" -ForegroundColor Cyan
    
    try {
        if ($file.Remote -like "*/notify.log") {
            # Per il log, prendi solo le ultime righe
            & ssh "$CheckMKUser@$CheckMKServer" "tail -1000 $($file.Remote)" | Out-File -FilePath $file.Local -Encoding UTF8
        } else {
            # Per altri file, copia completo
            & scp "$CheckMKUser@$CheckMKServer`:$($file.Remote)" $file.Local
        }
        
        if (Test-Path $file.Local) {
            $size = (Get-Item $file.Local).Length
            Write-Host "  ✅ Salvato: $($file.Local) ($size bytes)" -ForegroundColor Green
        } else {
            Write-Host "  ⚠️ File non esistente o non accessibile" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  ❌ Errore backup: $_" -ForegroundColor Red
    }
}

Write-Host "`n🔍 ANALISI CONFIGURAZIONE ATTUALE:" -ForegroundColor Yellow

# Analizza script mail_realip_00 se presente
$mailScript = "$BackupDir\mail_realip_00_backup"
if (Test-Path $mailScript) {
    $content = Get-Content $mailScript -Raw
    
    Write-Host "📄 ANALISI mail_realip_00:" -ForegroundColor Cyan
    Write-Host "  Dimensione: $((Get-Item $mailScript).Length) bytes" -ForegroundColor White
    Write-Host "  Gestisce real_ip: $(($content -match 'NOTIFY_HOSTLABEL_real_ip'))" -ForegroundColor White
    Write-Host "  Disabilita grafici: $(($content -match '_no_graphs'))" -ForegroundColor White
    Write-Host "  Modifica HOSTADDRESS: $(($content -match 'HOSTADDRESS.*real_ip'))" -ForegroundColor White
}

# Analizza configurazione notifiche se presente
$notifConfig = "$BackupDir\notifications_backup.mk"
if (Test-Path $notifConfig) {
    $notifContent = Get-Content $notifConfig -Raw
    
    Write-Host "`n📋 ANALISI notifications.mk:" -ForegroundColor Cyan
    Write-Host "  Dimensione: $((Get-Item $notifConfig).Length) bytes" -ForegroundColor White
    
    # Conta regole email
    $emailRules = ($notifContent | Select-String -Pattern "mail" -AllMatches).Matches.Count
    Write-Host "  Regole email trovate: $emailRules" -ForegroundColor White
    
    # Verifica script custom
    $customScripts = ($notifContent | Select-String -Pattern "mail_realip" -AllMatches).Matches.Count
    Write-Host "  Script mail_realip: $customScripts" -ForegroundColor White
}

Write-Host "`n📋 RIEPILOGO BACKUP:" -ForegroundColor Green
Write-Host "Directory: $BackupDir" -ForegroundColor Cyan
$backupSize = (Get-ChildItem $BackupDir -Recurse | Measure-Object -Property Length -Sum).Sum
Write-Host "Dimensione totale: $backupSize bytes" -ForegroundColor Cyan

Write-Host "`nFile salvati:" -ForegroundColor White
Get-ChildItem $BackupDir | ForEach-Object {
    Write-Host "  📄 $($_.Name) ($($_.Length) bytes)" -ForegroundColor Gray
}

Write-Host "`n✅ BACKUP COMPLETATO!" -ForegroundColor Green
Write-Host "Per ripristinare in caso di problemi:" -ForegroundColor Yellow
Write-Host "scp $BackupDir\mail_realip_00_backup $CheckMKUser@$CheckMKServer`:/tmp/" -ForegroundColor Cyan
Write-Host "ssh $CheckMKUser@$CheckMKServer 'sudo cp /tmp/mail_realip_00_backup /opt/omd/sites/$CheckMKSite/local/share/check_mk/notifications/mail_realip_00'" -ForegroundColor Cyan

Write-Host "`n🚀 PROSSIMI PASSI:" -ForegroundColor Cyan
Write-Host "1. Verificare backup completato correttamente" -ForegroundColor White
Write-Host "2. Procedere con installazione mail_realip_graphs" -ForegroundColor White
Write-Host "3. Testare nuova configurazione" -ForegroundColor White
Write-Host "4. Mantenere backup per eventuale rollback" -ForegroundColor White

Write-Host "`n=== BACKUP COMPLETATO ===" -ForegroundColor Cyan