#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:-/tmp/monitoring_backup_latest.tar.gz}"
SITE="monitoring"

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "[ERROR] Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

echo "[INFO] Stopping site (if running): $SITE"
omd stop "$SITE" || true
pkill -9 -u "$SITE" || true

echo "[INFO] Removing existing site: $SITE"
printf 'yes\n' | omd rm --kill "$SITE"

echo "[INFO] Restoring site from backup: $BACKUP_FILE"
omd restore "$SITE" "$BACKUP_FILE"

echo "[INFO] Starting restored site: $SITE"
omd start "$SITE"

echo "[INFO] Final status"
omd status "$SITE"
