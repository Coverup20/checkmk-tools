#!/usr/bin/env python3
"""
ydea_health_monitor.py - Monitoraggio disponibilità Ydea API

Controlla periodicamente se Ydea è raggiungibile e notifica via email se down/recovery.
Gestisce soglia errori consecutivi per evitare falsi positivi.

Usage:
    ydea_health_monitor.py

Tipicamente eseguito via cron ogni 15 minuti.

Version: 1.0.0 (convertito da Bash)
"""

VERSION = "1.0.0"  # Versione script (aggiornare ad ogni modifica)

import sys
import os
import importlib.util
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

# Import moduli locali
script_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(script_dir))

from ydea_common import Logger, StateManager, EmailNotifier  # type: ignore

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


# ===== CONFIGURAZIONE =====

STATE_FILE = Path("/tmp/ydea_health_state.json")
MAIL_SCRIPT = Path("/omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down")

# Destinatario email per notifiche
ALERT_EMAIL = os.getenv("YDEA_ALERT_EMAIL", "massimo.palazzetti@nethesis.it")

# Soglia di errori consecutivi prima di notificare (per evitare falsi positivi)
FAILURE_THRESHOLD = int(os.getenv("YDEA_FAILURE_THRESHOLD", "3"))

# Default state
DEFAULT_STATE = {
    "status": "unknown",
    "last_check": 0,
    "consecutive_failures": 0,
    "last_failure": "",
    "notified": False
}


# ===== FUNZIONI UTILITY =====

def test_ydea_login() -> bool:
    """
    Testa login Ydea API
    
    Returns:
        True se login riuscito, False altrimenti
    """
    try:
        api = YdeaAPI()
        api.ensure_token()
        return True
    except Exception as e:
        Logger.error(f"Login fallito: {e}")
        return False


def send_email_alert(subject: str, body: str) -> bool:
    """
    Invia notifica email
    
    Args:
        subject: Oggetto email
        body: Corpo email
        
    Returns:
        True se invio riuscito, False altrimenti
    """
    Logger.info(f"Invio notifica email a {ALERT_EMAIL}")
    
    # Usa lo script mail_ydea_down se esiste
    if MAIL_SCRIPT.exists() and os.access(MAIL_SCRIPT, os.X_OK):
        try:
            # Esporta variabili per lo script di notifica
            env = os.environ.copy()
            env.update({
                "NOTIFY_HOSTNAME": "ydea.cloud",
                "NOTIFY_HOSTADDRESS": "my.ydea.cloud",
                "NOTIFY_WHAT": "HOST",
                "NOTIFY_HOSTSTATE": "DOWN",
                "NOTIFY_HOSTOUTPUT": "Ydea API non raggiungibile - Impossibile effettuare login",
                "NOTIFY_CONTACTEMAIL": ALERT_EMAIL,
                "NOTIFY_DATE": datetime.now().strftime('%Y-%m-%d'),
                "NOTIFY_SHORTDATETIME": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            
            import subprocess
            result = subprocess.run(
                [str(MAIL_SCRIPT)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                Logger.info(result.stdout)
                return True
            else:
                Logger.error(f"Script mail fallito: {result.stderr}")
                return False
                
        except Exception as e:
            Logger.error(f"Errore esecuzione script mail: {e}")
            return False
    else:
        # Fallback: usa EmailNotifier
        try:
            notifier = EmailNotifier(smtp_host="localhost", smtp_port=25)
            notifier.send_email(ALERT_EMAIL, subject, body, html=False)
            return True
        except Exception as e:
            Logger.error(f"Errore invio email: {e}")
            return False


def build_down_alert() -> tuple[str, str]:
    """
    Costruisci email alert per Ydea down
    
    Returns:
        Tuple (subject, body)
    """
    subject = " [ALERT] Ydea API - Servizio Non Raggiungibile"
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    body = f"""ATTENZIONE: Il servizio Ydea API non è raggiungibile.

Dettagli:
- Data/Ora rilevazione: {now}
- Tentativi falliti consecutivi: {FAILURE_THRESHOLD}
- URL: https://my.ydea.cloud
- Endpoint: /app_api_v2/login

Impatto:
- Sistema di ticketing non disponibile
- Alert CheckMK NON verranno convertiti in ticket Ydea
- Creazione manuale ticket non possibile

Azioni richieste:
1. Verificare status servizio Ydea (https://status.ydea.cloud se disponibile)
2. Controllare connettività di rete
3. Verificare credenziali API
4. Contattare supporto Ydea se necessario

Il sistema continuerà a monitorare e invierà notifica quando il servizio sarà ripristinato.

---
Monitor automatico Ydea Health
Check ogni 15 minuti"""
    
    return subject, body


def build_recovery_alert(last_failure_timestamp: str) -> tuple[str, str]:
    """
    Costruisci email alert per Ydea recovery
    
    Args:
        last_failure_timestamp: Timestamp ultimo fallimento
        
    Returns:
        Tuple (subject, body)
    """
    subject = " [RECOVERY] Ydea API - Servizio Ripristinato"
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Converti timestamp se disponibile
    last_failure_str = "N/A"
    if last_failure_timestamp:
        try:
            last_failure_dt = datetime.fromtimestamp(int(last_failure_timestamp))
            last_failure_str = last_failure_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
    
    body = f"""Il servizio Ydea API è tornato online.

Dettagli:
- Data/Ora recovery: {now}
- Ultimo check fallito: {last_failure_str}

Il servizio di ticketing è nuovamente operativo.

---
Monitor automatico Ydea Health"""
    
    return subject, body


# ===== MAIN =====

def main():
    """Main function"""
    
    # Inizializza state manager
    state = StateManager(STATE_FILE, default_state=DEFAULT_STATE)
    
    # Leggi stato corrente
    current_status = state.get("status")
    consecutive_failures = state.get("consecutive_failures")
    was_notified = state.get("notified")
    
    Logger.info("Controllo disponibilità Ydea API...")
    
    if test_ydea_login():
        # ===== YDEA UP =====
        Logger.success(" Ydea API raggiungibile")
        
        # Se era down e abbiamo notificato, invia recovery email
        if current_status == "down" and was_notified:
            Logger.info("Ydea tornato online, invio notifica di recovery")
            
            last_failure = state.get("last_failure")
            subject, body = build_recovery_alert(last_failure)
            
            send_email_alert(subject, body)
        
        # Reset stato
        state.set("status", "up")
        state.set("consecutive_failures", 0)
        state.set("notified", False)
        state.set("last_failure", "")
        state.set("last_check", int(datetime.now().timestamp()))
        
    else:
        # ===== YDEA DOWN =====
        consecutive_failures += 1
        Logger.error(f" Ydea API non raggiungibile (tentativi falliti: {consecutive_failures}/{FAILURE_THRESHOLD})")
        
        # Notifica solo se raggiungiamo la soglia e non abbiamo già notificato
        if consecutive_failures >= FAILURE_THRESHOLD and not was_notified:
            Logger.info("Soglia di errori raggiunta, invio notifica")
            
            subject, body = build_down_alert()
            
            if send_email_alert(subject, body):
                Logger.success(" Notifica inviata con successo")
                state.set("notified", True)
            else:
                Logger.error("Errore invio notifica")
                state.set("notified", False)
        
        # Aggiorna stato
        state.set("status", "down")
        state.set("consecutive_failures", consecutive_failures)
        state.set("last_failure", str(int(datetime.now().timestamp())))
        state.set("last_check", int(datetime.now().timestamp()))


if __name__ == "__main__":
    main()
