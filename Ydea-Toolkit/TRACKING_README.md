# Sistema di Tracking Ticket Ydea

## Panoramica

Il sistema di tracking permette di monitorare automaticamente lo stato dei ticket creati da CheckMK, mantenendo uno storico persistente e fornendo statistiche dettagliate.

## Funzionalità

### 1. Tracking Automatico
- **Salvataggio ticket**: Ogni ticket creato viene salvato con metadata (host, service, timestamp)
- **Aggiornamento stati**: Controllo periodico dello stato dei ticket aperti
- **Rimozione automatica**: I ticket risolti vengono rimossi dopo N giorni (configurabile)
- **Statistiche**: Visualizza ticket aperti/risolti, tempi medi di risoluzione

### 2. File di Tracking
**Posizione**: `/var/log/ydea-tickets-tracking.json`

**Struttura JSON**:
```json
{
  "tickets": [
    {
      "ticket_id": 1503155,
      "codice": "TK25/003376",
      "host": "NB-Marzio",
      "service": "Check_MK",
      "description": "Alert da CheckMK",
      "titolo": "[CRITICAL] NB-Marzio - Check_MK",
      "stato": "Nuovo",
      "created_at": "2025-11-17T10:00:00Z",
      "last_update": "2025-11-17T11:30:00Z",
      "resolved_at": null,
      "checks_count": 5
    }
  ],
  "last_update": "2025-11-17T11:30:00Z"
}
```

## Comandi

### Aggiungere Ticket al Tracking
```bash
/opt/ydea-toolkit/ydea-toolkit.sh track <ticket_id> <codice> <host> <service> [description]
```

**Esempio**:
```bash
/opt/ydea-toolkit/ydea-toolkit.sh track 1503155 "TK25/003376" "server-web" "Apache Status" "Alert da CheckMK"
```

### Visualizzare Statistiche
```bash
/opt/ydea-toolkit/ydea-toolkit.sh stats
```

**Output**:
```
📊 Statistiche Ticket Tracking
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Totale ticket tracciati: 15
  ├─ Aperti: 3
  └─ Risolti: 12

🔴 Ticket Aperti:
  [#1503155] TK25/003376 - server-web/Apache Status - Stato: Nuovo - Creato: 2025-11-17T10:00:00Z
  ...

✅ Ultimi 5 Ticket Risolti:
  [2025-11-17T09:00:00Z] #1503000 TK25/003350 - db-server/MySQL Status
  ...

⏱️  Tempo medio risoluzione: ~4 ore
```

### Aggiornare Stati Ticket
```bash
/opt/ydea-toolkit/ydea-toolkit.sh update-tracking
```

Controlla tutti i ticket aperti e aggiorna i loro stati. Se un ticket è stato risolto, aggiorna `resolved_at`.

### Pulizia Ticket Risolti Vecchi
```bash
/opt/ydea-toolkit/ydea-toolkit.sh cleanup-tracking
```

Rimuove i ticket risolti più vecchi di `YDEA_TRACKING_RETENTION_DAYS` (default: 30 giorni).

### Visualizzare JSON Completo
```bash
/opt/ydea-toolkit/ydea-toolkit.sh list-tracking
```

## Monitoraggio Automatico

### Script: ydea-ticket-monitor.sh
Script che esegue automaticamente:
- Aggiornamento stati ticket ogni esecuzione
- Pulizia ticket risolti vecchi ogni 6 ore

**Posizione**: `/opt/ydea-toolkit/ydea-ticket-monitor.sh`

### Configurazione Cron
Aggiungi al crontab per esecuzione automatica ogni 30 minuti:

```bash
crontab -e
```

```cron
# Ydea Ticket Tracking - aggiornamento automatico ogni 30 minuti
*/30 * * * * /opt/ydea-toolkit/ydea-ticket-monitor.sh >> /var/log/ydea-ticket-monitor.log 2>&1
```

## Integrazione con CheckMK

### Script di Notifica CheckMK
Modifica lo script di notifica per aggiungere automaticamente ticket al tracking:

```bash
# Dopo la creazione del ticket
TICKET_ID=$(echo "$response" | jq -r '.ticket_id')
TICKET_CODE=$(echo "$response" | jq -r '.codice')

# Aggiungi al tracking
/opt/ydea-toolkit/ydea-toolkit.sh track \
  "$TICKET_ID" \
  "$TICKET_CODE" \
  "$NOTIFY_HOSTNAME" \
  "$NOTIFY_SERVICEDESC" \
  "Alert: $NOTIFY_HOSTSTATE/$NOTIFY_SERVICESTATE"
```

## Variabili di Configurazione

### Variabili Ambiente
```bash
export YDEA_TRACKING_FILE="/var/log/ydea-tickets-tracking.json"
export YDEA_TRACKING_RETENTION_DAYS=30  # Mantieni ticket risolti per 30 giorni
```

### File .env
Puoi configurare in `/opt/ydea-toolkit/.env`:
```bash
YDEA_TRACKING_FILE=/var/log/ydea-tickets-tracking.json
YDEA_TRACKING_RETENTION_DAYS=30
```

## Stati Ticket Considerati Risolti

Il sistema considera un ticket "risolto" quando lo stato è uno di:
- `Effettuato`
- `Chiuso`
- `Completato`
- `Risolto`

## Logging

Tutte le operazioni di tracking sono registrate in `/var/log/ydea-toolkit.log` con formato strutturato:

```
[2025-11-17 11:30:00] [INFO] [PID:12345] Aggiunto ticket #1503155 al tracking
[2025-11-17 11:30:15] [SUCCESS] [PID:12346] ✅ Ticket #1503000 RISOLTO (stato: Effettuato)
```

## Statistiche e Report

### Query Utili con jq

**Ticket aperti da più di 24 ore**:
```bash
jq '.tickets[] | select(.resolved_at == null) | select((.created_at | fromdateiso8601) < (now - 86400)) | {ticket_id, codice, host, service, created_at}' /var/log/ydea-tickets-tracking.json
```

**Top 5 host con più ticket**:
```bash
jq -r '.tickets[] | .host' /var/log/ydea-tickets-tracking.json | sort | uniq -c | sort -rn | head -5
```

**Tempo medio di risoluzione per host**:
```bash
jq '.tickets | group_by(.host) | map({host: .[0].host, avg_hours: (map(select(.resolved_at != null) | ((.resolved_at | fromdateiso8601) - (.created_at | fromdateiso8601)) / 3600) | add / length)})' /var/log/ydea-tickets-tracking.json
```

## Backup e Manutenzione

### Backup File Tracking
```bash
cp /var/log/ydea-tickets-tracking.json /backup/ydea-tickets-tracking-$(date +%Y%m%d).json
```

### Reset Completo
```bash
echo '{"tickets":[],"last_update":""}' > /var/log/ydea-tickets-tracking.json
```

## Troubleshooting

### Problema: File tracking non aggiornato
**Soluzione**: Verifica permessi e esegui manualmente:
```bash
sudo chmod 666 /var/log/ydea-tickets-tracking.json
/opt/ydea-toolkit/ydea-toolkit.sh update-tracking
```

### Problema: Ticket non rimossi dopo retention period
**Soluzione**: Esegui pulizia manuale:
```bash
/opt/ydea-toolkit/ydea-toolkit.sh cleanup-tracking
```

### Problema: Stats mostra tempo medio 0
**Soluzione**: Nessun ticket risolto ancora nel tracking. Aspetta che alcuni ticket vengano chiusi.

## Best Practices

1. **Backup regolare**: Backup del file tracking prima di operazioni massive
2. **Retention adeguato**: 30 giorni è un buon compromesso per statistiche e spazio
3. **Monitoraggio cron**: Verifica che il cron job funzioni correttamente
4. **Log review**: Controlla periodicamente `/var/log/ydea-toolkit.log` per errori
5. **Stats periodiche**: Esegui `stats` settimanalmente per review

## Esempi di Workflow

### Workflow Completo CheckMK → Ydea → Tracking
1. CheckMK rileva alert CRITICAL su host
2. Script notifica crea ticket Ydea
3. Script aggiunge ticket al tracking
4. Cron job aggiorna stato ogni 30 min
5. Tecnico risolve problema
6. Ticket chiuso manualmente su Ydea
7. Prossimo update tracking rileva ticket risolto
8. Dopo 30 giorni, ticket rimosso automaticamente

### Report Mensile
```bash
# Ticket risolti questo mese
jq '.tickets[] | select(.resolved_at != null) | select(.resolved_at | startswith("2025-11"))' /var/log/ydea-tickets-tracking.json | jq -s 'length'

# Tempo medio risoluzione questo mese
/opt/ydea-toolkit/ydea-toolkit.sh stats
```
