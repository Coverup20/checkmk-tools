#!/bin/bash
# setup-ydea-mirror.sh - Setup automatico sincronizzazione mirror Ydea

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OMD_SITE="monitoring"
YDEA_DIR="/opt/omd/sites/$OMD_SITE/var/ydea"
SYNC_SCRIPT="$SCRIPT_DIR/ydea-mirror-sync.sh"

echo "=== Setup Ydea Mirror Sync ==="
echo

# 1. Crea directory
echo "[1/5] Creazione directory..."
sudo -u "$OMD_SITE" mkdir -p "$YDEA_DIR/archive"
echo "✓ Directory creata: $YDEA_DIR"

# 2. Copia script sync
echo "[2/5] Installazione script sync..."
sudo cp "$SYNC_SCRIPT" "$YDEA_DIR/sync.sh"
sudo chmod +x "$YDEA_DIR/sync.sh"
sudo chown "$OMD_SITE:$OMD_SITE" "$YDEA_DIR/sync.sh"
echo "✓ Script installato: $YDEA_DIR/sync.sh"

# 3. Test sync iniziale
echo "[3/5] Test sincronizzazione iniziale..."
sudo -u "$OMD_SITE" "$YDEA_DIR/sync.sh" || {
  echo "⚠️  Test fallito, verifica configurazione Ydea"
  exit 1
}
echo "✓ Sincronizzazione iniziale completata"

# 4. Setup cron
echo "[4/5] Configurazione cron (ogni 5 minuti)..."
CRON_LINE="*/5 * * * * $YDEA_DIR/sync.sh >/dev/null 2>&1"

sudo -u "$OMD_SITE" bash -c "
  (crontab -l 2>/dev/null | grep -v 'ydea-mirror-sync' | grep -v '$YDEA_DIR/sync.sh'; echo '$CRON_LINE') | crontab -
"
echo "✓ Cron configurato: ogni 5 minuti"

# 5. Copia funzioni helper
echo "[5/5] Installazione funzioni helper..."
sudo cp "$SCRIPT_DIR/ydea-mirror-functions.sh" "$YDEA_DIR/functions.sh"
sudo chown "$OMD_SITE:$OMD_SITE" "$YDEA_DIR/functions.sh"
echo "✓ Funzioni installate: $YDEA_DIR/functions.sh"

echo
echo "=== Setup Completato! ==="
echo
echo "Mirror Ydea attivo:"
echo "  - Sync ogni: 5 minuti"
echo "  - Mirror file: $YDEA_DIR/mirror.json"
echo "  - Log: $YDEA_DIR/sync.log"
echo "  - Archive: $YDEA_DIR/archive/"
echo
echo "Verifica mirror:"
echo "  cat $YDEA_DIR/mirror.json | jq '.total_count, .sync_date'"
echo
echo "Prossimi passi:"
echo "  1. Integra check mirror in ydea_realip"
echo "  2. Monitora log: tail -f $YDEA_DIR/sync.log"
