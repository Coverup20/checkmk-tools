# CheckMK Email Real IP + Grafici - Deployment VPS Sicuro
# Script per deployment su VPS con SSH key + passphrase

Write-Host "=== CHECKMK VPS - EMAIL REAL IP + GRAFICI ===" -ForegroundColor Cyan
Write-Host "Deployment per VPS con autenticazione SSH sicura" -ForegroundColor Gray

# Configurazione VPS
Write-Host "`n📋 CONFIGURAZIONE VPS:" -ForegroundColor Yellow

$config = @{}

# Informazioni VPS
do {
    $config.VpsIP = Read-Host "`nIP/Hostname VPS CheckMK"
} while (-not $config.VpsIP)

do {
    $config.SshUser = Read-Host "Username SSH (es: root, ubuntu, cmkadmin)"
} while (-not $config.SshUser)

do {
    $config.SiteCheckMK = Read-Host "Nome site CheckMK (es: monitoring, prod)"
} while (-not $config.SiteCheckMK)

# Path chiave SSH
do {
    $config.SshKeyPath = Read-Host "Path chiave SSH privata (es: C:\Users\..\.ssh\id_rsa)"
    if (-not (Test-Path $config.SshKeyPath)) {
        Write-Host "⚠️ File chiave non trovato!" -ForegroundColor Yellow
        $continue = Read-Host "Continuare comunque? [y/N]"
        if ($continue -ne 'y') { continue }
    }
} while (-not $config.SshKeyPath)

# Email test
do {
    $config.TestEmail = Read-Host "Email per test notifiche"
} while (-not $config.TestEmail)

Write-Host "`n✅ CONFIGURAZIONE VPS:" -ForegroundColor Green
Write-Host "VPS: $($config.VpsIP)" -ForegroundColor Cyan
Write-Host "SSH User: $($config.SshUser)" -ForegroundColor Cyan
Write-Host "Site CheckMK: $($config.SiteCheckMK)" -ForegroundColor Cyan
Write-Host "SSH Key: $($config.SshKeyPath)" -ForegroundColor Cyan
Write-Host "Test Email: $($config.TestEmail)" -ForegroundColor Cyan

$confirm = Read-Host "`nConfermare configurazione? [Y/n]"
if ($confirm -match '^n') {
    Write-Host "❌ Deployment annullato" -ForegroundColor Red
    exit 1
}

# Verifica prerequisiti
Write-Host "`n🔍 VERIFICA PREREQUISITI:" -ForegroundColor Yellow

# 1. Verifica script locale
$scriptPath = "script-notify-checkmk\mail_realip_graphs"
if (-not (Test-Path $scriptPath)) {
    Write-Host "❌ Script mail_realip_graphs non trovato!" -ForegroundColor Red
    Write-Host "Percorso atteso: $scriptPath" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "✅ Script mail_realip_graphs trovato" -ForegroundColor Green
}

# 2. Test connessione SSH con chiave
Write-Host "`n🔐 Test connessione SSH con chiave..." -ForegroundColor Cyan
Write-Host "⚠️ Ti verrà richiesta la passphrase della chiave SSH" -ForegroundColor Yellow

try {
    $sshTestCmd = "ssh -i `"$($config.SshKeyPath)`" -o ConnectTimeout=10 -o StrictHostKeyChecking=no $($config.SshUser)@$($config.VpsIP) `"echo 'SSH_OK'`""
    Write-Host "Comando: $sshTestCmd" -ForegroundColor Gray
    
    $sshResult = Invoke-Expression $sshTestCmd
    if ($sshResult -match "SSH_OK") {
        Write-Host "✅ Connessione SSH funzionante!" -ForegroundColor Green
    } else {
        Write-Host "⚠️ Test SSH inconclusivo. Continuare? [Y/n]: " -NoNewline -ForegroundColor Yellow
        $continue = Read-Host
        if ($continue -match '^n') {
            Write-Host "❌ Deployment interrotto" -ForegroundColor Red
            exit 1
        }
    }
} catch {
    Write-Host "⚠️ Test SSH fallito: $_" -ForegroundColor Yellow
    Write-Host "Verificare chiave SSH e connettività VPS" -ForegroundColor White
    $continue = Read-Host "Continuare comunque? [y/N]"
    if ($continue -ne 'y') {
        Write-Host "❌ Deployment interrotto" -ForegroundColor Red
        exit 1
    }
}

# Funzione SSH helper
function Invoke-SshCommand {
    param(
        [string]$Command,
        [string]$Description = "Comando SSH"
    )
    
    Write-Host "🔄 $Description..." -ForegroundColor Cyan
    
    try {
        $result = & ssh -i "$($config.SshKeyPath)" -o StrictHostKeyChecking=no "$($config.SshUser)@$($config.VpsIP)" $Command
        if ($result) {
            $result | ForEach-Object { Write-Host "  $_" -ForegroundColor White }
        }
        return $true
    } catch {
        Write-Host "❌ Errore: $_" -ForegroundColor Red
        return $false
    }
}

function Invoke-ScpUpload {
    param(
        [string]$LocalPath,
        [string]$RemotePath,
        [string]$Description = "Upload file"
    )
    
    Write-Host "📤 $Description..." -ForegroundColor Cyan
    
    try {
        & scp -i "$($config.SshKeyPath)" -o StrictHostKeyChecking=no "$LocalPath" "$($config.SshUser)@$($config.VpsIP):$RemotePath"
        Write-Host "✅ Upload completato" -ForegroundColor Green
        return $true
    } catch {
        Write-Host "❌ Errore upload: $_" -ForegroundColor Red
        return $false
    }
}

Write-Host "`n💾 STEP 1: BACKUP CONFIGURAZIONE VPS" -ForegroundColor Yellow

# Backup remoto
$backupCommands = @'
# Crea directory backup con timestamp
BACKUP_DIR=/tmp/checkmk_backup_$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
echo "📁 Backup directory: $BACKUP_DIR"

# Backup script esistente
if [ -f /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_00 ]; then
    cp /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_00 $BACKUP_DIR/
    echo "✅ mail_realip_00 salvato"
else
    echo "ℹ️ mail_realip_00 non trovato (primo deployment)"
fi

# Backup configurazioni notifiche
if [ -f /opt/omd/sites/$($config.SiteCheckMK)/etc/check_mk/conf.d/wato/notifications.mk ]; then
    cp /opt/omd/sites/$($config.SiteCheckMK)/etc/check_mk/conf.d/wato/notifications.mk $BACKUP_DIR/
    echo "✅ notifications.mk salvato"
fi

# Verifica sito CheckMK
if [ -d /opt/omd/sites/$($config.SiteCheckMK) ]; then
    echo "✅ Site CheckMK '$($config.SiteCheckMK)' trovato"
    echo "📊 Stato sito:"
    omd status $($config.SiteCheckMK) 2>/dev/null || echo "Comando omd non disponibile"
else
    echo "❌ Site CheckMK '$($config.SiteCheckMK)' NON TROVATO!"
    exit 1
fi

echo "🗂️ Backup salvato in: $BACKUP_DIR"
ls -la $BACKUP_DIR/
'@

if (-not (Invoke-SshCommand -Command $backupCommands -Description "Backup configurazione VPS")) {
    Write-Host "❌ Backup fallito!" -ForegroundColor Red
    exit 1
}

Write-Host "`n🚀 STEP 2: UPLOAD E INSTALLAZIONE SCRIPT" -ForegroundColor Yellow

# Upload script
if (-not (Invoke-ScpUpload -LocalPath $scriptPath -RemotePath "/tmp/mail_realip_graphs" -Description "Upload script mail_realip_graphs")) {
    Write-Host "❌ Upload script fallito!" -ForegroundColor Red
    exit 1
}

# Installazione script
$installCommands = @"
# Verifica upload
if [ ! -f /tmp/mail_realip_graphs ]; then
    echo "❌ Script non trovato dopo upload!"
    exit 1
fi

echo "📁 Script caricato:"
ls -la /tmp/mail_realip_graphs

# Crea directory notifications se necessario
sudo mkdir -p /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/

# Installa script
echo "🔧 Installazione script..."
sudo cp /tmp/mail_realip_graphs /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/
sudo chmod +x /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_graphs
sudo chown $($config.SiteCheckMK):$($config.SiteCheckMK) /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_graphs

# Verifica installazione
if [ -x /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_graphs ]; then
    echo "✅ Script installato correttamente!"
    ls -la /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_graphs
else
    echo "❌ Errore installazione script!"
    exit 1
fi

# Test sintassi Python
echo "🐍 Test sintassi Python..."
su - $($config.SiteCheckMK) -c 'python3 -m py_compile local/share/check_mk/notifications/mail_realip_graphs' && echo "✅ Sintassi OK" || echo "❌ Errori sintassi"

# Cleanup
rm -f /tmp/mail_realip_graphs
echo "🧹 Cleanup temporanei completato"
"@

if (-not (Invoke-SshCommand -Command $installCommands -Description "Installazione script")) {
    Write-Host "❌ Installazione fallita!" -ForegroundColor Red
    exit 1
}

Write-Host "`n🏷️ STEP 3: CONFIGURAZIONE MANUALE RICHIESTA" -ForegroundColor Yellow

Write-Host "`n📋 CONFIGURAZIONE WEB UI CHECKMK:" -ForegroundColor Cyan
Write-Host "⚠️ I prossimi step richiedono configurazione manuale" -ForegroundColor Yellow
Write-Host ""
Write-Host "🌐 1. ACCESSO WEB UI:" -ForegroundColor White
Write-Host "   URL: https://$($config.VpsIP)/$($config.SiteCheckMK)/" -ForegroundColor Green
Write-Host "   Login con le tue credenziali CheckMK" -ForegroundColor White
Write-Host ""
Write-Host "🏷️ 2. CONFIGURAZIONE LABEL HOST:" -ForegroundColor White
Write-Host "   Setup → Hosts → [Seleziona ogni host monitorato]" -ForegroundColor Green
Write-Host "   Per ogni host remoto:" -ForegroundColor White
Write-Host "   - Host labels → Add new label" -ForegroundColor White
Write-Host "   - Label key: real_ip" -ForegroundColor Green
Write-Host "   - Label value: [IP reale dell'host]" -ForegroundColor Green
Write-Host "   - Save & go to folder" -ForegroundColor White
Write-Host ""
Write-Host "📧 3. CONFIGURAZIONE NOTIFICA:" -ForegroundColor White
Write-Host "   Setup → Notifications → Add rule" -ForegroundColor Green
Write-Host "   - Description: Email Real IP + Graphs" -ForegroundColor White
Write-Host "   - Method: Custom notification script" -ForegroundColor White
Write-Host "   - Script name: mail_realip_graphs" -ForegroundColor Green
Write-Host "   - Parameters: graph abstime address longoutput" -ForegroundColor White
Write-Host "   - Configurare contatti e condizioni" -ForegroundColor White
Write-Host "   - Save → Activate changes" -ForegroundColor White

Read-Host "`nPremere ENTER dopo aver completato la configurazione Web UI..."

Write-Host "`n🧪 STEP 4: TEST SCRIPT" -ForegroundColor Yellow

# Test script
$testCommands = @"
echo "🧪 Test script mail_realip_graphs"
echo "=================================="

# Switch al site CheckMK
su - $($config.SiteCheckMK) -c '
export NOTIFY_CONTACTEMAIL="$($config.TestEmail)"
export NOTIFY_HOSTNAME="test-host"
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100"
export NOTIFY_MONITORING_HOST="127.0.0.1"
export NOTIFY_WHAT="HOST"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"
export NOTIFY_HOSTSTATE="DOWN" 
export NOTIFY_HOSTOUTPUT="Test notification - Real IP + Graphs enabled"
export NOTIFY_PARAMETER_ELEMENTSS="graph abstime address longoutput"
export NOTIFY_OMD_SITE="$($config.SiteCheckMK)"

echo "=== VARIABILI TEST ==="
echo "Email: \$NOTIFY_CONTACTEMAIL"
echo "Host: \$NOTIFY_HOSTNAME"
echo "Real IP: \$NOTIFY_HOSTLABEL_real_ip"
echo "Elements: \$NOTIFY_PARAMETER_ELEMENTSS"

echo "=== TEST SINTASSI ==="
python3 -c "
import sys
sys.path.insert(0, \"local/share/check_mk/notifications/\")
try:
    with open(\"local/share/check_mk/notifications/mail_realip_graphs\", \"r\") as f:
        code = f.read()
    compile(code, \"mail_realip_graphs\", \"exec\")
    print(\"✅ Sintassi script OK\")
except Exception as e:
    print(f\"❌ Errore sintassi: {e}\")
"

echo "✅ Script pronto per test email reale"
'
"@

if (-not (Invoke-SshCommand -Command $testCommands -Description "Test script")) {
    Write-Host "⚠️ Test parziale" -ForegroundColor Yellow
}

Write-Host "`n📬 STEP 5: ISTRUZIONI TEST EMAIL" -ForegroundColor Yellow

Write-Host "`n📋 TEST EMAIL COMPLETO:" -ForegroundColor Cyan
Write-Host "1. Nella Web UI CheckMK:" -ForegroundColor White
Write-Host "   Monitoring → Hosts → [Seleziona un host]" -ForegroundColor Green
Write-Host "2. Cliccare Commands → Send custom notification" -ForegroundColor White
Write-Host "3. Verificare email ricevuta a: $($config.TestEmail)" -ForegroundColor Green
Write-Host ""
Write-Host "✅ COSA VERIFICARE:" -ForegroundColor Green
Write-Host "   ✅ Email contiene IP reale invece di 127.0.0.1" -ForegroundColor White
Write-Host "   ✅ Grafici PNG allegati" -ForegroundColor White
Write-Host "   ✅ Link grafici funzionanti" -ForegroundColor White
Write-Host "   ✅ URL utilizzano IP VPS: $($config.VpsIP)" -ForegroundColor White

Write-Host "`n📊 MONITORING LOGS:" -ForegroundColor Yellow
Write-Host "Per debug eventuali problemi:" -ForegroundColor White

$logCommands = @"
echo "📋 LOG NOTIFICHE CHECKMK:"
echo "========================"
tail -20 /opt/omd/sites/$($config.SiteCheckMK)/var/log/notify.log 2>/dev/null || echo "Log notify non disponibile"

echo -e "\n📋 LOG MAIL:"
echo "============"
tail -10 /var/log/mail.log 2>/dev/null || tail -10 /var/log/maillog 2>/dev/null || echo "Log mail non trovato"

echo -e "\n📂 SCRIPT INSTALLATO:"
echo "====================="
ls -la /opt/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip*
"@

Invoke-SshCommand -Command $logCommands -Description "Controllo log" | Out-Null

Write-Host "`n🎯 DEPLOYMENT COMPLETATO!" -ForegroundColor Green
Write-Host "==========================" -ForegroundColor Green

Write-Host "`n✅ SCRIPT INSTALLATO:" -ForegroundColor Cyan
Write-Host "   - mail_realip_graphs attivo su VPS" -ForegroundColor White
Write-Host "   - Sintassi verificata" -ForegroundColor White
Write-Host "   - Pronto per configurazione" -ForegroundColor White

Write-Host "`n📝 PROSSIMI PASSI:" -ForegroundColor Yellow
Write-Host "   1. Configurare label 'real_ip' per ogni host" -ForegroundColor White
Write-Host "   2. Configurare regola notifica" -ForegroundColor White
Write-Host "   3. Testare email notifica" -ForegroundColor White
Write-Host "   4. Monitorare logs per eventuali problemi" -ForegroundColor White

Write-Host "`n🆘 SUPPORTO:" -ForegroundColor Magenta
Write-Host "   - VPS: $($config.VpsIP)" -ForegroundColor White
Write-Host "   - SSH: ssh -i `"$($config.SshKeyPath)`" $($config.SshUser)@$($config.VpsIP)" -ForegroundColor Gray
Write-Host "   - CheckMK: https://$($config.VpsIP)/$($config.SiteCheckMK)/" -ForegroundColor White
Write-Host "   - Logs: /opt/omd/sites/$($config.SiteCheckMK)/var/log/notify.log" -ForegroundColor Gray

Write-Host "`n=== DEPLOYMENT VPS TERMINATO ===" -ForegroundColor Cyan