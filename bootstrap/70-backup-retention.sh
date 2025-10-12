#!/usr/bin/env bash
set -euo pipefail

# Backup retention script for CheckMK monitoring server
# Manages automatic backups and retention policies

BACKUP_DIR="${BACKUP_DIR:-/var/lib/checkmk_backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
SITE="${SITE:-monitoring}"

echo "==> Configurazione backup retention per CheckMK"

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Check if OMD site exists
if ! omd sites | awk '{print $1}' | grep -qx "$SITE"; then
  echo "⚠️  Site $SITE non trovato. Saltare la configurazione backup."
  exit 0
fi

# Create backup script
BACKUP_SCRIPT="/usr/local/bin/checkmk_backup.sh"
cat > "$BACKUP_SCRIPT" <<'BACKUP_EOF'
#!/usr/bin/env bash
set -euo pipefail

SITE="monitoring"
BACKUP_DIR="/var/lib/checkmk_backups"
RETENTION_DAYS=30

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/${SITE}_backup_${TIMESTAMP}.tar.gz"

echo "==> Avvio backup CheckMK site: $SITE"
omd backup "$SITE" "$BACKUP_FILE"

if [ -f "$BACKUP_FILE" ]; then
  echo "✅ Backup completato: $BACKUP_FILE"
  SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
  echo "   Dimensione: $SIZE"
else
  echo "❌ Errore durante il backup"
  exit 1
fi

# Cleanup old backups
echo "==> Rimozione backup più vecchi di $RETENTION_DAYS giorni"
find "$BACKUP_DIR" -name "${SITE}_backup_*.tar.gz" -type f -mtime +$RETENTION_DAYS -delete

REMAINING=$(find "$BACKUP_DIR" -name "${SITE}_backup_*.tar.gz" -type f | wc -l)
echo "   Backup rimanenti: $REMAINING"
BACKUP_EOF

chmod +x "$BACKUP_SCRIPT"

# Create systemd timer for automatic backups
TIMER_NAME="checkmk-backup"
TIMER_PATH="/etc/systemd/system/${TIMER_NAME}.timer"
SERVICE_PATH="/etc/systemd/system/${TIMER_NAME}.service"

# Create service unit
cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=CheckMK Backup Service
After=network.target

[Service]
Type=oneshot
ExecStart=$BACKUP_SCRIPT
User=root
StandardOutput=journal
StandardError=journal
EOF

# Create timer unit (daily at 2 AM)
cat > "$TIMER_PATH" <<EOF
[Unit]
Description=CheckMK Daily Backup Timer
Requires=${TIMER_NAME}.service

[Timer]
OnCalendar=daily
Persistent=true
Unit=${TIMER_NAME}.service

[Install]
WantedBy=timers.target
EOF

# Enable and start timer
systemctl daemon-reload
systemctl enable "${TIMER_NAME}.timer"
systemctl start "${TIMER_NAME}.timer"

echo ""
echo "✅ Backup retention configurato"
echo "   Directory backup: $BACKUP_DIR"
echo "   Retention: $RETENTION_DAYS giorni"
echo "   Timer: ${TIMER_NAME}.timer (daily at 2 AM)"
echo "   Script: $BACKUP_SCRIPT"
echo ""
echo "Comandi utili:"
echo "  - Esegui backup manuale: $BACKUP_SCRIPT"
echo "  - Stato timer: systemctl status ${TIMER_NAME}.timer"
echo "  - Lista backup: ls -lh $BACKUP_DIR"
echo ""
