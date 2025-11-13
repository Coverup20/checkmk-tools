# 🛠️ Ydea API Toolkit

Sistema completo per la gestione delle API Ydea v2, con focus su creazione e gestione ticket, integrazione con sistemi di monitoraggio, e automazione dei workflow.

## 📋 Indice

- [Caratteristiche](#caratteristiche)
- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Configurazione](#configurazione)
- [Utilizzo](#utilizzo)
- [Esempi Pratici](#esempi-pratici)
- [Integrazione Monitoraggio](#integrazione-monitoraggio)
- [Best Practices](#best-practices)

## ✨ Caratteristiche

- ✅ **Gestione automatica token** con refresh automatico
- ✅ **Funzioni helper** per operazioni comuni sui ticket
- ✅ **Retry automatico** su errori 401
- ✅ **Integrazione sistemi di monitoraggio** (Netdata, custom)
- ✅ **Prevenzione duplicati** tramite cache intelligente
- ✅ **Export dati** in formati CSV/JSON
- ✅ **Logging strutturato** con timestamp e emoji
- ✅ **Script di esempio** per casi d'uso comuni

## 📦 Requisiti

- **bash** >= 4.0
- **curl**
- **jq** (parser JSON)

### Installazione dipendenze

```bash
# Debian/Ubuntu
sudo apt-get install curl jq

# RHEL/CentOS/Fedora
sudo yum install curl jq

# macOS
brew install curl jq
```

## 🚀 Installazione

```bash
# 1. Scarica i file
git clone <repository> ydea-toolkit
cd ydea-toolkit

# 2. Rendi eseguibili gli script
chmod +x ydea-toolkit.sh esempi-ydea.sh ydea-monitoring-integration.sh

# 3. Copia e configura le credenziali
cp .env.example .env
nano .env  # Inserisci YDEA_ID e YDEA_API_KEY
```

## ⚙️ Configurazione

### 1. Ottieni le credenziali API

1. Accedi a [Ydea](https://my.ydea.cloud)
2. Vai su **Impostazioni** → **La mia azienda** → **API**
3. Copia **ID** e **API Key**

### 2. Configura il file .env

```bash
# Credenziali (OBBLIGATORIE)
export YDEA_ID="il_tuo_id_azienda"
export YDEA_API_KEY="la_tua_chiave_api"

# Opzionali
export YDEA_BASE_URL="https://my.ydea.cloud/app_api_v2"
export YDEA_TOKEN_FILE="${HOME}/.ydea_token.json"
export YDEA_DEBUG=0  # Imposta 1 per debug verboso
```

### 3. Carica le variabili

```bash
source .env
```

### 4. Testa la connessione

```bash
./ydea-toolkit.sh login
# Output atteso: ✅ Login effettuato (token valido ~1h)
```

## 📖 Utilizzo

### Comandi Base

```bash
# Login (effettuato automaticamente quando necessario)
./ydea-toolkit.sh login

# Lista ticket
./ydea-toolkit.sh list [limit] [status]

# Dettagli ticket
./ydea-toolkit.sh get <ticket_id>

# Cerca ticket
./ydea-toolkit.sh search "<query>" [limit]

# Crea ticket
./ydea-toolkit.sh create "<titolo>" "<descrizione>" [priorità] [categoria_id]

# Aggiorna ticket
./ydea-toolkit.sh update <ticket_id> '<json_updates>'

# Aggiungi commento
./ydea-toolkit.sh comment <ticket_id> "<testo>"

# Chiudi ticket
./ydea-toolkit.sh close <ticket_id> "<nota>"

# Lista categorie
./ydea-toolkit.sh categories

# Lista utenti
./ydea-toolkit.sh users [limit]

# Chiamata API generica
./ydea-toolkit.sh api <METHOD> </path> [json_body]
```

## 💡 Esempi Pratici

### Esempio 1: Lista ultimi 10 ticket aperti

```bash
./ydea-toolkit.sh list 10 open | jq '.data[] | {id, title, priority}'
```

Output:
```json
{
  "id": 12345,
  "title": "Server non raggiungibile",
  "priority": "high"
}
...
```

### Esempio 2: Crea ticket da script

```bash
#!/bin/bash
RESULT=$(./ydea-toolkit.sh create \
  "Backup fallito su server-prod" \
  "Il backup notturno non è stato completato. Log allegato." \
  "high")

TICKET_ID=$(echo "$RESULT" | jq -r '.id')
echo "Ticket creato: #$TICKET_ID"
```

### Esempio 3: Workflow completo

```bash
# 1. Crea ticket
TICKET=$(./ydea-toolkit.sh create "Manutenzione programmata" "Deploy nuova versione")
ID=$(echo "$TICKET" | jq -r '.id')

# 2. Aggiungi commento
./ydea-toolkit.sh comment "$ID" "Iniziata manutenzione alle $(date)"

# 3. Aggiorna stato
./ydea-toolkit.sh update "$ID" '{"status":"in_progress"}'

# 4. ... esegui operazioni ...

# 5. Chiudi
./ydea-toolkit.sh close "$ID" "Manutenzione completata con successo"
```

### Esempio 4: Report giornaliero via email

```bash
#!/bin/bash
{
  echo "=== REPORT TICKET GIORNALIERO ==="
  echo ""
  echo "Ticket APERTI:"
  ./ydea-toolkit.sh list 100 open | jq -r '.data[] | "  - #\(.id): \(.title)"'
  echo ""
  echo "Ticket CHIUSI OGGI:"
  ./ydea-toolkit.sh list 50 closed | jq -r '.data[] | select(.closed_at | startswith("2025-11-11")) | "  - #\(.id): \(.title)"'
} | mail -s "Report Ydea $(date +%Y-%m-%d)" admin@example.com
```

### Esempio 5: Export in CSV

```bash
./ydea-toolkit.sh list 1000 | jq -r '
  ["ID","Titolo","Status","Priorità","Data"] as $headers |
  ($headers | @csv),
  (.data[] | [.id, .title, .status, .priority, .created_at] | @csv)
' > tickets_export.csv
```

## 🔧 Integrazione Monitoraggio

### Monitoring Automatico

Lo script `ydea-monitoring-integration.sh` crea automaticamente ticket quando rileva problemi:

```bash
# Monitoring completo (CPU, RAM, Disk)
./ydea-monitoring-integration.sh monitor

# Monitora servizio specifico
./ydea-monitoring-integration.sh service nginx
./ydea-monitoring-integration.sh service postgresql
```

### Configurazione CRON

```bash
# Aggiungi a crontab -e
*/5 * * * * cd /path/to/ydea-toolkit && ./ydea-monitoring-integration.sh monitor >> /var/log/ydea-monitor.log 2>&1

# Monitora servizi critici ogni minuto
* * * * * cd /path/to/ydea-toolkit && ./ydea-monitoring-integration.sh service nginx >> /var/log/ydea-monitor.log 2>&1
```

### Integrazione Netdata

1. Configura Netdata per inviare notifiche custom:

```bash
# /etc/netdata/health_alarm_notify.conf
SEND_CUSTOM="YES"
DEFAULT_RECIPIENT_CUSTOM="ydea"

# Script di notifica custom
cat > /usr/local/bin/netdata-to-ydea.sh << 'EOF'
#!/bin/bash
cd /path/to/ydea-toolkit
source .env

cat << JSON | ./ydea-monitoring-integration.sh netdata-webhook
{
  "alarm": "${alarm}",
  "status": "${status}",
  "hostname": "${host}",
  "value": "${value}",
  "chart": "${chart}",
  "info": "${info}"
}
JSON
EOF

chmod +x /usr/local/bin/netdata-to-ydea.sh
```

2. Riavvia Netdata:

```bash
sudo systemctl restart netdata
```

### Alert da Script Custom

```bash
#!/bin/bash
# check-website.sh - Verifica disponibilità sito

SITE="https://example.com"
if ! curl -f -s -o /dev/null "$SITE"; then
  cd /path/to/ydea-toolkit
  source .env
  
  ./ydea-toolkit.sh create \
    "[ALERT] Sito $SITE non raggiungibile" \
    "Il sito web non risponde. Verificare server e DNS." \
    "critical"
fi
```

## 📚 Script di Esempio Inclusi

### esempi-ydea.sh

Script interattivo con menu che dimostra:

1. **Report giornaliero ticket**
2. **Creazione ticket da alert**
3. **Ricerca e aggiornamento**
4. **Workflow completo**
5. **Export CSV**

Uso:
```bash
# Menu interattivo
./esempi-ydea.sh --menu

# O esegui singole funzioni
source esempi-ydea.sh
esempio_report_giornaliero
esempio_workflow_completo
```

## 🎯 Best Practices

### 1. Gestione Token

Il token viene salvato in `~/.ydea_token.json` e rinnovato automaticamente. Non serve fare login manualmente ogni volta.

### 2. Prevenzione Duplicati

Per alert automatici, usa la cache integrata nel monitoring script per evitare ticket duplicati:

```bash
# La cache in /tmp/ydea_tickets_cache.json traccia gli alert aperti
# Viene pulita automaticamente dopo 24h
./ydea-monitoring-integration.sh cleanup  # pulizia manuale
```

### 3. Priorità Ticket

Usa le priorità in modo coerente:
- `critical` - Servizi down, dataloss
- `high` - Performance degradate, alert critici
- `normal` - Manutenzione programmata, richieste standard
- `low` - Miglioramenti, documentazione

### 4. Descrizioni Strutturate

Usa markdown nelle descrizioni per maggiore leggibilità:

```bash
./ydea-toolkit.sh create "Alert CPU" "
## Dettagli Alert
- Host: server-01
- CPU: 95%
- Soglia: 80%

## Diagnostica
\`\`\`
top -bn1 | head -20
\`\`\`

## Azioni
1. Verificare processi
2. Controllare log
3. Valutare scaling
"
```

### 5. Logging

Abilita debug per troubleshooting:

```bash
export YDEA_DEBUG=1
./ydea-toolkit.sh list
```

### 6. Error Handling

Gestisci sempre gli errori negli script:

```bash
if RESULT=$(./ydea-toolkit.sh create "..." "..." 2>&1); then
  TICKET_ID=$(echo "$RESULT" | jq -r '.id')
  echo "✅ Ticket #$TICKET_ID creato"
else
  echo "❌ Errore: $RESULT" >&2
  # Invia notifica, scrivi log, etc.
fi
```

## 🔐 Sicurezza

- **Mai committare** il file `.env` con credenziali
- Usa permessi restrittivi: `chmod 600 .env`
- Il token file ha permessi `644` di default
- Considera l'uso di vault per produzione (Hashicorp Vault, AWS Secrets Manager)

## 🐛 Troubleshooting

### Login fallisce

```bash
# Verifica credenziali
echo "ID: $YDEA_ID"
echo "API_KEY: ${YDEA_API_KEY:0:10}..."

# Test con curl diretto
curl -X POST https://my.ydea.cloud/app_api_v2/login \
  -H "Content-Type: application/json" \
  -d "{\"id\":\"$YDEA_ID\",\"api_key\":\"$YDEA_API_KEY\"}"
```

### Token scade subito

```bash
# Verifica orologio sistema
date -u
# Deve essere sincronizzato con NTP
```

### Errori jq

```bash
# Verifica installazione jq
jq --version

# Test parsing
echo '{"test": "value"}' | jq .
```

## 📞 Supporto

- **Documentazione API Ydea**: https://my.ydea.cloud/api/doc/v2
- **Issues**: Apri una issue su GitHub
- **Email**: support@example.com

## 📝 Licenza

MIT License - Vedi file LICENSE

## 🙏 Contributi

I contributi sono benvenuti! Per favore:

1. Fork del repository
2. Crea branch per feature (`git checkout -b feature/nuova-funzione`)
3. Commit modifiche (`git commit -am 'Aggiunta nuova funzione'`)
4. Push al branch (`git push origin feature/nuova-funzione`)
5. Apri Pull Request

## 📈 Roadmap

- [ ] Supporto webhook bidirezionale
- [ ] Dashboard web per visualizzazione ticket
- [ ] Integrazione con Slack/Teams
- [ ] Template ticket predefiniti
- [ ] Reportistica avanzata
- [ ] Supporto allegati
- [ ] CLI interattiva con autocompletamento

---

**Versione**: 1.0.0  
**Ultimo aggiornamento**: 2025-11-11  
**Autore**: Marzio
