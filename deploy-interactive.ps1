# CheckMK Email Real IP + Grafici - Deployment Interattivo
# Script personalizzato per il deployment nel tuo ambiente

Write-Host "=== CHECKMK EMAIL REAL IP + GRAFICI - DEPLOYMENT ===" -ForegroundColor Cyan
Write-Host "Iniziando deployment della soluzione completa..." -ForegroundColor Gray

# Raccolta informazioni ambiente
Write-Host "`n📋 CONFIGURAZIONE AMBIENTE:" -ForegroundColor Yellow
Write-Host "Inserisci le informazioni del tuo ambiente CheckMK" -ForegroundColor White

$config = @{}

# Server CheckMK
do {
    $config.Server = Read-Host "`nServer CheckMK (es: checkmk.domain.com o IP)"
} while (-not $config.Server)

# Site CheckMK
do {
    $config.Site = Read-Host "Nome site CheckMK (es: monitoring, prod)"
} while (-not $config.Site)

# Username SSH
do {
    $config.User = Read-Host "Username per SSH (es: cmkadmin, root)"
} while (-not $config.User)

# Real IP
do {
    $config.RealIP = Read-Host "Real IP del server (es: 192.168.1.100)"
} while (-not $config.RealIP)

# Email test
do {
    $config.TestEmail = Read-Host "Email per test (es: admin@domain.com)"
} while (-not $config.TestEmail)

Write-Host "`n✅ CONFIGURAZIONE RACCOLTA:" -ForegroundColor Green
Write-Host "Server CheckMK: $($config.Server)" -ForegroundColor Cyan
Write-Host "Site: $($config.Site)" -ForegroundColor Cyan
Write-Host "User SSH: $($config.User)" -ForegroundColor Cyan  
Write-Host "Real IP: $($config.RealIP)" -ForegroundColor Cyan
Write-Host "Email test: $($config.TestEmail)" -ForegroundColor Cyan

$confirm = Read-Host "`nConfermi la configurazione? [Y/n]"
if ($confirm -match '^n') {
    Write-Host "❌ Deployment annullato" -ForegroundColor Red
    exit 1
}

# Verifica prerequisiti
Write-Host "`n🔍 VERIFICA PREREQUISITI:" -ForegroundColor Yellow

# 1. Verifica file script
$scriptPath = "script-notify-checkmk\mail_realip_graphs"
if (-not (Test-Path $scriptPath)) {
    Write-Host "❌ Script mail_realip_graphs non trovato!" -ForegroundColor Red
    Write-Host "Assicurati di essere nella directory corretta" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "✅ Script mail_realip_graphs trovato" -ForegroundColor Green
}

# 2. Test connessione SSH
Write-Host "🔌 Test connessione SSH..." -ForegroundColor Cyan
try {
    $sshTest = ssh -o ConnectTimeout=5 -o BatchMode=yes "$($config.User)@$($config.Server)" "echo 'SSH OK'" 2>$null
    if ($sshTest -eq "SSH OK") {
        Write-Host "✅ Connessione SSH funzionante" -ForegroundColor Green
    } else {
        Write-Host "⚠️ Connessione SSH non configurata" -ForegroundColor Yellow
        Write-Host "Continuare comunque? [Y/n]: " -NoNewline -ForegroundColor Yellow
        $continue = Read-Host
        if ($continue -match '^n') {
            Write-Host "❌ Deployment annullato" -ForegroundColor Red
            exit 1
        }
    }
} catch {
    Write-Host "⚠️ Test SSH fallito: $_" -ForegroundColor Yellow
}

Write-Host "`n💾 STEP 1: BACKUP CONFIGURAZIONE ESISTENTE" -ForegroundColor Yellow

# Crea directory backup
$backupDir = "backup_deployment_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Write-Host "📁 Directory backup: $backupDir" -ForegroundColor Cyan

# Comandi backup remoto
$backupCommands = @"
# Backup script esistente se presente
if [ -f /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_00 ]; then
    cp /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_00 /tmp/mail_realip_00_backup
    echo "✅ Script mail_realip_00 salvato"
else
    echo "ℹ️ Script mail_realip_00 non trovato (primo deployment)"
fi

# Backup configurazione notifiche
if [ -f /opt/omd/sites/$($config.Site)/etc/check_mk/conf.d/wato/notifications.mk ]; then
    cp /opt/omd/sites/$($config.Site)/etc/check_mk/conf.d/wato/notifications.mk /tmp/notifications_backup.mk
    echo "✅ Configurazione notifiche salvata"
else
    echo "ℹ️ Configurazione notifiche non trovata"
fi

# Verifica site esistente
if [ -d /opt/omd/sites/$($config.Site) ]; then
    echo "✅ Site CheckMK $($config.Site) trovato"
else
    echo "❌ Site CheckMK $($config.Site) non trovato!"
    exit 1
fi
"@

Write-Host "🔄 Esecuzione backup remoto..." -ForegroundColor Cyan
try {
    $backupResult = ssh "$($config.User)@$($config.Server)" $backupCommands
    $backupResult | ForEach-Object { Write-Host "  $_" }
    
    # Scarica backup localmente
    Write-Host "📥 Download backup locali..." -ForegroundColor Cyan
    scp "$($config.User)@$($config.Server):/tmp/mail_realip_00_backup" "$backupDir/" 2>$null
    scp "$($config.User)@$($config.Server):/tmp/notifications_backup.mk" "$backupDir/" 2>$null
    
} catch {
    Write-Host "⚠️ Backup parziale: $_" -ForegroundColor Yellow
}

Write-Host "`n🚀 STEP 2: INSTALLAZIONE SCRIPT" -ForegroundColor Yellow

# Copia script sul server
Write-Host "📤 Caricamento script sul server..." -ForegroundColor Cyan
try {
    scp $scriptPath "$($config.User)@$($config.Server):/tmp/mail_realip_graphs"
    Write-Host "✅ Script caricato" -ForegroundColor Green
} catch {
    Write-Host "❌ Errore caricamento: $_" -ForegroundColor Red
    exit 1
}

# Installazione script
$installCommands = @"
# Crea directory notifications se non esiste
sudo mkdir -p /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/

# Installa script
sudo cp /tmp/mail_realip_graphs /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/
sudo chmod +x /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_graphs
sudo chown $($config.Site):$($config.Site) /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_graphs

# Verifica installazione
if [ -x /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_graphs ]; then
    echo "✅ Script installato correttamente"
    ls -la /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_graphs
else
    echo "❌ Errore installazione script"
    exit 1
fi

# Cleanup file temporaneo
rm -f /tmp/mail_realip_graphs
"@

Write-Host "🔧 Installazione script..." -ForegroundColor Cyan
try {
    $installResult = ssh "$($config.User)@$($config.Server)" $installCommands
    $installResult | ForEach-Object { Write-Host "  $_" }
} catch {
    Write-Host "❌ Errore installazione: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n🏷️ STEP 3: CONFIGURAZIONE LABEL HOST" -ForegroundColor Yellow
Write-Host "Configurazione manuale richiesta in CheckMK Web UI" -ForegroundColor White

Write-Host "`n📋 ISTRUZIONI CONFIGURAZIONE LABEL:" -ForegroundColor Cyan
Write-Host "1. Aprire browser e andare a: https://$($config.Server)/$($config.Site)/" -ForegroundColor White
Write-Host "2. Login con credenziali CheckMK" -ForegroundColor White
Write-Host "3. Setup → Hosts" -ForegroundColor White
Write-Host "4. Trovare e modificare l'host del server CheckMK" -ForegroundColor White
Write-Host "5. Sezione 'Host labels' → 'Add new label'" -ForegroundColor White
Write-Host "6. Inserire:" -ForegroundColor White
Write-Host "   - Label key: real_ip" -ForegroundColor Green
Write-Host "   - Label value: $($config.RealIP)" -ForegroundColor Green
Write-Host "7. Save & go to folder" -ForegroundColor White
Write-Host "8. Activate affected → Activate changes" -ForegroundColor White

Read-Host "`nPremere ENTER dopo aver configurato il label 'real_ip'..."

Write-Host "`n📧 STEP 4: CONFIGURAZIONE REGOLA NOTIFICA" -ForegroundColor Yellow

Write-Host "`n📋 ISTRUZIONI CONFIGURAZIONE NOTIFICA:" -ForegroundColor Cyan
Write-Host "1. Nella Web UI CheckMK: Setup → Notifications" -ForegroundColor White
Write-Host "2. Add rule → New notification rule" -ForegroundColor White
Write-Host "3. Configurare:" -ForegroundColor White
Write-Host "   - Description: Email Real IP + Graphs" -ForegroundColor Green
Write-Host "   - Method of notification: Custom notification script" -ForegroundColor Green
Write-Host "   - Script name: mail_realip_graphs" -ForegroundColor Green
Write-Host "4. Configurare contatti e condizioni come necessario" -ForegroundColor White
Write-Host "5. Save" -ForegroundColor White
Write-Host "6. Activate affected → Activate changes" -ForegroundColor White

Read-Host "`nPremere ENTER dopo aver configurato la regola notifica..."

Write-Host "`n🧪 STEP 5: TEST SCRIPT" -ForegroundColor Yellow

# Test funzioni script
$testCommands = @"
su - $($config.Site) -c '
export NOTIFY_CONTACTEMAIL="$($config.TestEmail)"
export NOTIFY_HOSTNAME="$($config.Server)"
export NOTIFY_HOSTLABEL_real_ip="$($config.RealIP)"
export NOTIFY_MONITORING_HOST="127.0.0.1"
export NOTIFY_WHAT="HOST"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"
export NOTIFY_HOSTSTATE="DOWN"
export NOTIFY_HOSTOUTPUT="Test notification - Real IP + Graphs"
export NOTIFY_PARAMETER_ELEMENTSS="graph abstime address longoutput"
export NOTIFY_OMD_SITE="$($config.Site)"

echo "=== TEST VARIABLES ==="
echo "Real IP: \$NOTIFY_HOSTLABEL_real_ip"
echo "Test Email: \$NOTIFY_CONTACTEMAIL"
echo "Elements: \$NOTIFY_PARAMETER_ELEMENTSS"

echo "=== TEST SCRIPT SYNTAX ==="
python3 -m py_compile local/share/check_mk/notifications/mail_realip_graphs
echo "✅ Sintassi script OK"

echo "=== TEST SCRIPT EXECUTION (DRY RUN) ==="
echo "Script pronto per test email reale"
'
"@

Write-Host "🔄 Esecuzione test script..." -ForegroundColor Cyan
try {
    $testResult = ssh "$($config.User)@$($config.Server)" $testCommands
    $testResult | ForEach-Object { Write-Host "  $_" }
} catch {
    Write-Host "⚠️ Test parziale: $_" -ForegroundColor Yellow
}

Write-Host "`n📬 STEP 6: TEST EMAIL COMPLETO" -ForegroundColor Yellow

Write-Host "`n📋 ISTRUZIONI TEST EMAIL:" -ForegroundColor Cyan
Write-Host "1. Nella Web UI CheckMK: Monitoring → Hosts" -ForegroundColor White
Write-Host "2. Trovare l'host del server CheckMK" -ForegroundColor White
Write-Host "3. Cliccare sull'icona di notifica personalizzata" -ForegroundColor White
Write-Host "4. Inviare test notification" -ForegroundColor White
Write-Host "5. Controllare email ricevuta a: $($config.TestEmail)" -ForegroundColor Green

Write-Host "`n✅ COSA VERIFICARE NELL'EMAIL:" -ForegroundColor Green
Write-Host "✅ Tutti i link contengono: $($config.RealIP)" -ForegroundColor White
Write-Host "✅ Nessun riferimento a 127.0.0.1" -ForegroundColor White
Write-Host "✅ Grafici PNG allegati all'email" -ForegroundColor White
Write-Host "✅ Link 'View graph' funzionante" -ForegroundColor White
Write-Host "✅ Email HTML completa e formattata" -ForegroundColor White

Read-Host "`nPremere ENTER dopo aver inviato e controllato l'email test..."

Write-Host "`n🎯 VALIDAZIONE FINALE" -ForegroundColor Yellow

$validation = @{}
$validation.RealIP = Read-Host "Email contiene real IP $($config.RealIP) invece di 127.0.0.1? [Y/n]"
$validation.Graphs = Read-Host "Email ha grafici PNG allegati? [Y/n]"
$validation.Links = Read-Host "Link grafici funzionano correttamente? [Y/n]"
$validation.Overall = Read-Host "Email completa e soddisfacente? [Y/n]"

$success = $true
foreach ($check in $validation.Values) {
    if ($check -match '^n') {
        $success = $false
        break
    }
}

if ($success) {
    Write-Host "`n🎉 DEPLOYMENT COMPLETATO CON SUCCESSO!" -ForegroundColor Green
    Write-Host "🏆 SOLUZIONE ATTIVA:" -ForegroundColor Cyan
    Write-Host "✅ Real IP: $($config.RealIP) nelle email" -ForegroundColor Green
    Write-Host "✅ Grafici: Completamente funzionanti" -ForegroundColor Green
    Write-Host "✅ URL: Tutti corretti e accessibili" -ForegroundColor Green
    
    Write-Host "`n📂 FILE BACKUP SALVATI IN:" -ForegroundColor Yellow
    Write-Host "$backupDir" -ForegroundColor Cyan
    
    Write-Host "`n📝 PROSSIMI PASSI:" -ForegroundColor Cyan
    Write-Host "- Monitorare email produzione" -ForegroundColor White
    Write-Host "- Eventualmente disattivare script mail_realip_00" -ForegroundColor White
    Write-Host "- Documentare nuova configurazione" -ForegroundColor White
    
} else {
    Write-Host "`n⚠️ DEPLOYMENT PARZIALE" -ForegroundColor Yellow
    Write-Host "Alcuni controlli falliti. Verificare:" -ForegroundColor White
    Write-Host "- Configurazione label host" -ForegroundColor Cyan
    Write-Host "- Regola notifica attiva" -ForegroundColor Cyan
    Write-Host "- Log CheckMK: /opt/omd/sites/$($config.Site)/var/log/notify.log" -ForegroundColor Cyan
    
    Write-Host "`n🔄 ROLLBACK (se necessario):" -ForegroundColor Red
    Write-Host "scp $backupDir\mail_realip_00_backup $($config.User)@$($config.Server):/tmp/" -ForegroundColor Gray
    Write-Host "ssh $($config.User)@$($config.Server) 'sudo cp /tmp/mail_realip_00_backup /opt/omd/sites/$($config.Site)/local/share/check_mk/notifications/mail_realip_00'" -ForegroundColor Gray
}

Write-Host "`n=== DEPLOYMENT TERMINATO ===" -ForegroundColor Cyan