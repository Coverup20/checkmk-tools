#!/usr/bin/env bash
set -euo pipefail

echo -e "\n===== INSTALLAZIONE E CONFIGURAZIONE TIMESHiFT ====="

LOG_FILE="/var/log/timeshift-rotation.log"
CRON_FILE="/etc/cron.d/timeshift-rotation"

# Verifica se timeshift è già installato
if command -v timeshift &>/dev/null; then
    echo "[INFO] Timeshift risulta già installato." | tee -a "$LOG_FILE"
else
    read -rp "Vuoi installare Timeshift e configurare gli snapshot automatici? (s/n): " risposta
    if [[ "$risposta" =~ ^[Ss]$ ]]; then
        echo "[INFO] Installazione Timeshift e dipendenze..." | tee -a "$LOG_FILE"
        apt-get update -qq >>"$LOG_FILE" 2>&1

        # Se grub-btrfs è disponibile lo installa, altrimenti lo salta
        if apt-cache show grub-btrfs >/dev/null 2>&1; then
            apt-get install -y timeshift inotify-tools grub-btrfs >>"$LOG_FILE" 2>&1 || {
                echo "[ERRORE] Installazione fallita. Controllare il log: $LOG_FILE"
                exit 1
            }
        else
            echo "[WARN] Pacchetto grub-btrfs non disponibile nei repository. Proseguo senza." | tee -a "$LOG_FILE"
            apt-get install -y timeshift inotify-tools >>"$LOG_FILE" 2>&1 || {
                echo "[ERRORE] Installazione Timeshift non riuscita. Controllare il log: $LOG_FILE"
                exit 1
            }
        fi
    else
        echo "[INFO] Installazione Timeshift saltata su richiesta dell'utente." | tee -a "$LOG_FILE"
        exit 0
    fi
fi

# Creazione snapshot iniziale
echo "[INFO] Creazione snapshot iniziale..." | tee -a "$LOG_FILE"
timeshift --create --comments "Snapshot Iniziale Post-Bootstrap" >>"$LOG_FILE" 2>&1 || {
    echo "[WARN] Creazione snapshot iniziale non riuscita. Verificare spazio e configurazione." | tee -a "$LOG_FILE"
}

# Configurazione cron per snapshot 5 volte a settimana (lun-ven alle 03:00)
echo "[INFO] Configurazione rotazione automatica (5 snapshot/settimana) via cron" | tee -a "$LOG_FILE"
cat > "$CRON_FILE" <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Esegue uno snapshot ogni giorno lavorativo alle 03:00
0 3 * * 1-5 root /usr/bin/timeshift --create --comments "Snapshot Automatico Giornaliero" >> /var/log/timeshift-rotation.log 2>&1

# Pulisce snapshot più vecchi di 14 giorni
30 3 * * 1 root /usr/bin/timeshift --check --scripted | grep "Removing" >> /var/log/timeshift-rotation.log 2>&1
EOF

chmod 644 "$CRON_FILE"

VERSION=$(timeshift --version 2>/dev/null || echo "sconosciuta")
echo "[OK] Installazione e configurazione Timeshift completata (versione: $VERSION)." | tee -a "$LOG_FILE"
