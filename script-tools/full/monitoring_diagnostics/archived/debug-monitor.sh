#!/bin/bash
TRACKING_FILE="/var/log/ydea-tickets-tracking.json"
echo "=== DEBUG MONITOR ==="
echo ""
echo "1. Lettura PREVIOUS (prima di update-tracking):"
jq -r '.tickets[] | select(.resolved_at == null) | "\(.ticket_id)|\(.stato)|\(.descrizione_ticket // "")|\(.priorita // "Normale")|\(.assegnatoA // "Non assegnato")"' "$TRACKING_FILE"
echo ""
echo "2. Parsing con while loop (simula monitor):"
while IFS='|' read -r tid stato desc prio assegnato; do
  echo "tid=$tid"
  echo "stato=$stato"
  echo "desc=$desc"
  echo "prio=$prio"  
echo "assegnato=$assegnato"
done < <(jq -r '.tickets[] | select(.resolved_at == null) | "\(.ticket_id)|\(.stato)|\(.descrizione_ticket // "")|\(.priorita // "Normale")|\(.assegnatoA // "Non assegnato")"' "$TRACKING_FILE")
echo ""
echo "3. Eseguo update-tracking:"/opt/checkmk-tools/Ydea-Toolkit/full/ydea-toolkit.sh update-tracking
echo ""
echo "4. Lettura CURRENT (dopo update-tracking):"jq -r '.tickets[] | "\(.ticket_id)|\(.stato)|\(.host)|\(.service)|\(.codice)|\(.descrizione_ticket // "")|\(.priorita // "Normale")|\(.assegnatoA // "Non assegnato")"' "$TRACKING_FILE"
echo ""
echo "5. Parsing con while loop COMPLETO (8 campi):"while 
IFS='|' read -r tid stato host service codice desc prio assegnato _extra; do  
echo "tid=$tid"  
echo "stato=$stato"  
echo "host=$host"  
echo "service=$service"  
echo "codice=$codice"  
echo "desc=$desc"  
echo "prio=$prio"  
echo "assegnato=$assegnato"  
echo "_extra=$_extra"
done < <(jq -r '.tickets[] | "\(.ticket_id)|\(.stato)|\(.host)|\(.service)|\(.codice)|\(.descrizione_ticket // "")|\(.priorita // "Normale")|\(.assegnatoA // "Non assegnato")"' "$TRACKING_FILE")
