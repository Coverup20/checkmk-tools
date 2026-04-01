#!/usr/bin/env python3
"""
ydea_common.py - Modulo condiviso per utilities comuni Ydea-Toolkit

Fornisce funzionalità comuni utilizzate da tutti gli script:
- Logging utilities
- Cache management (JSON file-based)
- Configuration loading
- State management
- Email notifications

Version: 1.0.0
"""

VERSION = "1.0.0"  # Versione modulo (aggiornare ad ogni modifica)

import os
import sys
import json
import time
import smtplib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


# ===== LOGGING UTILITIES =====

class Logger:
    """Logger semplice con timestamp e emoji"""
    
    @staticmethod
    def _log(emoji: str, level: str, message: str, to_stderr: bool = False):
        """Log generico con timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"[{timestamp}] {emoji} {message}"
        
        if to_stderr:
            print(log_line, file=sys.stderr)
        else:
            print(log_line)
    
    @staticmethod
    def info(message: str):
        """Log informativo"""
        Logger._log("ℹ ", "INFO", message)
    
    @staticmethod
    def warn(message: str):
        """Log warning"""
        Logger._log(" ", "WARN", message, to_stderr=True)
    
    @staticmethod
    def error(message: str):
        """Log errore"""
        Logger._log("", "ERROR", message, to_stderr=True)
    
    @staticmethod
    def success(message: str):
        """Log successo"""
        Logger._log("", "SUCCESS", message)
    
    @staticmethod
    def debug(message: str):
        """Log debug (solo se DEBUG=1)"""
        if os.getenv("DEBUG", "0") == "1":
            Logger._log("", "DEBUG", message, to_stderr=True)


# ===== CACHE MANAGEMENT =====

class CacheManager:
    """Gestione cache JSON file-based"""
    
    def __init__(self, cache_file: str):
        """
        Inizializza cache manager
        
        Args:
            cache_file: Path al file cache JSON
        """
        self.cache_file = Path(cache_file)
        self._init_cache()
    
    def _init_cache(self):
        """Inizializza file cache se non esiste"""
        if not self.cache_file.exists():
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.save({})
    
    def load(self) -> Dict[str, Any]:
        """
        Carica cache da file
        
        Returns:
            Dizionario con contenuto cache
        """
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def save(self, data: Dict[str, Any]):
        """
        Salva cache su file
        
        Args:
            data: Dizionario da salvare
        """
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            Logger.error(f"Errore salvataggio cache: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Ottieni valore dalla cache
        
        Args:
            key: Chiave da cercare
            default: Valore di default se chiave non trovata
        
        Returns:
            Valore associato alla chiave o default
        """
        cache = self.load()
        return cache.get(key, default)
    
    def set(self, key: str, value: Any):
        """
        Imposta valore in cache
        
        Args:
            key: Chiave
            value: Valore da salvare
        """
        cache = self.load()
        cache[key] = value
        self.save(cache)
    
    def delete(self, key: str):
        """
        Rimuovi chiave dalla cache
        
        Args:
            key: Chiave da rimuovere
        """
        cache = self.load()
        if key in cache:
            del cache[key]
            self.save(cache)
    
    def exists(self, key: str) -> bool:
        """
        Verifica se chiave esiste in cache
        
        Args:
            key: Chiave da verificare
        
        Returns:
            True se chiave esiste, False altrimenti
        """
        cache = self.load()
        return key in cache
    
    def cleanup_old_entries(self, max_age_seconds: int, timestamp_key: str = 'created_at'):
        """
        Pulisci entry vecchie dalla cache
        
        Args:
            max_age_seconds: Età massima in secondi
            timestamp_key: Nome campo timestamp nelle entry
        """
        cache = self.load()
        now = int(time.time())
        cutoff = now - max_age_seconds
        
        cleaned = {
            k: v for k, v in cache.items()
            if isinstance(v, dict) and v.get(timestamp_key, 0) > cutoff
        }
        
        if len(cleaned) < len(cache):
            removed = len(cache) - len(cleaned)
            Logger.debug(f"Rimossi {removed} entry vecchie dalla cache")
            self.save(cleaned)


# ===== CONFIGURATION LOADING =====

class ConfigLoader:
    """Caricamento configurazione da file JSON"""
    
    @staticmethod
    def load_json(config_file: str) -> Dict[str, Any]:
        """
        Carica configurazione da file JSON
        
        Args:
            config_file: Path al file di configurazione
        
        Returns:
            Dizionario con configurazione
        
        Raises:
            FileNotFoundError: Se file non esiste
            json.JSONDecodeError: Se JSON non valido
        """
        config_path = Path(config_file)
        
        if not config_path.exists():
            raise FileNotFoundError(f"File configurazione non trovato: {config_file}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def load_env(env_file: str = ".env") -> Dict[str, str]:
        """
        Carica variabili da file .env
        
        Args:
            env_file: Path al file .env
        
        Returns:
            Dizionario con variabili ambiente
        """
        env_vars = {}
        env_path = Path(env_file)
        
        if not env_path.exists():
            return env_vars
        
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # Rimuovi 'export' se presente
                    line = line.replace('export ', '', 1).strip()
                    key, value = line.split('=', 1)
                    # Rimuovi quotes
                    value = value.strip().strip('"').strip("'")
                    env_vars[key.strip()] = value
        
        return env_vars


# ===== STATE MANAGEMENT =====

class StateManager:
    """Gestione stato applicazione con persistenza JSON"""
    
    def __init__(self, state_file: str, default_state: Optional[Dict[str, Any]] = None):
        """
        Inizializza state manager
        
        Args:
            state_file: Path al file stato JSON
            default_state: Stato di default se file non esiste
        """
        self.state_file = Path(state_file)
        self.default_state = default_state or {}
        self._init_state()
    
    def _init_state(self):
        """Inizializza file stato se non esiste"""
        if not self.state_file.exists():
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.save(self.default_state)
    
    def load(self) -> Dict[str, Any]:
        """
        Carica stato da file
        
        Returns:
            Dizionario con stato corrente
        """
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return self.default_state.copy()
    
    def save(self, state: Dict[str, Any]):
        """
        Salva stato su file
        
        Args:
            state: Dizionario stato da salvare
        """
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            Logger.error(f"Errore salvataggio stato: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Ottieni valore dallo stato"""
        state = self.load()
        return state.get(key, default)
    
    def set(self, key: str, value: Any):
        """Imposta valore nello stato"""
        state = self.load()
        state[key] = value
        self.save(state)
    
    def update(self, updates: Dict[str, Any]):
        """
        Aggiorna multiple chiavi nello stato
        
        Args:
            updates: Dizionario con aggiornamenti
        """
        state = self.load()
        state.update(updates)
        self.save(state)


# ===== EMAIL NOTIFICATIONS =====

class EmailNotifier:
    """Gestione notifiche email"""
    
    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 25,
        from_email: Optional[str] = None
    ):
        """
        Inizializza email notifier
        
        Args:
            smtp_host: Host SMTP
            smtp_port: Porta SMTP
            from_email: Email mittente
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_email = from_email or f"checkmk@{os.uname().nodename}"
    
    def send_email(
        self,
        to_email: str,
        subject: str,
        body: str,
        html: bool = False
    ) -> bool:
        """
        Invia email
        
        Args:
            to_email: Destinatario
            subject: Oggetto
            body: Corpo messaggio
            html: True se body è HTML
        
        Returns:
            True se invio riuscito, False altrimenti
        """
        try:
            msg = MIMEMultipart('alternative') if html else MIMEText(body)
            
            if html:
                msg.attach(MIMEText(body, 'plain'))
                msg.attach(MIMEText(body, 'html'))
            
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = to_email
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.send_message(msg)
            
            Logger.success(f"Email inviata a {to_email}")
            return True
            
        except Exception as e:
            Logger.error(f"Errore invio email: {e}")
            return False


# ===== UTILITY FUNCTIONS =====

def format_timestamp(timestamp: Optional[int] = None, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """
    Formatta timestamp Unix in stringa
    
    Args:
        timestamp: Timestamp Unix (None = now)
        fmt: Formato output
    
    Returns:
        Stringa formattata
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    return datetime.fromtimestamp(timestamp).strftime(fmt)


def get_current_timestamp() -> int:
    """
    Ottieni timestamp Unix corrente
    
    Returns:
        Timestamp Unix (secondi)
    """
    return int(time.time())


def ensure_directory(path: str):
    """
    Assicura che directory esista, creandola se necessario
    
    Args:
        path: Path directory
    """
    Path(path).mkdir(parents=True, exist_ok=True)


# ===== EXPORTS =====

__all__ = [
    'Logger',
    'CacheManager',
    'ConfigLoader',
    'StateManager',
    'EmailNotifier',
    'format_timestamp',
    'get_current_timestamp',
    'ensure_directory'
]
