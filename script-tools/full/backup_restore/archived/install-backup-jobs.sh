#!/bin/bash
# install-backup-jobs.sh
# Installa systemd timers per gestione automatica backup CheckMK
# - job00: Giornaliero compresso (1.2MB), retention 90, ore 03:00
# - job01: Settimanale normale (362MB), retention 5, domenica 04:00
#
# Uso: ./install-backup-jobs.sh

set -euo pipefail

echo "============================================"
echo "CheckMK Backup Jobs Installation"
echo "============================================"

# Verifica root
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root"
   exit 1
fi

# Chiedi modalità installazione
echo ""
echo "Select schedule mode:"
echo "  1) 🧪 TEST MODE - Every minute (for immediate testing)"
echo "  2) 🚀 PRODUCTION MODE - job00 daily 03:00, job01 Sunday 04:00"
echo ""
read -p "Enter choice [1-2]: " MODE_CHOICE

case $MODE_CHOICE in
    1)
        echo "✅ TEST MODE selected - timers will run every minute"
        TIMER_MODE="test"
        ;;
    2)
        echo "✅ PRODUCTION MODE selected - standard schedule"
        TIMER_MODE="production"
        ;;
    *)
        echo "❌ Invalid choice, defaulting to PRODUCTION MODE"
        TIMER_MODE="production"
        ;;
esac
echo ""

# Step 1: Verifica e prepara script
echo "📋 Preparing scripts..."
SCRIPT_DIR="/opt/checkmk-tools/script-tools/full/backup_restore"
CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$SCRIPT_DIR"

# Copia solo se non siamo già nella directory target
if [[ "$CURRENT_DIR" != "$SCRIPT_DIR" ]]; then
    cp "$CURRENT_DIR/checkmk_manage_job00_daily.sh" "$SCRIPT_DIR/"
    cp "$CURRENT_DIR/checkmk_manage_job01_weekly.sh" "$SCRIPT_DIR/"
    echo "✅ Scripts copied to $SCRIPT_DIR"
else
    echo "✅ Already in target directory, skipping copy"
fi

chmod +x "$SCRIPT_DIR/checkmk_manage_job00_daily.sh"
chmod +x "$SCRIPT_DIR/checkmk_manage_job01_weekly.sh"

# Step 2: Configura e installa systemd units
echo "⚙️  Installing systemd units..."

# Copia timer base
cp "$CURRENT_DIR/systemd/checkmk-backup-job00.timer" /tmp/checkmk-backup-job00.timer
cp "$CURRENT_DIR/systemd/checkmk-backup-job01.timer" /tmp/checkmk-backup-job01.timer

# Modifica timer in base alla modalità
if [[ "$TIMER_MODE" == "test" ]]; then
    echo "  🧪 Configuring TEST schedule (every minute)..."
    sed -i 's/^OnCalendar=.*/OnCalendar=*-*-* *:*:00/' /tmp/checkmk-backup-job00.timer
    sed -i 's/^RandomizedDelaySec=/#RandomizedDelaySec=/' /tmp/checkmk-backup-job00.timer
    sed -i 's/^OnCalendar=.*/OnCalendar=*-*-* *:*:00/' /tmp/checkmk-backup-job01.timer
    sed -i 's/^RandomizedDelaySec=/#RandomizedDelaySec=/' /tmp/checkmk-backup-job01.timer
else
    echo "  🚀 Configuring PRODUCTION schedule..."
    sed -i 's|^# TEST MODE.*||' /tmp/checkmk-backup-job00.timer
    sed -i 's|^# (restore.*||' /tmp/checkmk-backup-job00.timer
    sed -i 's|^# TEST MODE.*||' /tmp/checkmk-backup-job01.timer
    sed -i 's|^# (restore.*||' /tmp/checkmk-backup-job01.timer
fi

# Installa timer configurati
mv /tmp/checkmk-backup-job00.timer /etc/systemd/system/
mv /tmp/checkmk-backup-job01.timer /etc/systemd/system/

# Installa services
cp "$CURRENT_DIR/systemd/checkmk-backup-job00.service" /etc/systemd/system/
cp "$CURRENT_DIR/systemd/checkmk-backup-job01.service" /etc/systemd/system/

echo "✅ Systemd units installed"

# Step 3: Reload systemd
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload
echo "✅ Systemd reloaded"

# Step 4: Abilita e avvia timers
echo "🚀 Enabling and starting timers..."
systemctl enable checkmk-backup-job00.timer
systemctl start checkmk-backup-job00.timer
systemctl enable checkmk-backup-job01.timer
systemctl start checkmk-backup-job01.timer
echo "✅ Timers enabled and started"

# Step 5: Verifica status
echo ""
echo "============================================"
echo "Installation Status"
echo "============================================"
echo ""
echo "Job00 Timer (Daily - 03:00):"
systemctl status checkmk-backup-job00.timer --no-pager -l
echo ""
echo "Next run:"
systemctl list-timers checkmk-backup-job00.timer --no-pager
echo ""
echo "============================================"
echo ""
echo "Job01 Timer (Weekly Sunday - 04:00):"
systemctl status checkmk-backup-job01.timer --no-pager -l
echo ""
echo "Next run:"
systemctl list-timers checkmk-backup-job01.timer --no-pager
echo ""
echo "============================================"
echo "✅ Installation Completed Successfully"
echo "============================================"
echo ""
echo "Logs:"
echo "  - Job00: tail -f /var/log/checkmk-backup-job00.log"
echo "  - Job01: tail -f /var/log/checkmk-backup-job01.log"
echo ""
echo "Manual run:"
echo "  - Job00: systemctl start checkmk-backup-job00.service"
echo "  - Job01: systemctl start checkmk-backup-job01.service"
echo ""
echo "Status:"
echo "  - Job00: systemctl status checkmk-backup-job00.timer"
echo "  - Job01: systemctl status checkmk-backup-job01.timer"
echo "============================================"

exit 0
