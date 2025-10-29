#!/bin/bash
# ===============================================================
# checkmk-tuning-interactive.sh v5.1.1  (Fail-safe edition)
# Autotune intelligente per Checkmk RAW (Nagios core)
# - Timeout 3s su Livestatus
# - Auto fallback log se non disponibile
# - Fix bug awk + debug concorrenza
# - Protezione su servizi_attivi=0
# ===============================================================

set -euo pipefail
SITE="monitoring"
SITEPATH="/opt/omd/sites/$SITE"
NAGIOS_CFG="$SITEPATH/etc/nagios/nagios.d/tuning.cfg"
GLOBAL_MK="$SITEPATH/etc/check_mk/conf.d/wato/global.mk"
LIVE="$SITEPATH/tmp/run/live"
BACKUP_DIR="/root/checkmk_tuning_backup_$(date +%Y%m%d_%H%M%S)"
MODE="${1:-interactive}"

# Colori
G='\033[1;32m'; Y='\033[1;33m'; C='\033[1;36m'; R='\033[1;31m'; N='\033[0m'

require() {
  for b in "$@"; do command -v "$b" >/dev/null 2>&1 || { echo -e "${R}Manca $b${N}"; exit 1; }; done
}
require mpstat bc awk sed grep sort head tail

clear
echo -e "${C}=== Checkmk Tuning Tool v5.1.1 (fail-safe) ===${N}"
echo "Sito: $SITE | Modalità: $MODE"
echo "Backup in: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"
cp -a "$NAGIOS_CFG" "$BACKUP_DIR/" 2>/dev/null || true
cp -a "$GLOBAL_MK" "$BACKUP_DIR/" 2>/dev/null || true
echo

# --- Stato sistema ---
CORES=$(nproc)
CPU_NOW=$(mpstat 3 3 | awk '/Average/ && $12 ~ /[0-9.]+/ {s+=100-$12;c++} END{if(c) printf("%.2f",s/c); else print 0}')
LOAD_NOW=$(awk '{print $1}' /proc/loadavg)
echo -e "${Y}→ Stato sistema:${N} CPU=${CPU_NOW}% | Load=${LOAD_NOW} | Core=${CORES}"

# --- Rilevazione Livestatus (timeout 3s) ---
HAVE_LIVE=0
if [ -S "$LIVE" ]; then
  if timeout 3 bash -c "echo -e 'GET status\n' | unixcat '$LIVE' >/dev/null 2>&1"; then
    HAVE_LIVE=1
    echo -e "${G}✓ Livestatus attivo.${N}"
  else
    echo -e "${Y}⚠ Livestatus non risponde entro 3s → uso fallback log.${N}"
  fi
else
  echo -e "${Y}⚠ Nessun socket Livestatus trovato → uso fallback log.${N}"
fi
echo

# --- Metriche servizi (usa sempre fallback se HAVE_LIVE=0) ---
SRV_COUNT=0; INTERVAL_SEC_AVG=300; AVG_EXEC=0.7; P95_EXEC=1.8; AVG_LAT=0.2; TIMEOUT_RATE=0
LOG="$SITEPATH/var/nagios/nagios.log"

if [ $HAVE_LIVE -eq 1 ]; then
  SRV_COUNT=$(echo -e "GET services\nColumns: active_checks_enabled\nOutputFormat: json\n" | timeout 3 unixcat "$LIVE" | jq 'length' 2>/dev/null || echo 0)
  [ -z "$SRV_COUNT" ] && SRV_COUNT=0
else
  SRV_COUNT=$(grep -c "SERVICE.*INITIALIZED" "$LOG" 2>/dev/null || echo 400)
  NOW=$(date +%s); AGO=$((NOW-3600))
  TOT=$(awk -v t="$AGO" -F'[][]' '$2>=t && /SERVICE ALERT/ {c++} END{print c+0}' "$LOG" 2>/dev/null || echo 0)
  TO=$(awk -v t="$AGO" -F'[][]' '$2>=t && /SERVICE ALERT/ && /SERVICE CHECK TIMEOUT/ {c++} END{print c+0}' "$LOG" 2>/dev/null || echo 0)
  if [ "$TOT" -gt 0 ]; then TIMEOUT_RATE=$(awk -v a="$TO" -v b="$TOT" 'BEGIN{printf("%.2f",(a*100)/b)}'); fi
fi

# --- Protezione ---
if [ "$SRV_COUNT" -le 0 ]; then
  echo -e "${Y}⚠ Nessun servizio rilevato, imposto 400 come valore di default per il tuning.${N}"
  SRV_COUNT=400
fi

echo -e "${Y}→ Metriche servizi:${N} servizi_attivi=${SRV_COUNT} | interval_avg_s=${INTERVAL_SEC_AVG} | p95_exec=${P95_EXEC}s | timeout_rate=${TIMEOUT_RATE}%"
echo

# --- Decision engine avanzato ---
TH_NEEDED=$(awk -v n="$SRV_COUNT" -v s="$INTERVAL_SEC_AVG" 'BEGIN{if(s==0)s=300;printf("%.3f",n/s)}')
CONC_THEO=$(awk -v th="$TH_NEEDED" -v p95="$P95_EXEC" 'BEGIN{v=th*p95*1.3; printf("%.0f", v)}')
echo -e "${C}→ Calcolo concorrenza teorica:${N} TH=${TH_NEEDED} checks/s, P95=${P95_EXEC}s → ${CONC_THEO}"

HARD_CAP=$((CORES*12))
if (( $(echo "$CPU_NOW > 80" | bc -l) )) || (( $(echo "$TIMEOUT_RATE > 2" | bc -l) )); then
  SCALE=0.8
elif (( $(echo "$CPU_NOW < 40" | bc -l) )); then
  SCALE=1.2
else
  SCALE=1.0
fi

NEW_CONC=$(awk -v c="$CONC_THEO" -v s="$SCALE" 'BEGIN{v=c*s;if(v<10)v=10;printf("%.0f",v)}')
[ "$NEW_CONC" -gt "$HARD_CAP" ] && NEW_CONC="$HARD_CAP"
NEW_SLEEP=$(awk -v c="$NEW_CONC" -v cores="$CORES" 'BEGIN{if(c>cores*10)print 0.35;else print 0.25}')
NEW_SVC_TO=$(awk -v x="$P95_EXEC" 'BEGIN{v=int(x*2);if(v<45)v=45;if(v>120)v=120;print v}')
NEW_HOST_TO="$NEW_SVC_TO"; NEW_DELAY="s"

echo -e "${C}=== Riepilogo tuning automatico ===${N}"
cat <<EOF
  max_concurrent_checks = $NEW_CONC
  service_check_timeout = $NEW_SVC_TO
  host_check_timeout    = $NEW_HOST_TO
  sleep_time            = $NEW_SLEEP
  service_inter_check_delay_method = $NEW_DELAY
EOF
echo -e "${Y}→ Applicazione tra 5 secondi (CTRL+C per annullare)...${N}"
for i in {5..1}; do echo -ne "  ⏳ ${i}s...\r"; sleep 1; done; echo

# --- Scrittura config ---
cat > "$NAGIOS_CFG" <<EOF
# Autotune generato automaticamente (v5.1.1 fail-safe)
max_concurrent_checks=$NEW_CONC
service_check_timeout=$NEW_SVC_TO
host_check_timeout=$NEW_HOST_TO
sleep_time=$NEW_SLEEP
service_inter_check_delay_method=$NEW_DELAY
EOF
grep -q "use_cache_for_checking" "$GLOBAL_MK" 2>/dev/null || echo "use_cache_for_checking = True" >> "$GLOBAL_MK"

# --- Riavvio + benchmark ---
echo -e "${Y}→ Riavvio del sito...${N}"
omd restart "$SITE" >/dev/null
echo -e "${Y}→ Attesa 60s di quiete...${N}"
sleep 60

CPU_AFTER=$(mpstat 3 3 | awk '/Average/ && $12 ~ /[0-9.]+/ {s+=100-$12;c++} END{if(c)printf("%.2f",s/c);else print 0}')
LOAD_AFTER=$(awk '{print $1}' /proc/loadavg)
CHECKS_AFTER=$(ps -eo comm | grep check_ | wc -l)

clear
echo -e "${C}=== Benchmark prima e dopo ===${N}"
printf "%-28s %-12s %-12s\n" "Parametro" "Prima" "Dopo"
printf "%-28s %-12s %-12s\n" "CPU Utilization (%)" "$CPU_NOW" "$CPU_AFTER"
printf "%-28s %-12s %-12s\n" "Load Average (1m)"  "$LOAD_NOW" "$LOAD_AFTER"
printf "%-28s %-12s %-12s\n" "Processi check_*"   "?" "$CHECKS_AFTER"
echo -e "${G}Backup:${N} $BACKUP_DIR"
echo -e "${G}✅ Fine (fail-safe mode).${N}"
