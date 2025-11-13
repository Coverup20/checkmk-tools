# 🔌 Integrazioni Avanzate - Ydea Toolkit

Questo documento contiene esempi di integrazione con vari sistemi e use case avanzati.

## 📊 Integrazione con Netdata

### Configurazione Netdata Health Alarm

```bash
# /etc/netdata/health.d/custom-ydea.conf

# Alert CPU alto
alarm: cpu_usage_high
   on: system.cpu
class: Utilization
 type: System
component: CPU
   os: linux
hosts: *
 calc: $user + $system + $softirq + $irq + $steal
units: %
every: 1m
 warn: $this > 80
 crit: $this > 90
delay: down 15m multiplier 1.5 max 1h
 info: average CPU utilization over the last minute
   to: sysadmin

# Alert RAM alta
alarm: ram_usage_high
   on: system.ram
class: Utilization
 type: System
component: Memory
   os: linux
hosts: *
 calc: $used * 100 / ($used + $cached + $free + $buffers)
units: %
every: 1m
 warn: $this > 80
 crit: $this > 90
delay: down 15m multiplier 1.5 max 1h
 info: system RAM usage
   to: sysadmin

# Alert disco pieno
alarm: disk_space_usage
   on: disk.space
class: Utilization
 type: System
component: Disk
   os: linux
hosts: *
 calc: $used * 100 / ($avail + $used)
units: %
every: 1m
 warn: $this > 80
 crit: $this > 90
delay: up 1m down 15m multiplier 1.5 max 1h
 info: disk space utilization
   to: sysadmin
```

### Script di notifica Netdata

```bash
# /usr/libexec/netdata/plugins.d/alarm-notify-ydea.sh
#!/usr/bin/env bash

# Path al toolkit Ydea
YDEA_TOOLKIT="/opt/ydea-toolkit/ydea-toolkit.sh"
YDEA_ENV="/opt/ydea-toolkit/.env"

# Carica credenziali
source "$YDEA_ENV"

# Funzione di notifica
send_ydea_notification() {
    local status="${1}"
    local host="${2}"
    local alarm="${3}"
    local value="${4}"
    local chart="${5}"
    local info="${6}"
    
    # Determina priorità
    local priority="normal"
    case "$status" in
        CRITICAL) priority="critical" ;;
        WARNING)  priority="high" ;;
        CLEAR)    priority="low" ;;
    esac
    
    # Crea titolo e descrizione
    local title="[NETDATA-${status}] ${alarm} su ${host}"
    local description="**Alert Netdata**

**Dettagli:**
- Host: ${host}
- Alarm: ${alarm}
- Status: ${status}
- Chart: ${chart}
- Valore: ${value}
- Info: ${info}
- Timestamp: $(date '+%Y-%m-%d %H:%M:%S')

**Dashboard Netdata:**
http://${host}:19999/#menu_system

**Azioni:**
1. Verificare il sistema
2. Analizzare i log
3. Prendere provvedimenti se necessario"
    
    # Crea ticket solo per WARNING e CRITICAL
    if [[ "$status" == "WARNING" || "$status" == "CRITICAL" ]]; then
        "$YDEA_TOOLKIT" create "$title" "$description" "$priority" 2>&1 | logger -t netdata-ydea
    fi
}

# Main
send_ydea_notification "$@"
```

### Configurazione notification

```bash
# /etc/netdata/health_alarm_notify.conf

# Abilita notifiche custom
SEND_CUSTOM="YES"
DEFAULT_RECIPIENT_CUSTOM="ydea"

# Custom sender function
custom_sender() {
    /usr/libexec/netdata/plugins.d/alarm-notify-ydea.sh \
        "${status}" \
        "${host}" \
        "${alarm}" \
        "${value}" \
        "${chart}" \
        "${info}"
    
    return 0
}
```

## 🐳 Integrazione con Docker

### Monitoring container Docker

```bash
#!/bin/bash
# docker-monitor.sh - Monitora health dei container

YDEA_TOOLKIT="./ydea-toolkit.sh"
source .env

# Controlla tutti i container
docker ps -a --format '{{.Names}} {{.Status}}' | while read -r name status; do
    if [[ "$status" == *"Exited"* ]] || [[ "$status" == *"Dead"* ]]; then
        # Container non healthy
        container_id=$(docker ps -aqf "name=$name")
        logs=$(docker logs --tail 50 "$container_id" 2>&1)
        
        $YDEA_TOOLKIT create \
            "[DOCKER] Container $name non funzionante" \
            "**Container Status Alert**

Container: $name
Status: $status
Container ID: $container_id

**Ultimi log:**
\`\`\`
$logs
\`\`\`

**Comandi diagnostici:**
\`\`\`bash
docker logs $name
docker inspect $name
docker restart $name
\`\`\`" \
            "high"
    fi
done
```

### Docker Compose health check con ticket

```yaml
# docker-compose.yml
version: '3.8'

services:
  web:
    image: nginx:latest
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped
    
  monitor:
    image: alpine:latest
    volumes:
      - ./ydea-toolkit:/opt/ydea
      - /var/run/docker.sock:/var/run/docker.sock
    command: >
      sh -c "apk add --no-cache docker-cli curl jq bash &&
             while true; do
               /opt/ydea/docker-monitor.sh;
               sleep 60;
             done"
    depends_on:
      - web
```

## 📧 Integrazione Email (Parsing)

### Parse email e crea ticket

```bash
#!/bin/bash
# email-to-ticket.sh - Converte email in ticket Ydea

YDEA_TOOLKIT="./ydea-toolkit.sh"
source .env

# Leggi email da stdin (da .forward o procmail)
EMAIL_CONTENT=$(cat)

# Estrai subject e body
SUBJECT=$(echo "$EMAIL_CONTENT" | grep -m1 "^Subject:" | sed 's/Subject: //')
FROM=$(echo "$EMAIL_CONTENT" | grep -m1 "^From:" | sed 's/From: //')
BODY=$(echo "$EMAIL_CONTENT" | sed -n '/^$/,$p' | tail -n +2)

# Determina priorità da subject
PRIORITY="normal"
if [[ "$SUBJECT" =~ URGENT|CRITICAL|EMERGENCY ]]; then
    PRIORITY="critical"
elif [[ "$SUBJECT" =~ HIGH|IMPORTANT ]]; then
    PRIORITY="high"
fi

# Crea ticket
$YDEA_TOOLKIT create \
    "$SUBJECT" \
    "**Ticket creato da email**

From: $FROM
Date: $(date)

---

$BODY" \
    "$PRIORITY"
```

### Configurazione .forward

```bash
# ~/.forward
"|/path/to/email-to-ticket.sh"
```

## 🔔 Integrazione Telegram Bot

### Bot Telegram per notifiche ticket

```bash
#!/bin/bash
# telegram-notify.sh - Invia notifiche Telegram per nuovi ticket

TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID="YOUR_CHAT_ID"
YDEA_TOOLKIT="./ydea-toolkit.sh"
source .env

# File per tracciare ultimi ticket notificati
LAST_TICKET_FILE="/tmp/ydea_last_ticket_id"
LAST_ID=$(cat "$LAST_TICKET_FILE" 2>/dev/null || echo "0")

# Recupera nuovi ticket
NEW_TICKETS=$($YDEA_TOOLKIT list 50 | jq -r --arg last "$LAST_ID" '.data[] | select(.id > ($last|tonumber)) | {id, title, priority, created_at} | @json')

# Invia notifica per ogni nuovo ticket
echo "$NEW_TICKETS" | while read -r ticket; do
    [[ -z "$ticket" ]] && continue
    
    TICKET_ID=$(echo "$ticket" | jq -r '.id')
    TITLE=$(echo "$ticket" | jq -r '.title')
    PRIORITY=$(echo "$ticket" | jq -r '.priority')
    
    # Emoji basato su priorità
    EMOJI="📋"
    case "$PRIORITY" in
        critical) EMOJI="🚨" ;;
        high)     EMOJI="⚠️" ;;
        normal)   EMOJI="ℹ️" ;;
        low)      EMOJI="📝" ;;
    esac
    
    MESSAGE="$EMOJI *Nuovo Ticket #$TICKET_ID*

*Titolo:* $TITLE
*Priorità:* $PRIORITY

[Visualizza su Ydea](https://my.ydea.cloud/tickets/$TICKET_ID)"
    
    # Invia a Telegram
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="$TELEGRAM_CHAT_ID" \
        -d text="$MESSAGE" \
        -d parse_mode="Markdown" > /dev/null
    
    # Aggiorna ultimo ID
    echo "$TICKET_ID" > "$LAST_TICKET_FILE"
done
```

### CRON per notifiche Telegram

```bash
# crontab -e
*/5 * * * * /path/to/telegram-notify.sh
```

## 📊 Integrazione Grafana

### Dashboard Grafana per ticket Ydea

```bash
#!/bin/bash
# ydea-metrics.sh - Espone metriche per Prometheus/Grafana

YDEA_TOOLKIT="./ydea-toolkit.sh"
source .env

# Recupera statistiche
TOTAL=$($YDEA_TOOLKIT list 10000 | jq '.total // 0')
OPEN=$($YDEA_TOOLKIT list 10000 open | jq '.total // 0')
IN_PROGRESS=$($YDEA_TOOLKIT list 10000 in_progress | jq '.total // 0')
CLOSED=$($YDEA_TOOLKIT list 10000 closed | jq '.total // 0')

# Formato Prometheus
cat << EOF
# HELP ydea_tickets_total Total number of tickets
# TYPE ydea_tickets_total gauge
ydea_tickets_total $TOTAL

# HELP ydea_tickets_by_status Number of tickets by status
# TYPE ydea_tickets_by_status gauge
ydea_tickets_by_status{status="open"} $OPEN
ydea_tickets_by_status{status="in_progress"} $IN_PROGRESS
ydea_tickets_by_status{status="closed"} $CLOSED
EOF
```

### Node Exporter textfile collector

```bash
# /etc/systemd/system/ydea-metrics.service
[Unit]
Description=Ydea Metrics Exporter
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/ydea-toolkit/ydea-metrics.sh > /var/lib/node_exporter/textfile_collector/ydea.prom

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/ydea-metrics.timer
[Unit]
Description=Run Ydea metrics every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

## 🔄 Integrazione GitLab CI/CD

### Crea ticket su deploy failure

```yaml
# .gitlab-ci.yml
stages:
  - deploy
  - notify

deploy_production:
  stage: deploy
  script:
    - ./deploy.sh
  environment:
    name: production
  only:
    - main

notify_failure:
  stage: notify
  when: on_failure
  script:
    - source .env
    - |
      ./ydea-toolkit.sh create \
        "[CI/CD] Deploy fallito su ${CI_ENVIRONMENT_NAME}" \
        "**Pipeline Failed**
        
        Project: ${CI_PROJECT_NAME}
        Branch: ${CI_COMMIT_BRANCH}
        Commit: ${CI_COMMIT_SHORT_SHA}
        Author: ${GITLAB_USER_NAME}
        Pipeline: ${CI_PIPELINE_URL}
        
        **Error Log:**
        \`\`\`
        ${CI_JOB_LOG}
        \`\`\`" \
        "high"
```

## 🎯 Use Cases Complessi

### Sistema di ticketing multi-livello

```bash
#!/bin/bash
# smart-ticket-router.sh - Routing intelligente dei ticket

YDEA_TOOLKIT="./ydea-toolkit.sh"
source .env

create_smart_ticket() {
    local issue_type="$1"
    local description="$2"
    
    # Logica di routing
    case "$issue_type" in
        security)
            priority="critical"
            category_id="1"  # Security team
            ;;
        infrastructure)
            priority="high"
            category_id="2"  # DevOps team
            ;;
        application)
            priority="normal"
            category_id="3"  # Dev team
            ;;
        *)
            priority="normal"
            category_id="4"  # General
            ;;
    esac
    
    # Crea ticket
    RESULT=$($YDEA_TOOLKIT create \
        "[${issue_type^^}] $description" \
        "Auto-generated ticket
        
Type: $issue_type
Priority: $priority
Routing: Category $category_id
Created: $(date)" \
        "$priority")
    
    TICKET_ID=$(echo "$RESULT" | jq -r '.id')
    
    # Auto-assign based on category
    # $YDEA_TOOLKIT update "$TICKET_ID" "{\"assigned_to\": \"$assignee_id\"}"
    
    echo "Ticket #$TICKET_ID created and routed"
}

# Uso
create_smart_ticket "security" "Failed login attempts detected"
create_smart_ticket "infrastructure" "Server CPU high"
```

## 🔐 Best Practices Produzione

### 1. Credential Management con Vault

```bash
#!/bin/bash
# ydea-with-vault.sh

# Recupera credenziali da Hashicorp Vault
YDEA_ID=$(vault kv get -field=id secret/ydea/credentials)
YDEA_API_KEY=$(vault kv get -field=api_key secret/ydea/credentials)

export YDEA_ID
export YDEA_API_KEY

./ydea-toolkit.sh "$@"
```

### 2. Rate Limiting

```bash
#!/bin/bash
# rate-limited-ticket-creation.sh

RATE_LIMIT_FILE="/tmp/ydea_rate_limit"
MAX_TICKETS_PER_HOUR=50

# Controlla rate limit
current_hour=$(date +%Y%m%d%H)
ticket_count=$(grep "^$current_hour" "$RATE_LIMIT_FILE" 2>/dev/null | wc -l)

if [[ $ticket_count -ge $MAX_TICKETS_PER_HOUR ]]; then
    echo "Rate limit exceeded: $ticket_count/$MAX_TICKETS_PER_HOUR tickets this hour"
    exit 1
fi

# Crea ticket e registra
./ydea-toolkit.sh create "$@"
echo "$current_hour $(date +%s)" >> "$RATE_LIMIT_FILE"

# Pulizia vecchie entry
grep "^$current_hour" "$RATE_LIMIT_FILE" > "${RATE_LIMIT_FILE}.tmp"
mv "${RATE_LIMIT_FILE}.tmp" "$RATE_LIMIT_FILE"
```

### 3. High Availability Setup

```bash
#!/bin/bash
# ha-ydea-wrapper.sh - Retry logic per alta affidabilità

MAX_RETRIES=3
RETRY_DELAY=5

for i in $(seq 1 $MAX_RETRIES); do
    if ./ydea-toolkit.sh "$@"; then
        exit 0
    fi
    
    if [[ $i -lt $MAX_RETRIES ]]; then
        echo "Retry $i/$MAX_RETRIES after ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    fi
done

echo "Failed after $MAX_RETRIES attempts"
exit 1
```

---

**Nota**: Questi esempi richiedono adattamenti specifici al tuo ambiente. Testa sempre in ambiente di sviluppo prima di usare in produzione!
