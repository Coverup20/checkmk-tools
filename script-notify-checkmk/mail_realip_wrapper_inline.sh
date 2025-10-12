#!/bin/bash
# Wrapper Bash per aggiungere NOTIFY_HOSTLABEL_real_ip in CRE (Raw Edition)

# 1. Se abbiamo giÃ  NOTIFY_HOSTLABELS, estrai real_ip:...
if [ -n "$NOTIFY_HOSTLABELS" ]; then
    REAL_IP=$(echo "$NOTIFY_HOSTLABELS" | grep -o 'real_ip:[^,]*' | cut -d: -f2)
    export NOTIFY_HOSTLABEL_real_ip="$REAL_IP"
fi

# 2. (Opzionale) Se REAL_IP Ã¨ vuoto, puoi usare un mapping statico
# File CSV: hostname,ip
MAPPING_FILE="/omd/sites/monitoring/local/etc/real_ip_map.csv"
if [ -z "$NOTIFY_HOSTLABEL_real_ip" ] && [ -f "$MAPPING_FILE" ]; then
    REAL_IP=$(grep "^${NOTIFY_HOSTNAME}," "$MAPPING_FILE" | cut -d, -f2)
    [ -n "$REAL_IP" ] && export NOTIFY_HOSTLABEL_real_ip="$REAL_IP"
fi

# 3. Debug log
LOGFILE="/omd/sites/monitoring/var/log/mail_realip_wrapper.log"
echo "[$(date)] host=$NOTIFY_HOSTNAME real_ip=$NOTIFY_HOSTLABEL_real_ip labels=$NOTIFY_HOSTLABELS" >> "$LOGFILE"

# 4. Avvia lo script Python originale
exec /omd/sites/monitoring/local/share/check_mk/notifications/mail_realip_wrapper_inline "$@"
