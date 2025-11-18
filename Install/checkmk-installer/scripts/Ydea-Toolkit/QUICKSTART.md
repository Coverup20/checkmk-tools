# 🚀 Quick Start Guide - Ydea Toolkit

## Setup Rapido (5 minuti)

### 1. Installa dipendenze

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y curl jq

# RHEL/CentOS
sudo yum install -y curl jq
```

### 2. Configura credenziali

```bash
# Crea file .env
cat > .env << 'EOF'
export YDEA_ID="TUO_ID_QUI"
export YDEA_API_KEY="TUA_API_KEY_QUI"
EOF

# Carica credenziali
source .env
```

### 3. Test connessione

```bash
# Rendi eseguibile
chmod +x ydea-toolkit.sh

# Test login
./ydea-toolkit.sh login
# Output atteso: ✅ Login effettuato (token valido ~1h)
```

## 📋 Comandi Essenziali

### Lista ticket
```bash
# Ultimi 20 ticket
./ydea-toolkit.sh list

# Solo ticket aperti
./ydea-toolkit.sh list 50 open

# Con formato leggibile
./ydea-toolkit.sh list 10 | jq '.data[] | {id, title, status}'
```

### Crea ticket
```bash
# Ticket semplice
./ydea-toolkit.sh create "Titolo ticket" "Descrizione dettagliata"

# Con priorità alta
./ydea-toolkit.sh create "Server down" "Descrizione" "high"

# Salva ID ticket creato
TICKET=$(./ydea-toolkit.sh create "Test" "Desc")
TICKET_ID=$(echo "$TICKET" | jq -r '.id')
echo "Creato ticket #$TICKET_ID"
```

### Gestisci ticket
```bash
# Visualizza dettagli
./ydea-toolkit.sh get 12345

# Aggiungi commento
./ydea-toolkit.sh comment 12345 "Ho risolto il problema"

# Aggiorna stato
./ydea-toolkit.sh update 12345 '{"status":"in_progress"}'

# Chiudi ticket
./ydea-toolkit.sh close 12345 "Problema risolto"
```

### Cerca ticket
```bash
# Cerca per parola chiave
./ydea-toolkit.sh search "database" | jq '.data[] | {id, title}'

# Cerca con più risultati
./ydea-toolkit.sh search "errore" 50
```

## 🎯 Casi d'Uso Comuni

### 1. Alert Automatico da Script

```bash
#!/bin/bash
# Esempio: monitora sito web

SITE="https://example.com"
if ! curl -f -s "$SITE" > /dev/null; then
    ./ydea-toolkit.sh create \
        "[ALERT] Sito $SITE down" \
        "Il sito non risponde. Verificare server." \
        "critical"
fi
```

### 2. Report Giornaliero

```bash
#!/bin/bash
# report-giornaliero.sh

source .env

echo "=== REPORT TICKET $(date +%Y-%m-%d) ==="
echo ""
echo "Ticket APERTI:"
./ydea-toolkit.sh list 100 open | jq -r '.data[] | "  #\(.id) - \(.title)"'
echo ""
echo "Ticket CHIUSI OGGI:"
./ydea-toolkit.sh list 50 closed | jq -r '.data[] | select(.closed_at | startswith("'$(date +%Y-%m-%d)'")) | "  #\(.id) - \(.title)"'
```

### 3. Monitoring con CRON

```bash
# Aggiungi a crontab -e

# Monitoring sistema ogni 5 minuti
*/5 * * * * cd /path/to/ydea-toolkit && ./ydea-monitoring-integration.sh monitor >> /var/log/ydea.log 2>&1

# Report giornaliero alle 9:00
0 9 * * * cd /path/to/ydea-toolkit && ./report-giornaliero.sh | mail -s "Report Ydea" admin@example.com
```

## 🔧 Troubleshooting Veloce

### Login non funziona
```bash
# Verifica credenziali
echo "ID: $YDEA_ID"
echo "API_KEY (primi 10 caratteri): ${YDEA_API_KEY:0:10}..."

# Se vuoti, ricarica .env
source .env
```

### jq non trovato
```bash
# Installa jq
sudo apt-get install jq  # Ubuntu/Debian
sudo yum install jq      # RHEL/CentOS
```

### Permesso negato
```bash
# Rendi eseguibili gli script
chmod +x *.sh
```

### Debug
```bash
# Abilita output verboso
export YDEA_DEBUG=1
./ydea-toolkit.sh list
```

## 📚 Risorse

- **README completo**: Leggi `README.md` per documentazione dettagliata
- **Esempi**: Esegui `./esempi-ydea.sh --menu` per esempi interattivi
- **Template**: Usa `./ydea-templates.sh` per ticket predefiniti
- **API Ydea**: https://my.ydea.cloud/api/doc/v2

## 💡 Suggerimenti

1. **Sempre source .env** prima di usare gli script
2. **Usa jq** per formattare l'output JSON
3. **Abilita debug** se qualcosa non funziona
4. **Backup .env** in un posto sicuro (MAI commitarlo su git!)
5. **Controlla log** in `/var/log/ydea*.log` per troubleshooting

## 🎉 Prossimi Passi

1. ✅ Setup completato
2. 📖 Leggi il README completo
3. 🧪 Prova gli esempi interattivi
4. 🔧 Configura monitoring automatico
5. 📊 Crea report personalizzati

---

**Hai bisogno di aiuto?** Apri un ticket... con Ydea! 😉
