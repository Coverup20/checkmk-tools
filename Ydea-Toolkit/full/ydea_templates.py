#!/usr/bin/env python3
"""
ydea_templates.py - Template predefiniti per ticket Ydea

Genera JSON per creazione ticket tramite API Ydea con template predefiniti
per vari scenari: infrastruttura, applicazioni, sicurezza, manutenzione.

Usage:
    ydea_templates.py server-down <hostname> [service]
    ydea_templates.py disk-full <hostname> <mount_point> <usage_%>
    ydea_templates.py app-errors <app_name> <error_rate_%> [threshold]
    
Examples:
    ydea_templates.py server-down web-prod-01 nginx
    ydea_templates.py disk-full server-01 /var 92

Version: 1.0.0 (convertito da Bash)
"""

VERSION = "1.0.0"

import sys
import json
from datetime import datetime, timedelta
from typing import Dict, Any


# ===== TEMPLATE INFRASTRUTTURA =====

def template_server_down(hostname: str, service: str = "N/A") -> Dict[str, Any]:
    """Template per server non raggiungibile"""
    return {
        "title": f"[CRITICAL] Server {hostname} non raggiungibile",
        "description": f""" Server Down Alert

**Dettagli:**
- Hostname: {hostname}
- Servizio: {service}
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Rilevato da: Sistema di monitoraggio automatico

**Impatto:**
- [ ] Servizio completamente offline
- [ ] Performance degradate
- [ ] Accesso limitato

**Azioni immediate:**
1. Verificare connettività di rete
2. Controllare status hardware
3. Verificare log di sistema
4. Tentare restart se appropriato

**Comandi diagnostici:**
```bash
ping {hostname}
ssh {hostname} 'uptime; systemctl status'
journalctl -xe
```

**Priority:** CRITICAL
**SLA:** 15 minuti""",
        "priority": "critical",
        "tags": ["infrastruttura", "downtime", "server"]
    }


def template_backup_failed(backup_job: str, error_msg: str = "Unknown error") -> Dict[str, Any]:
    """Template per backup fallito"""
    return {
        "title": f"[HIGH] Backup fallito: {backup_job}",
        "description": f""" Backup Failure Alert

**Dettagli Job:**
- Nome job: {backup_job}
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Errore: {error_msg}

**Impatto:**
- [ ] Dati non protetti per questo ciclo
- [ ] RPO a rischio
- [ ] Storage backup non aggiornato

**Azioni richieste:**
1. Verificare spazio disco disponibile
2. Controllare permessi file/directory
3. Verificare connettività storage remoto
4. Controllare log backup dettagliati
5. Tentare backup manuale se possibile

**Log Path:**
```
/var/log/backup/{backup_job}.log
```

**Priority:** HIGH
**SLA:** 2 ore""",
        "priority": "high",
        "tags": ["backup", "storage", "dati"]
    }


def template_disk_full(hostname: str, mount_point: str, usage: str) -> Dict[str, Any]:
    """Template per disco quasi pieno"""
    return {
        "title": f"[HIGH] Disco quasi pieno su {hostname}:{mount_point}",
        "description": f""" Disk Space Alert

**Dettagli:**
- Hostname: {hostname}
- Mount Point: {mount_point}
- Utilizzo: {usage}%
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Impatto potenziale:**
- [ ] Applicazioni potrebbero fallire
- [ ] Log potrebbero non essere scritti
- [ ] Database a rischio corruzione
- [ ] Sistema potrebbe diventare instabile

**Azioni immediate:**
1. Identificare file più grandi
2. Pulire log vecchi
3. Rimuovere file temporanei
4. Verificare necessità espansione

**Comandi per pulizia:**
```bash
# Trova file grandi
du -sh {mount_point}/* | sort -rh | head -20

# Pulisci log vecchi
find /var/log -type f -name '*.log' -mtime +30 -delete

# Pulisci cache apt/yum
apt-get clean  # o yum clean all

# Svuota cestino
rm -rf ~/.local/share/Trash/*
```

**Priority:** HIGH
**SLA:** 4 ore""",
        "priority": "high",
        "tags": ["storage", "disk", "infrastruttura"]
    }


def template_ssl_expiring(domain: str, days_left: str) -> Dict[str, Any]:
    """Template per certificato SSL in scadenza"""
    try:
        expiry_date = (datetime.now() + timedelta(days=int(days_left))).strftime('%Y-%m-%d')
    except:
        expiry_date = "N/A"
    
    return {
        "title": f"[MEDIUM] Certificato SSL in scadenza per {domain}",
        "description": f""" SSL Certificate Expiration Warning

**Dettagli:**
- Dominio: {domain}
- Giorni rimanenti: {days_left}
- Data scadenza: {expiry_date}
- Data/Ora controllo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Impatto se scade:**
- [ ] Sito web inaccessibile
- [ ] Errori browser per utenti
- [ ] API potrebbero fallire
- [ ] Email potrebbero non funzionare

**Azioni richieste:**
1. Rinnovare certificato tramite CA
2. Aggiornare configurazione web server
3. Testare nuovo certificato
4. Aggiornare monitoring

**Rinnovo Let's Encrypt:**
```bash
certbot renew --dry-run  # test
certbot renew            # rinnovo effettivo
sudo systemctl reload nginx
```

**Verifica certificato:**
```bash
echo | openssl s_client -servername {domain} -connect {domain}:443 2>/dev/null | openssl x509 -noout -dates
```

**Priority:** MEDIUM
**SLA:** Prima della scadenza""",
        "priority": "normal",
        "tags": ["ssl", "sicurezza", "certificati"]
    }


# ===== TEMPLATE APPLICAZIONI =====

def template_app_error_rate(app_name: str, error_rate: str, threshold: str = "5") -> Dict[str, Any]:
    """Template per error rate elevato"""
    return {
        "title": f"[HIGH] Error rate elevato per {app_name}",
        "description": f""" Application Error Rate Alert

**Dettagli:**
- Applicazione: {app_name}
- Error rate: {error_rate}%
- Soglia: {threshold}%
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Metriche:**
- Richieste totali: [DA VERIFICARE]
- Errori: [DA VERIFICARE]
- Endpoint più colpiti: [DA VERIFICARE]

**Azioni immediate:**
1. Verificare log applicazione
2. Controllare dipendenze (DB, cache, API esterne)
3. Verificare recenti deployment
4. Controllare risorse sistema
5. Valutare rollback se necessario

**Log da controllare:**
```bash
tail -f /var/log/{app_name}/error.log
grep -i 'error\\|exception' /var/log/{app_name}/*.log | tail -50
```

**Priority:** HIGH
**SLA:** 1 ora""",
        "priority": "high",
        "tags": ["applicazione", "errori", "performance"]
    }


def template_db_slow_queries(db_name: str, slow_count: str) -> Dict[str, Any]:
    """Template per query lente database"""
    return {
        "title": f"[MEDIUM] Query lente rilevate su database {db_name}",
        "description": f""" Database Performance Alert

**Dettagli:**
- Database: {db_name}
- Query lente: {slow_count}
- Periodo: ultima ora
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Impatto:**
- [ ] Performance applicazione degradate
- [ ] Timeout per utenti
- [ ] Carico DB elevato

**Azioni richieste:**
1. Identificare query problematiche
2. Verificare indici mancanti
3. Analizzare execution plan
4. Controllare statistiche tabelle
5. Valutare ottimizzazioni

**Diagnostica MySQL/MariaDB:**
```sql
-- Query più lente
SELECT * FROM mysql.slow_log ORDER BY query_time DESC LIMIT 10;

-- Query attive
SHOW FULL PROCESSLIST;

-- Indici non usati
SELECT * FROM sys.schema_unused_indexes;
```

**Diagnostica PostgreSQL:**
```sql
-- Query lente
SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;

-- Sessioni attive
SELECT * FROM pg_stat_activity WHERE state = 'active';
```

**Priority:** MEDIUM
**SLA:** 4 ore""",
        "priority": "normal",
        "tags": ["database", "performance", "ottimizzazione"]
    }


# ===== TEMPLATE SICUREZZA =====

def template_security_breach(incident_type: str, affected_system: str) -> Dict[str, Any]:
    """Template per incidente di sicurezza"""
    return {
        "title": f"[CRITICAL] Potenziale incidente di sicurezza: {incident_type}",
        "description": f""" SECURITY INCIDENT ALERT

**ATTENZIONE: INCIDENT RESPONSE IMMEDIATA RICHIESTA**

**Dettagli:**
- Tipo incidente: {incident_type}
- Sistema interessato: {affected_system}
- Data/Ora rilevamento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- Severità: CRITICAL

**Azioni immediate (NON MODIFICARE IL SISTEMA):**
1.  Isolare sistema compromesso dalla rete
2.  Preservare log e evidenze
3.  Notificare team security
4.  Attivare piano incident response
5.  Documentare ogni azione

**NON FARE:**
-  Non riavviare il sistema
-  Non modificare file
-  Non cancellare log
-  Non informare pubblicamente

**Contatti emergenza:**
- Security Team: [INSERIRE CONTATTO]
- Manager: [INSERIRE CONTATTO]
- Legal: [INSERIRE CONTATTO]

**Preservazione evidenze:**
```bash
# Backup log
tar czf /tmp/incident-logs-$(date +%s).tar.gz /var/log/

# Cattura stato sistema
ps auxf > /tmp/processes.txt
netstat -tulpn > /tmp/connections.txt
lsof > /tmp/openfiles.txt
```

**Priority:** CRITICAL
**SLA:** IMMEDIATO""",
        "priority": "critical",
        "tags": ["sicurezza", "incident", "emergenza"]
    }


def template_failed_login(username: str, ip_address: str, attempts: str) -> Dict[str, Any]:
    """Template per tentativi di login falliti"""
    return {
        "title": f"[HIGH] Tentativi di login falliti per {username}",
        "description": f""" Failed Login Attempts Alert

**Dettagli:**
- Username: {username}
- IP Address: {ip_address}
- Tentativi: {attempts}
- Periodo: ultima ora
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Azioni immediate:**
1. Verificare se attacco brute force
2. Controllare altri account compromessi
3. Verificare se IP già noto
4. Valutare blocco temporaneo IP
5. Notificare utente se legittimo

**Analisi log:**
```bash
# Login falliti SSH
grep 'Failed password' /var/log/auth.log | tail -50

# IP più attivi
grep 'Failed password' /var/log/auth.log | awk '{{print $(NF-3)}}' | sort | uniq -c | sort -rn

# Blocco IP con fail2ban
fail2ban-client status sshd
fail2ban-client set sshd banip {ip_address}
```

**Geolocalizzazione IP:**
```bash
whois {ip_address} | grep -i country
curl -s ipinfo.io/{ip_address}
```

**Priority:** HIGH
**SLA:** 2 ore""",
        "priority": "high",
        "tags": ["sicurezza", "autenticazione", "brute-force"]
    }


# ===== TEMPLATE MANUTENZIONE =====

def template_planned_maintenance(system: str, date_time: str, duration: str) -> Dict[str, Any]:
    """Template per manutenzione programmata"""
    return {
        "title": f"[PLANNED] Manutenzione programmata: {system}",
        "description": f""" Scheduled Maintenance

**Dettagli:**
- Sistema: {system}
- Data/Ora: {date_time}
- Durata stimata: {duration}
- Creato: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Lavori pianificati:**
- [ ] Backup sistema completo
- [ ] Update sistema operativo
- [ ] Update applicazioni
- [ ] Riavvio servizi
- [ ] Testing post-manutenzione

**Impatto atteso:**
- [ ] Downtime totale
- [ ] Performance ridotte
- [ ] Accesso limitato
- [ ] Nessun impatto

**Checklist pre-manutenzione:**
- [ ] Backup verificato
- [ ] Utenti notificati
- [ ] Change request approvato
- [ ] Rollback plan pronto
- [ ] Team di supporto allertato

**Checklist post-manutenzione:**
- [ ] Servizi riavviati
- [ ] Smoke test completato
- [ ] Monitoring verificato
- [ ] Performance baseline ristabilita
- [ ] Utenti notificati (completamento)

**Rollback procedure:**
```bash
# [INSERIRE COMANDI ROLLBACK]
```

**Priority:** NORMAL
**Deadline:** {date_time}""",
        "priority": "normal",
        "tags": ["manutenzione", "programmato", "change"]
    }


# ===== CLI =====

def print_usage():
    """Stampa usage"""
    print(""" Ydea Ticket Templates

USO:
  # Template infrastruttura
  ydea_templates.py server-down <hostname> [service]
  ydea_templates.py backup-failed <job_name> [error_msg]
  ydea_templates.py disk-full <hostname> <mount_point> <usage_%>
  ydea_templates.py ssl-expiring <domain> <days_left>
  
  # Template applicazioni
  ydea_templates.py app-errors <app_name> <error_rate_%> [threshold]
  ydea_templates.py db-slow <db_name> <slow_query_count>
  
  # Template sicurezza
  ydea_templates.py security-breach <incident_type> <affected_system>
  ydea_templates.py failed-login <username> <ip_address> <attempts>
  
  # Template manutenzione
  ydea_templates.py maintenance <system> <date_time> <duration>

ESEMPI:
  # Stampa template JSON
  ydea_templates.py server-down web-prod-01 nginx
  
  # Usa in script Python
  import ydea_templates
  template = ydea_templates.template_disk_full("server-01", "/var", "92")
  print(json.dumps(template, indent=2))
""", file=sys.stderr)


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1]
    args = sys.argv[2:]  # type: ignore
    
    template = None
    
    if command == "server-down":
        if len(args) < 1:
            print("Errore: hostname richiesto", file=sys.stderr)
            sys.exit(1)
        template = template_server_down(*args)
    
    elif command == "backup-failed":
        if len(args) < 1:
            print("Errore: job_name richiesto", file=sys.stderr)
            sys.exit(1)
        template = template_backup_failed(*args)
    
    elif command == "disk-full":
        if len(args) < 3:
            print("Errore: hostname, mount_point, usage richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_disk_full(*args)
    
    elif command == "ssl-expiring":
        if len(args) < 2:
            print("Errore: domain, days_left richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_ssl_expiring(*args)
    
    elif command == "app-errors":
        if len(args) < 2:
            print("Errore: app_name, error_rate richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_app_error_rate(*args)
    
    elif command == "db-slow":
        if len(args) < 2:
            print("Errore: db_name, slow_count richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_db_slow_queries(*args)
    
    elif command == "security-breach":
        if len(args) < 2:
            print("Errore: incident_type, affected_system richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_security_breach(*args)
    
    elif command == "failed-login":
        if len(args) < 3:
            print("Errore: username, ip_address, attempts richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_failed_login(*args)
    
    elif command == "maintenance":
        if len(args) < 3:
            print("Errore: system, date_time, duration richiesti", file=sys.stderr)
            sys.exit(1)
        template = template_planned_maintenance(*args)
    
    else:
        print_usage()
        sys.exit(1)
    
    # Stampa JSON
    print(json.dumps(template, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
