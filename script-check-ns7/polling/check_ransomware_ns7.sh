#!/bin/bash
# Ransomware/Cryptolocker Monitor per NethServer 7.9
# Scansiona tutte le share Samba e logga file sospetti
# Log: /var/log/ransomware_monitor.log

LOGFILE="/var/log/ransomware_monitor.log"
SUSPECT_EXTS="encrypted crypt locked enc lock ransom pay recover"
RANSOM_NOTES="README DECRYPT HOW_TO_RECOVER UNLOCK HELP RESTORE"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

SHARES=$(grep -E '^[[]' /etc/samba/smb.conf | grep -Ev 'global|homes|printers' | sed 's/\[//;s/\]//')

for SHARE in $SHARES; do
    SHARE_PATH=$(grep -A5 "[$SHARE]" /etc/samba/smb.conf | grep 'path =' | head -1 | cut -d'=' -f2 | xargs)
    [ -z "$SHARE_PATH" ] && continue

    FOUND=""
    for EXT in $SUSPECT_EXTS; do
        while IFS= read -r F; do
            FOUND="$FOUND$F\n"
        done < <(find "$SHARE_PATH" -type f -name "*.$EXT" 2>/dev/null)
    done
    for NOTE in $RANSOM_NOTES; do
        while IFS= read -r F; do
            FOUND="$FOUND$F\n"
        done < <(find "$SHARE_PATH" -type f -iname "*$NOTE*" 2>/dev/null)
    done

    if [ -n "$FOUND" ]; then
        echo "[$DATE] [SHARE:$SHARE] [PATH:$SHARE_PATH] File sospetti trovati:" >> "$LOGFILE"
        echo -e "$FOUND" | while read -r F; do
            [ -n "$F" ] && echo "  $F" >> "$LOGFILE"
        done
    fi

done

# Output per CheckMK
if grep -q "File sospetti trovati:" "$LOGFILE"; then
    echo "2 CRITICAL - Ransomware: file sospetti rilevati. Vedi $LOGFILE"
else
    echo "0 OK - Nessun ransomware rilevato"
fi
