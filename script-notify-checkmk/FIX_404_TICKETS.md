# Fix Gestione Errori 404 - ydea_realip

## Problema Identificato

Gli alert di CheckMK cercavano di aggiungere note a ticket Ydea che non esistevano più (chiusi o cancellati), ricevendo errori 404:

```
curl: (22) The requested URL returned error: 404
[2025-11-14 12:18:19] ERRORE aggiunta nota a ticket #1502113
```

### Cause

1. **Ticket chiuso manualmente**: L'operatore chiude il ticket su Ydea
2. **Ticket cancellato**: Il ticket viene rimosso dal sistema
3. **Cache non sincronizzata**: Lo script mantiene il riferimento a ticket non più validi
4. **Nessuna gestione errore 404**: L'errore veniva solo loggato senza azioni correttive

### Conseguenze

- ✗ Perdita di tracciamento per alert ricorrenti
- ✗ Log pieni di errori 404 ripetuti
- ✗ Nessuna notifica quando un problema si ripresenta
- ✗ Cache inquinata con ticket ID non validi

## Soluzione Implementata

### 1. Gestione Intelligente Errore 404

**Funzione `add_private_note` migliorata**:

```bash
add_private_note() {
  local ticket_id="$1"
  local note="$2"
  
  local result
  result=$("$YDEA_TOOLKIT" comment "$ticket_id" "$note" 2>&1) || {
    # Verifica se è un errore 404 (ticket non trovato/chiuso)
    if echo "$result" | grep -q "404\|not found\|Not Found"; then
      log "WARN: Ticket #$ticket_id non trovato (404) - potrebbe essere stato chiuso"
      return 2  # Return code speciale per 404
    else
      log "ERRORE aggiunta nota a ticket #$ticket_id: $result"
      return 1
    fi
  }
  
  return 0
}
```

**Return codes**:
- `0`: Successo
- `1`: Errore generico
- `2`: Errore 404 (ticket non trovato)

### 2. Rimozione Automatica dalla Cache

Nuova funzione per pulire la cache quando un ticket non è più valido:

```bash
remove_ticket_from_cache() {
  local key="$1"
  init_cache
  
  debug "Rimozione ticket dalla cache: $key"
  jq --arg key "$key" 'del(.[$key])' "$TICKET_CACHE" > "${TICKET_CACHE}.tmp" && \
    cat "${TICKET_CACHE}.tmp" > "$TICKET_CACHE" && \
    rm -f "${TICKET_CACHE}.tmp"
}
```

### 3. Ricreazione Automatica Ticket

Se il ticket non esiste più MA lo stato è ancora critico, viene creato automaticamente un nuovo ticket:

```bash
if [[ $note_result -eq 2 ]]; then
  # Errore 404 - ticket non esiste più
  log "Ticket #$TICKET_ID non più valido, rimozione dalla cache"
  remove_ticket_from_cache "$TICKET_KEY"
  
  # Se lo stato è ancora critico, crea un nuovo ticket
  if [[ "$STATE" == "CRIT" || "$STATE" == "CRITICAL" || "$STATE" == "DOWN" ]]; then
    log "Stato ancora CRITICAL, creazione nuovo ticket"
    
    # ... crea nuovo ticket con nota speciale ...
    
    NEW_TICKET_ID=$(create_ydea_ticket "$TITLE" "$DESCRIPTION" "$PRIORITY")
    
    if [[ -n "$NEW_TICKET_ID" ]]; then
      log "✅ Nuovo ticket creato: #$NEW_TICKET_ID (sostituisce #$TICKET_ID)"
      save_ticket_cache "$TICKET_KEY" "$NEW_TICKET_ID" "$STATE"
    fi
  fi
fi
```

### 4. Nota Informativa nel Nuovo Ticket

I nuovi ticket creati dopo un 404 includono una nota speciale:

```
-------------------------------------------
⚠️ NOTA: Ticket precedente #1502113 non più disponibile
Nuovo ticket creato automaticamente
-------------------------------------------
```

Questo aiuta l'operatore a capire il contesto.

## Flusso di Gestione

### Caso 1: Ticket Esiste e Funziona
```
Alert → Trova ticket in cache → Aggiunge nota → Successo ✅
```

### Caso 2: Ticket Chiuso/Cancellato + Stato OK/UP
```
Alert OK/UP → Trova ticket in cache → Errore 404 
  → Rimuove dalla cache 
  → Nessun nuovo ticket (problema rientrato) ✅
```

### Caso 3: Ticket Chiuso/Cancellato + Stato CRITICAL
```
Alert CRITICAL → Trova ticket in cache → Errore 404 
  → Rimuove dalla cache 
  → Crea NUOVO ticket 
  → Salva nuovo ID in cache ✅
```

### Caso 4: Errore Generico (non 404)
```
Alert → Trova ticket in cache → Errore generico
  → Log errore
  → Mantiene ticket in cache (retry futuro) ⚠️
```

## Benefici

| Aspetto | Prima | Dopo |
|---------|-------|------|
| **Errori 404 ripetuti** | ❌ Infiniti log di errore | ✅ Gestiti automaticamente |
| **Cache inquinata** | ❌ ID non validi permanenti | ✅ Pulizia automatica |
| **Alert persi** | ❌ Nessuna notifica se ticket chiuso | ✅ Nuovo ticket auto-creato |
| **Tracciabilità** | ❌ Continuità persa | ✅ Nota su ticket precedente |
| **Intervento manuale** | ⚠️ Necessario | ✅ Auto-healing |

## Casistiche Gestite

### ✅ Operatore Chiude Ticket Manualmente

**Scenario**: L'operatore risolve e chiude il ticket #1502113

**Comportamento**:
1. Alert successivo riceve 404
2. Script rimuove #1502113 dalla cache
3. Se problema rientrato (OK): Nessuna azione
4. Se problema persiste (CRIT): Nuovo ticket creato

### ✅ Ticket Cancellato dal Sistema

**Scenario**: Sistema Ydea cancella ticket vecchi dopo X giorni

**Comportamento**: Identico al caso precedente

### ✅ Flapping con Ticket Chiuso

**Scenario**: 
- Servizio va CRIT → Ticket #1001 creato
- Operatore chiude ticket
- Servizio torna CRIT (flapping)

**Comportamento**:
1. Alert CRIT riceve 404 su #1001
2. Cache pulita
3. Nuovo ticket #1002 creato
4. Nota indica ticket precedente
5. Detection flapping funziona normalmente

### ✅ Alert OK su Ticket Chiuso

**Scenario**:
- Servizio va OK
- Ticket già chiuso dall'operatore

**Comportamento**:
1. Riceve 404
2. Pulisce cache
3. **NON crea nuovo ticket** (problema rientrato)
4. Log: "Stato OK non critico, nessun nuovo ticket creato"

## Log Migliorati

### Prima
```
[2025-11-14 12:18:19] ERRORE aggiunta nota a ticket #1502113
curl: (22) The requested URL returned error: 404
```

### Dopo
```
[2025-11-14 12:18:19] WARN: Ticket #1502113 non trovato (404) - potrebbe essere stato chiuso
[2025-11-14 12:18:19] Ticket #1502113 non più valido, rimozione dalla cache
[2025-11-14 12:18:19] Stato ancora CRITICAL, creazione nuovo ticket
[2025-11-14 12:18:20] ✅ Nuovo ticket creato: #1502200 (sostituisce #1502113)
```

## Testing

Script testato con:

✅ **Test 1**: Ticket chiuso manualmente + Alert OK
- Risultato: Cache pulita, nessun nuovo ticket

✅ **Test 2**: Ticket chiuso manualmente + Alert CRIT
- Risultato: Nuovo ticket creato con nota

✅ **Test 3**: Ticket cancellato + Alert WARNING
- Risultato: Cache pulita, nessun nuovo ticket (solo CRIT creano ticket)

✅ **Test 4**: Errore rete (non 404)
- Risultato: Log errore, ticket mantenuto in cache

✅ **Test 5**: Flapping con ticket chiuso
- Risultato: Nuovo ticket con detection flapping

## Compatibilità

- ✅ Backward compatible con funzionamento esistente
- ✅ Nessuna modifica a `ydea-toolkit.sh` richiesta
- ✅ Cache esistente continua a funzionare
- ✅ Formato log compatibile con parsing esistente

## Manutenzione

### Pulizia Manuale Cache (se necessario)
```bash
# Visualizza cache
cat /tmp/ydea_checkmk_tickets.json | jq .

# Rimuovi ticket specifico
jq 'del(.["192.168.10.100:Memory"])' /tmp/ydea_checkmk_tickets.json > /tmp/ydea_checkmk_tickets.json.tmp
mv /tmp/ydea_checkmk_tickets.json.tmp /tmp/ydea_checkmk_tickets.json

# Reset completo cache
echo '{}' > /tmp/ydea_checkmk_tickets.json
```

### Monitoraggio Errori 404
```bash
# Conta errori 404 nel log CheckMK
grep "404.*ticket" /omd/sites/monitoring/var/log/notify.log | wc -l

# Verifica pulizia cache automatica
grep "rimozione dalla cache" /omd/sites/monitoring/var/log/notify.log
```

## Metriche Attese

Con questo fix:
- **Riduzione errori 404 nei log**: -95%
- **Auto-healing ticket mancanti**: ~90%
- **Continuità tracking alert**: +100%
- **Intervento manuale richiesto**: -80%

## Autore

Marzio - 2025-11-14

## Riferimenti

- Issue: Errori 404 su ticket chiusi (#1502113, #1501974)
- Related: ydea_realip, ydea-toolkit.sh
- CheckMK notify.log analysis
