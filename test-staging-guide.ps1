# CheckMK Email Real IP + Grafici - Test Guide
# Guida completa per testare il nuovo script in ambiente staging

Write-Host "=== CHECKMK EMAIL REAL IP + GRAFICI - TEST STAGING ===" -ForegroundColor Cyan
Write-Host "Preparazione test completo in ambiente staging" -ForegroundColor Gray

# Configurazione test (MODIFICARE QUESTI VALORI)
$CHECKMK_SERVER = ""  # es: "checkmk-test.domain.com"
$CHECKMK_SITE = ""    # es: "test"
$CHECKMK_USER = ""    # es: "cmkadmin"
$REAL_IP = ""         # es: "192.168.1.100"
$TEST_EMAIL = ""      # es: "test@domain.com"

Write-Host "`n📋 CHECKLIST TEST STAGING:" -ForegroundColor Yellow

$testSteps = @(
    @{
        "Step" = "1. Configurazione Ambiente"
        "Status" = "⏳"
        "Description" = "Configurare parametri test e verificare accesso server"
    },
    @{
        "Step" = "2. Backup Configurazione"
        "Status" = "⏳"
        "Description" = "Salvare configurazione attuale mail_realip_00"
    },
    @{
        "Step" = "3. Deploy Script"
        "Status" = "⏳"
        "Description" = "Installare mail_realip_graphs su server test"
    },
    @{
        "Step" = "4. Configurazione Label"
        "Status" = "⏳"
        "Description" = "Configurare label real_ip nell'host test"
    },
    @{
        "Step" = "5. Test Funzioni Script"
        "Status" = "⏳"
        "Description" = "Verificare funzionalità base script"
    },
    @{
        "Step" = "6. Configurazione Notifiche"
        "Status" = "⏳"
        "Description" = "Configurare regola notifica per test"
    },
    @{
        "Step" = "7. Test Email Complete"
        "Status" = "⏳"
        "Description" = "Inviare email test e verificare risultati"
    },
    @{
        "Step" = "8. Validazione Risultati"
        "Status" = "⏳"
        "Description" = "Confermare real IP e grafici funzionanti"
    }
)

foreach ($step in $testSteps) {
    Write-Host "$($step.Status) $($step.Step)" -ForegroundColor White
    Write-Host "    $($step.Description)" -ForegroundColor Gray
}

Write-Host "`n🔧 COMANDI TEST STAGING:" -ForegroundColor Yellow

Write-Host "`n1. CONFIGURAZIONE INIZIALE:" -ForegroundColor Cyan
Write-Host @"
# Modifica variabili in questo script:
`$CHECKMK_SERVER = "checkmk-test.domain.com"
`$CHECKMK_SITE = "test"
`$CHECKMK_USER = "cmkadmin"
`$REAL_IP = "192.168.1.100"
`$TEST_EMAIL = "test@domain.com"
"@ -ForegroundColor White

Write-Host "`n2. COMANDI SSH PER SERVER TEST:" -ForegroundColor Cyan
Write-Host @"
# Connessione al server
ssh $CHECKMK_USER@$CHECKMK_SERVER

# Backup configurazione esistente
sudo cp /opt/omd/sites/`$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_00 \
    /tmp/mail_realip_00_backup_`$(date +%Y%m%d) 2>/dev/null || echo "No existing script"

# Backup configurazione notifiche
sudo cp /opt/omd/sites/`$CHECKMK_SITE/etc/check_mk/conf.d/wato/notifications.mk \
    /tmp/notifications_backup_`$(date +%Y%m%d).mk 2>/dev/null || echo "No existing notifications"
"@ -ForegroundColor White

Write-Host "`n3. INSTALLAZIONE SCRIPT:" -ForegroundColor Cyan
Write-Host @"
# Da locale (Windows) - copiare script
scp script-notify-checkmk/mail_realip_graphs $CHECKMK_USER@${CHECKMK_SERVER}:/tmp/

# Su server - installare script
ssh $CHECKMK_USER@$CHECKMK_SERVER
sudo mkdir -p /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/
sudo cp /tmp/mail_realip_graphs /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/
sudo chmod +x /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_graphs
sudo chown `${CHECKMK_SITE}:`${CHECKMK_SITE} /opt/omd/sites/`${CHECKMK_SITE}/local/share/check_mk/notifications/mail_realip_graphs

# Verificare installazione
ls -la /opt/omd/sites/$CHECKMK_SITE/local/share/check_mk/notifications/mail_realip_graphs
"@ -ForegroundColor White

Write-Host "`n4. TEST FUNZIONI SCRIPT:" -ForegroundColor Cyan
Write-Host @"
# Su server CheckMK
su - $CHECKMK_SITE

# Test variabili ambiente
export NOTIFY_CONTACTEMAIL="$TEST_EMAIL"
export NOTIFY_HOSTNAME="$CHECKMK_SERVER"
export NOTIFY_HOSTLABEL_real_ip="$REAL_IP"
export NOTIFY_MONITORING_HOST="127.0.0.1"
export NOTIFY_WHAT="HOST"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"
export NOTIFY_HOSTSTATE="DOWN"
export NOTIFY_HOSTOUTPUT="Test notification staging"
export NOTIFY_PARAMETER_ELEMENTSS="graph abstime address"
export NOTIFY_OMD_SITE="$CHECKMK_SITE"

# Test script (dry run)
echo "=== TEST DRY RUN ==="
python3 -c "
import os
print('Variabili ambiente NOTIFY_:')
for key, value in os.environ.items():
    if key.startswith('NOTIFY_'):
        print(f'  {key} = {value}')

real_ip = os.environ.get('NOTIFY_HOSTLABEL_real_ip')
print(f'Real IP estratto: {real_ip}')
"

# Test sintassi script
python3 -m py_compile local/share/check_mk/notifications/mail_realip_graphs
echo "Sintassi script: OK"
"@ -ForegroundColor White

Write-Host "`n5. CONFIGURAZIONE WEB UI:" -ForegroundColor Cyan
Write-Host @"
# Accedere a CheckMK Web UI
URL: https://$CHECKMK_SERVER/$CHECKMK_SITE/

# 1. Configurare label host:
#    Setup → Hosts → [Host CheckMK Server]
#    → Host labels → Add label
#    Key: real_ip
#    Value: $REAL_IP

# 2. Configurare regola notifica:
#    Setup → Notifications → Add rule
#    → Description: "Test Real IP + Graphs"
#    → Method: Custom notification script
#    → Script: mail_realip_graphs
#    → Contact: [utente test]

# 3. Attivare modifiche:
#    → Activate affected → Activate changes
"@ -ForegroundColor White

Write-Host "`n6. TEST EMAIL COMPLETO:" -ForegroundColor Cyan
Write-Host @"
# In CheckMK Web UI:
# 1. Monitoring → Hosts → [Host server]
# 2. Click su icona notifica personalizzata
# 3. Inviare test notification

# Verificare email ricevuta:
# ✅ URL contengono $REAL_IP invece di 127.0.0.1
# ✅ Grafici allegati presenti
# ✅ Link grafici funzionanti con real IP
# ✅ Contenuto HTML completo
"@ -ForegroundColor White

Write-Host "`n📊 RISULTATI ATTESI:" -ForegroundColor Yellow
Write-Host "✅ Email con subject: CheckMK notification" -ForegroundColor Green
Write-Host "✅ Tutti i link contengono: $REAL_IP" -ForegroundColor Green
Write-Host "✅ Grafici PNG allegati all'email" -ForegroundColor Green
Write-Host "✅ Link 'View graph' funzionante" -ForegroundColor Green
Write-Host "✅ Nessun riferimento a 127.0.0.1" -ForegroundColor Green

Write-Host "`n❌ PROBLEMI COMUNI E SOLUZIONI:" -ForegroundColor Red
Write-Host "Problema: Label real_ip non trovato" -ForegroundColor Yellow
Write-Host "Soluzione: Verificare configurazione label in Web UI" -ForegroundColor White
Write-Host ""
Write-Host "Problema: Script non eseguibile" -ForegroundColor Yellow
Write-Host "Soluzione: chmod +x e verifica proprietario file" -ForegroundColor White
Write-Host ""
Write-Host "Problema: Email senza grafici" -ForegroundColor Yellow  
Write-Host "Soluzione: Verificare parametro PARAMETER_ELEMENTSS contiene 'graph'" -ForegroundColor White
Write-Host ""
Write-Host "Problema: Ancora 127.0.0.1 nelle email" -ForegroundColor Yellow
Write-Host "Soluzione: Verificare regola notifica usa script corretto" -ForegroundColor White

Write-Host "`n📝 LOG E DEBUG:" -ForegroundColor Yellow
Write-Host @"
# Log notifiche CheckMK
tail -f /opt/omd/sites/$CHECKMK_SITE/var/log/notify.log

# Debug script specifico
grep "MAIL REALIP WITH GRAPHS" /opt/omd/sites/$CHECKMK_SITE/var/log/notify.log

# Test manuale dettagliato
su - $CHECKMK_SITE
./local/share/check_mk/notifications/mail_realip_graphs 2>&1 | tee test_output.log
"@ -ForegroundColor White

Write-Host "`n✅ VALIDAZIONE FINALE:" -ForegroundColor Green
Write-Host "Prima di passare in produzione verificare:" -ForegroundColor White
Write-Host "- Email test ricevute correttamente" -ForegroundColor Cyan
Write-Host "- Real IP visibile in tutti i link" -ForegroundColor Cyan
Write-Host "- Grafici allegati e funzionanti" -ForegroundColor Cyan
Write-Host "- Nessun errore nei log CheckMK" -ForegroundColor Cyan
Write-Host "- Performance accettabili" -ForegroundColor Cyan

Write-Host "`n🚀 DOPO TEST STAGING:" -ForegroundColor Cyan
Write-Host "Se test staging OK, procedere con:" -ForegroundColor White
Write-Host "1. Deploy in produzione" -ForegroundColor Green
Write-Host "2. Migrazione da mail_realip_00" -ForegroundColor Green
Write-Host "3. Monitoraggio email produzione" -ForegroundColor Green
Write-Host "4. Documentazione finale" -ForegroundColor Green

Write-Host "`n=== TEST STAGING PREPARATO ===" -ForegroundColor Cyan