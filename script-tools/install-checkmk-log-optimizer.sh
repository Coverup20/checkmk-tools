#!/bin/bash
# ==========================================================
#  Checkmk RAW - LOG OPTIMIZATION PACK (Versione 2)
#  Include TUTTI i log: Nagios, Apache, OMD, Event Console,
#  Piggyback, Crash dump, Notify.
#  Autore: ChatGPT per Marzio Bordin
# ==========================================================

SITE="monitoring"
SITE_PATH="/opt/omd/sites/$SITE"

echo " "
echo "==============================================="
echo "   INSTALLAZIONE LOG OPTIMIZATION PACK"
echo "   Checkmk RAW - sito: $SITE"
echo "==============================================="
echo " "

# ==========================================================
# 1. LOGROTATE NAGIOS (core)
# ==========================================================
echo "👉 Configurazione logrotate per NAGIOS..."

cat > $SITE_PATH/etc/logrotate.d/nagios << 'EOF'
/opt/omd/sites/monitoring/var/nagios/nagios.log {
    daily
    rotate 14
    size 100M
    compress
    delaycompress
    missingok
    notifempty
    create 640 monitoring monitoring
    sharedscripts
    postrotate
        /opt/omd/sites/monitoring/bin/omd reload monitoring > /dev/null 2>&1 || true
    endscript
}
EOF

chown root:root $SITE_PATH/etc/logrotate.d/nagios
chmod 644 $SITE_PATH/etc/logrotate.d/nagios


# ==========================================================
# 2. LOGROTATE APACHE DEL SITO
# ==========================================================
echo "👉 Configurazione logrotate per APACHE interno..."

cat > $SITE_PATH/etc/logrotate.d/apache << 'EOF'
/opt/omd/sites/monitoring/var/log/apache/*log* {
    daily
    rotate 14
    size 50M
    compress
    delaycompress
    missingok
    notifempty
    create 640 monitoring monitoring
    sharedscripts
    postrotate
        /opt/omd/sites/monitoring/bin/apache reload monitoring > /dev/null 2>&1 || true
    endscript
}
EOF

chown root:root $SITE_PATH/etc/logrotate.d/apache
chmod 644 $SITE_PATH/etc/logrotate.d/apache


# ==========================================================
# 3. LOGROTATE OMD CORE (cmk.log, notify.log, web.log, ecc.)
# ==========================================================
echo "👉 Configurazione logrotate per OMD core..."

cat > $SITE_PATH/etc/logrotate.d/omd << 'EOF'
/opt/omd/sites/monitoring/var/log/*.log {
    daily
    rotate 14
    size 50M
    compress
    delaycompress
    missingok
    notifempty
    create 640 monitoring monitoring
}
EOF

chown root:root $SITE_PATH/etc/logrotate.d/omd
chmod 644 $SITE_PATH/etc/logrotate.d/omd


# ==========================================================
# 4. LOGROTATE EVENT CONSOLE (mkeventd)
# ==========================================================
echo "👉 Configurazione logrotate per EVENT CONSOLE..."

cat > $SITE_PATH/etc/logrotate.d/mkeventd << 'EOF'
/opt/omd/sites/monitoring/var/log/mkeventd.log {
    weekly
    rotate 8
    size 20M
    compress
    delaycompress
    missingok
    notifempty
}
EOF

chown root:root $SITE_PATH/etc/logrotate.d/mkeventd
chmod 644 $SITE_PATH/etc/logrotate.d/mkeventd


# ==========================================================
# 5. CLEANUP AUTOMATICO PIGGYBACK
# ==========================================================
echo "👉 Installazione script pulizia PIGGYBACK..."

cat > $SITE_PATH/local/lib/cleanup-piggyback.sh << 'EOF'
#!/bin/bash
find /opt/omd/sites/monitoring/var/piggyback -type f -mtime +3 -delete
find /opt/omd/sites/monitoring/var/piggyback -type d -empty -delete
EOF

chmod +x $SITE_PATH/local/lib/cleanup-piggyback.sh

cat > $SITE_PATH/etc/cron.d/cleanup-piggyback << 'EOF'
0 3 * * * monitoring /opt/omd/sites/monitoring/local/lib/cleanup-piggyback.sh
EOF

chown monitoring:monitoring $SITE_PATH/etc/cron.d/cleanup-piggyback
chmod 644 $SITE_PATH/etc/cron.d/cleanup-piggyback


# ==========================================================
# 6. CLEANUP CRASH DUMP
# ==========================================================
echo "👉 Installazione script pulizia CRASH dump..."

cat > $SITE_PATH/local/lib/cleanup-crash.sh << 'EOF'
#!/bin/bash
find /opt/omd/sites/monitoring/var/check_mk/crash -type f -mtime +7 -delete
EOF

chmod +x $SITE_PATH/local/lib/cleanup-crash.sh

cat > $SITE_PATH/etc/cron.d/cleanup-crash << 'EOF'
10 3 * * * monitoring /opt/omd/sites/monitoring/local/lib/cleanup-crash.sh
EOF

chown monitoring:monitoring $SITE_PATH/etc/cron.d/cleanup-crash
chmod 644 $SITE_PATH/etc/cron.d/cleanup-crash


# ==========================================================
# 7. CLEANUP NOTIFY LOGS (telegram / mail)
# ==========================================================
echo "👉 Installazione script pulizia NOTIFY logs..."

cat > $SITE_PATH/local/lib/cleanup-notify.sh << 'EOF'
#!/bin/bash
find /opt/omd/sites/monitoring/var/log/notify -type f -mtime +5 -delete
EOF

chmod +x $SITE_PATH/local/lib/cleanup-notify.sh

cat > $SITE_PATH/etc/cron.d/cleanup-notify << 'EOF'
20 3 * * * monitoring /opt/omd/sites/monitoring/local/lib/cleanup-notify.sh
EOF

chown monitoring:monitoring $SITE_PATH/etc/cron.d/cleanup-notify
chmod 644 $SITE_PATH/etc/cron.d/cleanup-notify


# ==========================================================
#  REPORT FINALE
# ==========================================================
echo ""
echo "==============================================="
echo "   ✔ INSTALLAZIONE COMPLETATA CON SUCCESSO"
echo "==============================================="
echo "Log gestiti:"
echo " - Nagios (core)"
echo " - Apache del sito"
echo " - OMD core"
echo " - Event Console"
echo ""
echo "Cleanup automatici attivi:"
echo " - Piggyback"
echo " - Crash dump"
echo " - Notify logs"
echo ""
echo "Puoi testare con:"
echo " ➤ logrotate -vf $SITE_PATH/etc/logrotate.d/apache"
echo ""
