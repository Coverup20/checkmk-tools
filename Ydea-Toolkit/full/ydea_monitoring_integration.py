#!/usr/bin/env python3
"""
ydea_monitoring_integration.py - Integrazione monitoraggio sistema con Ydea

Monitora CPU, memoria, disco e servizi systemd.
Crea automaticamente ticket Ydea quando le soglie vengono superate.
Gestisce cache per evitare duplicati e cleanup automatico.

Usage:
    ydea_monitoring_integration.py [cpu|memory|disk|service|cleanup|main]

Examples:
    ydea_monitoring_integration.py              # Esegue tutti i controlli
    ydea_monitoring_integration.py cpu          # Solo controllo CPU
    ydea_monitoring_integration.py service nginx  # Controlla servizio nginx

Version: 1.0.0 (convertito da Bash)
"""

VERSION = "1.0.0"  # Versione script (aggiornare ad ogni modifica)

import sys
import os
import importlib.util
import socket
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

# Richiede psutil per metriche sistema
try:
    import psutil
except ImportError:
    print("ERRORE: psutil non installato. Eseguire: pip3 install psutil")
    sys.exit(1)

# Import moduli locali
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from ydea_common import Logger, CacheManager  # type: ignore

# Import ydea-toolkit.py (nome con trattino richiede importlib)
ydea_toolkit_path = script_dir / "ydea-toolkit.py"
spec = importlib.util.spec_from_file_location("ydea_toolkit", ydea_toolkit_path)
if spec and spec.loader:
    ydea_toolkit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ydea_toolkit)  # type: ignore
else:
    raise ImportError("Cannot load ydea-toolkit.py")

# Estrai classi necessarie
YdeaAPI = ydea_toolkit.YdeaAPI
TicketOperations = ydea_toolkit.TicketOperations


# ===== CONFIGURAZIONE =====

# Soglie alert
ALERT_THRESHOLD_CPU = int(os.getenv("ALERT_THRESHOLD_CPU", "90"))
ALERT_THRESHOLD_MEM = int(os.getenv("ALERT_THRESHOLD_MEM", "85"))
ALERT_THRESHOLD_DISK = int(os.getenv("ALERT_THRESHOLD_DISK", "90"))

# File cache ticket
TICKET_CACHE_FILE = Path("/tmp/ydea_tickets_cache.json")

# Max age cache (24 ore)
CACHE_MAX_AGE_HOURS = 24


# ===== GESTIONE CACHE TICKET =====

cache = CacheManager(TICKET_CACHE_FILE)


def ticket_exists(alert_key: str) -> bool:
    """
    Verifica se esiste già un ticket aperto per questo alert
    
    Args:
        alert_key: Chiave univoca alert (es: cpu_hostname)
        
    Returns:
        True se ticket esiste in cache
    """
    return cache.get(alert_key) is not None


def save_ticket_cache(alert_key: str, ticket_id: int):
    """
    Salva ticket in cache
    
    Args:
        alert_key: Chiave univoca alert
        ticket_id: ID ticket creato
    """
    cache.set(alert_key, {
        "ticket_id": ticket_id,
        "created_at": int(datetime.now().timestamp())
    })


def remove_ticket_cache(alert_key: str):
    """
    Rimuovi ticket dalla cache (quando viene chiuso o alert risolto)
    
    Args:
        alert_key: Chiave univoca alert
    """
    cache.delete(alert_key)


def cleanup_cache():
    """Pulisci cache da ticket vecchi (>24h)"""
    now = int(datetime.now().timestamp())
    max_age_seconds = CACHE_MAX_AGE_HOURS * 3600
    
    all_data = cache.load()
    removed_count = 0
    
    for key, ticket_data in all_data.items():
        if ticket_data and isinstance(ticket_data, dict):
            created_at = ticket_data.get("created_at", 0)
            if now - created_at > max_age_seconds:
                cache.delete(key)
                removed_count += 1
    
    if removed_count > 0:
        Logger.info(f"Rimossi {removed_count} ticket vecchi dalla cache")


# ===== FUNZIONI CREAZIONE TICKET =====

def create_ticket(title: str, description: str, priority: str = "normal", tags: list = None) -> Optional[int]:
    """
    Crea ticket Ydea
    
    Args:
        title: Titolo ticket
        description: Descrizione ticket
        priority: Priorità (normal, high, critical)
        tags: Lista tag
        
    Returns:
        ID ticket creato, None se fallito
    """
    try:
        api = YdeaAPI()
        
        ticket_body = {
            "titolo": title,
            "descrizione": description,
            "priorita": priority
        }
        
        if tags:
            ticket_body["tags"] = tags
        
        response, status_code = api.api_call("POST", "/tickets", json_body=ticket_body)
        
        if status_code in [200, 201]:
            ticket_id = response.get("id")
            if ticket_id:
                Logger.success(f" Ticket creato: #{ticket_id}")
                return ticket_id
        
        Logger.error("Creazione ticket fallita")
        return None
        
    except Exception as e:
        Logger.error(f"Errore creazione ticket: {e}")
        return None


# ===== FUNZIONI DI MONITORAGGIO =====

def check_cpu_usage(hostname: Optional[str] = None):
    """
    Monitora CPU
    
    Args:
        hostname: Nome host (default: hostname corrente)
    """
    if not hostname:
        hostname = socket.gethostname()
    
    # Ottieni uso CPU (media 1 secondo)
    cpu_usage = int(psutil.cpu_percent(interval=1))
    
    alert_key = f"cpu_{hostname}"
    
    if cpu_usage > ALERT_THRESHOLD_CPU:
        if not ticket_exists(alert_key):
            Logger.warn(f"CPU usage elevato: {cpu_usage}%")
            
            title = f"[HIGH] CPU usage elevato su {hostname}"
            description = f""" CPU Alert

**Dettagli:**
- Hostname: {hostname}
- CPU Usage: {cpu_usage}%
- Soglia: {ALERT_THRESHOLD_CPU}%
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Azioni immediate:**
1. Identificare processi che consumano più CPU
2. Verificare se è un picco temporaneo o persistente
3. Controllare se ci sono processi zombie
4. Valutare scaling verticale

**Diagnostica:**
```bash
top -bn1 | head -20
ps auxf --sort=-%cpu | head -10
```"""
            
            ticket_id = create_ticket(title, description, priority="high", 
                                     tags=["cpu", "performance", "infrastruttura"])
            
            if ticket_id:
                save_ticket_cache(alert_key, ticket_id)
    else:
        # CPU OK - rimuovi ticket se esistente
        if ticket_exists(alert_key):
            Logger.info(f"CPU tornata normale ({cpu_usage}%), rimuovo ticket dalla cache")
            remove_ticket_cache(alert_key)


def check_memory_usage(hostname: Optional[str] = None):
    """
    Monitora memoria
    
    Args:
        hostname: Nome host (default: hostname corrente)
    """
    if not hostname:
        hostname = socket.gethostname()
    
    # Ottieni uso memoria
    mem = psutil.virtual_memory()
    mem_usage = int(mem.percent)
    
    alert_key = f"mem_{hostname}"
    
    if mem_usage > ALERT_THRESHOLD_MEM:
        if not ticket_exists(alert_key):
            Logger.warn(f"Memory usage elevato: {mem_usage}%")
            
            title = f"[HIGH] Memory usage elevato su {hostname}"
            description = f""" Memory Alert

**Dettagli:**
- Hostname: {hostname}
- Memory Usage: {mem_usage}%
- Soglia: {ALERT_THRESHOLD_MEM}%
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Azioni immediate:**
1. Identificare processi che consumano più memoria
2. Verificare memory leaks
3. Controllare cache e buffer
4. Valutare se aumentare RAM

**Diagnostica:**
```bash
free -h
ps auxf --sort=-%mem | head -10
sudo slabtop
```"""
            
            ticket_id = create_ticket(title, description, priority="high",
                                     tags=["memoria", "performance", "infrastruttura"])
            
            if ticket_id:
                save_ticket_cache(alert_key, ticket_id)
    else:
        # Memoria OK
        if ticket_exists(alert_key):
            Logger.info(f"Memoria tornata normale ({mem_usage}%), rimuovo ticket dalla cache")
            remove_ticket_cache(alert_key)


def check_disk_usage(hostname: Optional[str] = None, mount_point: str = "/"):
    """
    Monitora disco
    
    Args:
        hostname: Nome host (default: hostname corrente)
        mount_point: Punto di mount da controllare (default: /)
    """
    if not hostname:
        hostname = socket.gethostname()
    
    try:
        # Ottieni uso disco
        disk = psutil.disk_usage(mount_point)
        disk_usage = int(disk.percent)
        
        # Crea chiave alert (sostituisci / con _)
        mount_safe = mount_point.replace("/", "_")
        alert_key = f"disk_{hostname}_{mount_safe}"
        
        if disk_usage > ALERT_THRESHOLD_DISK:
            if not ticket_exists(alert_key):
                Logger.warn(f"Disk usage elevato su {mount_point}: {disk_usage}%")
                
                title = f"[HIGH] Disk usage elevato su {hostname}:{mount_point}"
                description = f""" Disk Alert

**Dettagli:**
- Hostname: {hostname}
- Mount Point: {mount_point}
- Disk Usage: {disk_usage}%
- Soglia: {ALERT_THRESHOLD_DISK}%
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Azioni immediate:**
1. Identificare file/directory più grandi
2. Pulire log vecchi
3. Rimuovere file temporanei
4. Valutare espansione storage

**Diagnostica:**
```bash
df -h {mount_point}
du -sh {mount_point}/* | sort -rh | head -10
find {mount_point} -type f -size +100M
```"""
                
                ticket_id = create_ticket(title, description, priority="high",
                                         tags=["disco", "storage", "infrastruttura"])
                
                if ticket_id:
                    save_ticket_cache(alert_key, ticket_id)
        else:
            # Disco OK
            if ticket_exists(alert_key):
                Logger.info(f"Disco {mount_point} tornato normale ({disk_usage}%), rimuovo ticket dalla cache")
                remove_ticket_cache(alert_key)
                
    except Exception as e:
        Logger.error(f"Errore controllo disco {mount_point}: {e}")


def check_service_status(service_name: str, hostname: Optional[str] = None):
    """
    Monitora servizio systemd
    
    Args:
        service_name: Nome servizio systemd
        hostname: Nome host (default: hostname corrente)
    """
    if not hostname:
        hostname = socket.gethostname()
    
    try:
        # Controlla stato servizio con systemctl
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        is_active = (result.returncode == 0)
        service_status = result.stdout.strip()
        
        alert_key = f"service_{hostname}_{service_name}"
        
        if not is_active:
            if not ticket_exists(alert_key):
                Logger.error(f"Servizio {service_name} non attivo")
                
                title = f"[CRITICAL] Servizio {service_name} non attivo su {hostname}"
                description = f""" Service Down Alert

**Dettagli:**
- Hostname: {hostname}
- Servizio: {service_name}
- Stato: {service_status}
- Data/Ora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Azioni immediate:**
1. Tentare restart servizio
2. Controllare log servizio
3. Verificare dipendenze
4. Controllare configurazione

**Diagnostica:**
```bash
systemctl status {service_name}
journalctl -xeu {service_name} --since '10 minutes ago'
sudo systemctl restart {service_name}
```"""
                
                ticket_id = create_ticket(title, description, priority="critical",
                                         tags=["servizio", "downtime", "infrastruttura"])
                
                if ticket_id:
                    save_ticket_cache(alert_key, ticket_id)
        else:
            # Servizio OK
            if ticket_exists(alert_key):
                Logger.info(f"Servizio {service_name} tornato attivo, rimuovo ticket dalla cache")
                remove_ticket_cache(alert_key)
                
    except subprocess.TimeoutExpired:
        Logger.error(f"Timeout controllo servizio {service_name}")
    except FileNotFoundError:
        Logger.error("systemctl non trovato - sistema non supportato")
    except Exception as e:
        Logger.error(f"Errore controllo servizio {service_name}: {e}")


# ===== MAIN =====

def main():
    """Main function - esegue tutti i controlli"""
    Logger.info("Inizio controlli monitoraggio")
    
    # Pulizia cache
    cleanup_cache()
    
    # Controlli di default
    check_cpu_usage()
    check_memory_usage()
    check_disk_usage()
    
    # Controlli servizi critici (opzionali - decommentare se necessario)
    # check_service_status("nginx")
    # check_service_status("mysql")
    # check_service_status("postgresql")
    
    Logger.success("Controlli completati")


if __name__ == "__main__":
    # CLI
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "cpu":
            hostname = sys.argv[2] if len(sys.argv) > 2 else None
            check_cpu_usage(hostname)
        
        elif command in ["memory", "mem"]:
            hostname = sys.argv[2] if len(sys.argv) > 2 else None
            check_memory_usage(hostname)
        
        elif command == "disk":
            hostname = sys.argv[2] if len(sys.argv) > 2 else None
            mount_point = sys.argv[3] if len(sys.argv) > 3 else "/"
            check_disk_usage(hostname, mount_point)
        
        elif command == "service":
            if len(sys.argv) < 3:
                print("Usage: ydea_monitoring_integration.py service <service_name> [hostname]")
                sys.exit(1)
            service_name = sys.argv[2]
            hostname = sys.argv[3] if len(sys.argv) > 3 else None
            check_service_status(service_name, hostname)
        
        elif command == "cleanup":
            cleanup_cache()
            Logger.success("Cache pulita")
        
        else:
            main()
    else:
        main()
