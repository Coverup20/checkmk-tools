# Cache TTL e Risoluzione Ticket - Aggiornamento

## Riepilogo Modifiche

Implementata gestione corretta del ciclo di vita dei ticket in cache con TTL differenziati per ticket risolti e attivi.

## Workflow Completo

### 1. Alert CRITICAL/DOWN
```
1. Controlla cache: ticket presente?
   ├─ SÌ → Verifica via API se ancora aperto
   │   ├─ Aperto → Aggiungi nota
   │   ├─ Chiuso dall'operatore → Aggiungi nota finale (se possibile), mantieni cache
   │   └─ Cancellato (404) → Rimuovi da cache
   └─ NO → Verifica via API se esiste già
       ├─ Esiste → Aggiungi nota + salva in cache
       └─ Non esiste → Crea ticket + salva in cache
```

### 2. Alert OK/UP (Rientro)
```
1. Verifica ticket in cache
   ├─ SÌ → Aggiungi nota "Allarme rientrato"
   │       + marca ticket.resolved_at = timestamp corrente
   │       + parte timer 5 giorni
   └─ NO → Nessuna azione
```

### 3. Pulizia Automatica Cache
```
clean_old_cache_entries() esegue check:
├─ Ticket risolti (resolved_at != null)
│   └─ Se (now - resolved_at) > 5 giorni → RIMUOVI
└─ Ticket attivi (resolved_at == null)
    └─ Se (now - last_update) > 30 giorni → RIMUOVI
```

## Configurazione

```bash
# Tempo di ritenzione per ticket risolti: 5 giorni
RESOLVED_TICKET_TTL=$((5*24*3600))

# Tempo di ritenzione per ticket attivi: 30 giorni (fallback)
CACHE_MAX_AGE=$((30*24*3600))
```

## Struttura Cache JSON

```json
{
  "192.168.10.100:Memory": {
    "ticket_id": 1502598,
    "state": "OK",
    "created_at": 1735040400,
    "last_update": 1735126800,
    "resolved_at": 1735126800  // timestamp quando passa a OK/UP (null se attivo)
  }
}
```

## Funzioni Modificate

### 1. `save_ticket_cache()`
- **Modifica**: Aggiunto campo `resolved_at: null` nella creazione iniziale
- **Motivo**: Tutti i ticket nuovi partono come attivi (non risolti)

### 2. `mark_ticket_resolved()`
- **Nuova funzione**: Imposta timestamp `resolved_at` quando alert passa a OK/UP
- **Uso**: Chiamata automaticamente dopo aggiunta nota di rientro
- **Effetto**: Parte il timer di 5 giorni per cleanup

### 3. `clean_old_cache_entries()`
- **Modifica**: Logica differenziata per ticket risolti vs attivi
- **Logica**: 
  - `resolved_at != null` → TTL 5 giorni
  - `resolved_at == null` → TTL 30 giorni
- **Usa**: `atomic_cache_write()` per sicurezza concorrenza

### 4. Gestione Alert SERVICE (linee 434-467)
- **Modifica**: Aggiunto blocco dopo `update_ticket_state()`
  ```bash
  if [[ "$STATE" == "OK" || "$STATE" == "UP" ]]; then
    mark_ticket_resolved "$TICKET_KEY"
    log "Ticket #$TICKET_ID marcato come risolto, cleanup automatico tra 5 giorni"
  fi
  ```

### 5. Gestione Alert HOST (linee 599-622)
- **Modifica**: Stessa logica applicata per alert host
- **Simmetria**: Comportamento identico tra SERVICE e HOST alerts

## Casistiche Gestite

| Scenario | Comportamento Cache | Note |
|----------|-------------------|------|
| Alert CRIT → crea ticket | Salva con `resolved_at: null` | Ticket attivo, TTL 30gg |
| Alert CRIT → OK | Imposta `resolved_at: timestamp` | Parte timer 5gg |
| Operatore chiude ticket su Ydea | Cache rimane invariata | Cleanup dopo 30gg se mai risolto |
| Alert OK dopo chiusura operatore | Aggiorna `resolved_at` | Cleanup dopo 5gg dal rientro |
| Ticket cancellato (404) | Rimozione immediata | Unico caso di rimozione sincrona |
| Alert CRIT → OK → CRIT di nuovo | Reset `resolved_at: null` | Ticket torna attivo, TTL 30gg |

## Vantaggi Implementazione

1. **Persistenza Ticket**: Cache non perde tracking anche se operatore chiude ticket
2. **Cleanup Intelligente**: TTL breve (5gg) per risolti, lungo (30gg) per attivi
3. **Anti-Duplicazione**: Verifica API prima di creare nuovo ticket
4. **Tracciabilità**: `resolved_at` permette audit del momento esatto di risoluzione
5. **Race-Safe**: Usa `atomic_cache_write()` con flock in tutte le modifiche

## Testing Raccomandato

```bash
# 1. Crea alert CRITICAL
# Verifica: cat /tmp/ydea_checkmk_tickets.json | jq '.["IP:SERVICE"].resolved_at'
# Output atteso: null

# 2. Passa alert a OK
# Verifica: cat /tmp/ydea_checkmk_tickets.json | jq '.["IP:SERVICE"].resolved_at'
# Output atteso: 1735126800 (timestamp corrente)

# 3. Simula cleanup dopo 5+ giorni
# Modifica manualmente resolved_at a 6 giorni fa
# Esegui: clean_old_cache_entries
# Verifica: ticket rimosso

# 4. Verifica operatore chiude ticket
# Chiudi ticket su Ydea
# Alert CRIT di nuovo
# Verifica: nota aggiunta, no creazione duplicato
```

## File Modificati

- `script-notify-checkmk/ydea_realip` (linee 13-14, 70-100, 145-189, 434-467, 599-622)

## Deploy

```bash
# Backup cache esistente
ssh monitoring@monitor.nethlab.it "cp /tmp/ydea_checkmk_tickets.json /tmp/ydea_checkmk_tickets.json.pre-ttl"

# Deploy script aggiornato
scp script-notify-checkmk/ydea_realip monitoring@monitor.nethlab.it:/opt/omd/sites/monitoring/local/share/check_mk/notifications/

# Verifica deployment
ssh monitoring@monitor.nethlab.it "grep -A5 'mark_ticket_resolved' /opt/omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip"
```

## Monitoraggio Post-Deploy

```bash
# Watch logs per verifiche risoluzione
tail -f /opt/omd/sites/monitoring/var/log/notify.log | grep -E "marcato come risolto|cleanup automatico"

# Check cache periodico
watch -n 300 'cat /tmp/ydea_checkmk_tickets.json | jq "to_entries | map({key: .key, resolved: (.value.resolved_at != null), age_days: ((now - .value.created_at) / 86400 | floor)})"'
```
