@echo off
echo === AGGIORNAMENTO SCRIPT MAIL_REALIP_GRAPHS ===
echo Bug fix: Correzione lettura label NOTIFY_HOSTLABEL_real_ip

echo.
echo Inserisci il path della tua chiave SSH:
set /p SSH_KEY="Path chiave SSH: "

echo.
echo Caricamento script corretto...
scp -i "%SSH_KEY%" "script-notify-checkmk\mail_realip_graphs" root@monitor.nethlab.it:/tmp/

echo.
echo Installazione...
ssh -i "%SSH_KEY%" root@monitor.nethlab.it "sudo cp /tmp/mail_realip_graphs /opt/omd/sites/monitoring/local/share/check_mk/notifications/ && sudo chown monitoring:monitoring /opt/omd/sites/monitoring/local/share/check_mk/notifications/mail_realip_graphs"

echo.
echo Script aggiornato! Ora il label real_ip dovrebbe funzionare.
echo Testa una nuova notifica per verificare.

pause