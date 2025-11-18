#!/bin/bash
# check-proxmox-vm-status-multi.sh
# Versione 3.5 (2025-10-07)
# Ogni VM/LXC come servizio distinto, nomi maiuscoli, uptime leggibile completo

NODE=$(hostname)
TMP_QEMU=$(mktemp)
TMP_LXC=$(mktemp)

# --- Recupero dati ---
pvesh get /nodes/$NODE/qemu --output-format json > "$TMP_QEMU" 2>/dev/null
pvesh get /nodes/$NODE/lxc  --output-format json > "$TMP_LXC"  2>/dev/null

# --- Funzione per convertire uptime in formato leggibile completo ---
human_time() {
    local SECS=$1
    local DAYS=$((SECS / 86400))
    local HOURS=$(((SECS % 86400) / 3600))
    local MINUTES=$(((SECS % 3600) / 60))
    local SECONDS=$((SECS % 60))
    local OUT=""

    (( DAYS > 0 )) && OUT+="${DAYS} d "
    (( HOURS > 0 )) && OUT+="${HOURS} h "
    (( MINUTES > 0 )) && OUT+="${MINUTES} min "
    (( SECONDS > 0 )) && OUT+="${SECONDS} s"

    [[ -z "$OUT" ]] && OUT="0 s"
    echo "$OUT" | xargs
}

# --- Funzione per maiuscolizzare ---
uppercase() {
    echo "$1" | tr '[:lower:]' '[:upper:]'
}

# --- Verifica errori ---
if [[ ! -s "$TMP_QEMU" && ! -s "$TMP_LXC" ]]; then
    echo "2 Proxmox_VM_Global - ERRORE: impossibile ottenere elenco VM/LXC"
    rm -f "$TMP_QEMU" "$TMP_LXC"
    exit 2
fi

# --- Contatori globali ---
QEMU_TOTAL=$(jq 'length' "$TMP_QEMU" 2>/dev/null)
QEMU_RUNNING=$(jq '[.[] | select(.status=="running")] | length' "$TMP_QEMU" 2>/dev/null)
LXC_TOTAL=$(jq 'length' "$TMP_LXC" 2>/dev/null)
LXC_RUNNING=$(jq '[.[] | select(.status=="running")] | length' "$TMP_LXC" 2>/dev/null)
TOTAL=$((QEMU_TOTAL + LXC_TOTAL))
RUNNING=$((QEMU_RUNNING + LXC_RUNNING))
STOPPED=$((TOTAL - RUNNING))

# --- Riga riepilogativa globale ---
if (( RUNNING == 0 )); then
    STATUS=2
    MSG="CRIT: nessuna VM o container attivo"
elif (( STOPPED > 0 )); then
    STATUS=1
    MSG="WARN: $RUNNING/$TOTAL attivi ($STOPPED spenti)"
else
    STATUS=0
    MSG="OK: tutti i $TOTAL attivi"
fi

echo "$STATUS Proxmox_VM_Global total_active=$RUNNING;0;$TOTAL;0;$TOTAL total_total=$TOTAL;0;$TOTAL;0;$TOTAL - $MSG"

# --- VM (QEMU) ---
if (( QEMU_TOTAL > 0 )); then
    jq -r '.[] | "\(.vmid) \(.name) \(.status) \(.uptime)"' "$TMP_QEMU" | while read -r ID NAME STATUSTXT UPTIME; do
        NAME_UPPER=$(uppercase "$NAME")
        SERVICE_NAME=$(uppercase "vm_${ID}_${NAME}")
        UPTIME_HUMAN=$(human_time "$UPTIME")
        if [[ "$STATUSTXT" == "running" ]]; then
            echo "0 ${SERVICE_NAME} uptime=${UPTIME}s;0;;0; VMID:${ID} (${NAME_UPPER}) Running, Uptime ${UPTIME_HUMAN}"
        else
            echo "1 ${SERVICE_NAME} uptime=${UPTIME}s;0;;0; VMID:${ID} (${NAME_UPPER}) Stopped, Uptime ${UPTIME_HUMAN}"
        fi
    done
fi

# --- LXC ---
if (( LXC_TOTAL > 0 )); then
    jq -r '.[] | "\(.vmid) \(.name) \(.status) \(.uptime)"' "$TMP_LXC" | while read -r ID NAME STATUSTXT UPTIME; do
        NAME_UPPER=$(uppercase "$NAME")
        SERVICE_NAME=$(uppercase "lxc_${ID}_${NAME}")
        UPTIME_HUMAN=$(human_time "$UPTIME")
        if [[ "$STATUSTXT" == "running" ]]; then
            echo "0 ${SERVICE_NAME} uptime=${UPTIME}s;0;;0; CTID:${ID} (${NAME_UPPER}) Running, Uptime ${UPTIME_HUMAN}"
        else
            echo "1 ${SERVICE_NAME} uptime=${UPTIME}s;0;;0; CTID:${ID} (${NAME_UPPER}) Stopped, Uptime ${UPTIME_HUMAN}"
        fi
    done
fi

# --- Cleanup ---
rm -f "$TMP_QEMU" "$TMP_LXC"
exit 0
