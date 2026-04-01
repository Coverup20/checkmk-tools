#!/usr/bin/env python3
"""check_ns8_services.py - CheckMK Local Check for NS8 Mail Services

Monitor main email services (clamav, rspamd, dovecot, postfix).
Special controls for Dovecot:
- Active IMAP sessions
- vsz_limit errors in logs (CRITICAL if present)
- VszLimit configuration (WARNING if not set)

Version: 1.0.0"""

import subprocess
import sys
import re
from typing import Tuple, List, Optional, Dict

VERSION = "1.0.0"
LOG_LINES = 500  # Numero righe log da analizzare

TARGET_SERVICES = ['clamav', 'rspamd', 'dovecot', 'postfix']


def run_command(cmd: List[str]) -> Tuple[int, str, str]:
    """Execute a shell command and return exit code, stdout, stderr.
    
    Args:
        cmd: Command as list of strings
        
    Returns:
        Tuple of (exit_code, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def get_mail_instances() -> List[str]:
    """Get list of mail instances via runagent.
    
    Returns:
        List of mail instance names (e.g., ['mail1', 'mail2'])"""
    exit_code, stdout, stderr = run_command(['runagent', '-l'])
    
    if exit_code != 0:
        return []
    
    instances = []
    for line in stdout.split('\n'):
        line = line.strip()
        if line.startswith('mail'):
            instances.append(line)
    
    return instances


def get_container_status(instance: str) -> Dict[str, str]:
    """Get container names and status via podman ps.
    
    Args:
        instance: Mail instance name
        
    Returns:
        Dict mapping container_name -> status (e.g., {'dovecot': 'Up'})"""
    exit_code, stdout, stderr = run_command([
        'runagent', '-m', instance, 'podman', 'ps',
        '--format', '{{.Names}} {{.Status}}'
    ])
    
    if exit_code != 0 or not stdout:
        return {}
    
    status_map = {}
    for line in stdout.split('\n'):
        parts = line.strip().split(None, 1)
        if len(parts) >= 2:
            name = parts[0]
            status = parts[1].split()[0]  # Get first word (Up/Down/etc)
            status_map[name] = status
    
    return status_map


def get_imap_sessions(instance: str) -> int:
    """Get count of IMAP sessions via doveadm who.
    
    Args:
        instance: Mail instance name
        
    Returns:
        Count of IMAP sessions"""
    exit_code, stdout, stderr = run_command([
        'runagent', '-m', instance, 'podman', 'exec', 'dovecot',
        'doveadm', 'who'
    ])
    
    if exit_code != 0 or not stdout:
        return 0
    
    # Count lines (each line = one session)
    return len(stdout.split('\n'))


def get_vsz_limit(instance: str) -> Optional[str]:
    """Get VszLimit configuration from config show dovecot.
    
    Args:
        instance: Mail instance name
        
    Returns:
        VszLimit value as string or None if not set"""
    exit_code, stdout, stderr = run_command(['config', 'show', 'dovecot'])
    
    if exit_code != 0 or not stdout:
        return None
    
    # Search for VszLimit line (case insensitive)
    for line in stdout.split('\n'):
        if re.search(r'vszlimit', line, re.IGNORECASE):
            parts = line.split()
            if len(parts) >= 2:
                return parts[1]
    
    return None


def count_vsz_errors(instance: str) -> int:
    """Count vsz_limit error occurrences in recent dovecot logs.
    
    Args:
        instance: Mail instance name
        
    Returns:
        Count of vsz_limit errors in last LOG_LINES"""
    # Build shell command to tail logs and grep for errors
    shell_cmd = f"tail -n {LOG_LINES} /var/log/dovecot* 2>/dev/null | grep -c 'Cannot allocate memory due to vsz_limit'"
    
    exit_code, stdout, stderr = run_command([
        'runagent', '-m', instance, 'podman', 'exec', 'dovecot',
        'sh', '-c', shell_cmd
    ])
    
    if exit_code != 0 or not stdout:
        return 0
    
    try:
        return int(stdout.strip())
    except ValueError:
        return 0


def check_dovecot_extras(instance: str) -> None:
    """Perform extra checks for dovecot: IMAP sessions and vsz_limit.
    
    Args:
        instance: Mail instance name"""
    # IMAP sessions
    imap_count = get_imap_sessions(instance)
    
    if imap_count > 0:
        print(f"0 imap_sessions - Sessioni IMAP attive: {imap_count}")
    else:
        print(f"1 imap_sessions - Nessuna sessione IMAP attiva")
    
    # VszLimit configuration
    vsz_limit = get_vsz_limit(instance)
    
    # Count vsz_limit errors in logs
    error_count = count_vsz_errors(instance)
    
    # Evaluate state based on errors and configuration
    if error_count > 0:
        # CRITICAL if errors found (regardless of config)
        if vsz_limit:
            print(f"2 dovecot_vszlimit - CRIT: rilevato vsz_limit ({error_count} occorrenze nelle ultime {LOG_LINES} righe, limite configurato={vsz_limit})")
        else:
            print(f"2 dovecot_vszlimit - CRIT: rilevato vsz_limit ({error_count} occorrenze nelle ultime {LOG_LINES} righe, limite non impostato)")
    else:
        # No errors
        if vsz_limit:
            # OK: no errors and limit is set
            print(f"0 dovecot_vszlimit - Nessun allarme nei log (limite configurato={vsz_limit})")
        else:
            # WARNING: no errors but limit not set
            print(f"1 dovecot_vszlimit - WARNING: Nessun allarme nei log (limite non impostato)")


def main() -> int:
    """Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)"""
    mail_instances = get_mail_instances()
    
    if not mail_instances:
        # No mail instances found, silent exit
        return 0
    
    for instance in mail_instances:
        # Get container status for this instance
        container_status = get_container_status(instance)
        
        for service in TARGET_SERVICES:
            if service in container_status:
                status = container_status[service]
                
                if status == 'Up':
                    print(f"0 {service} - {service} attivo")
                    
                    # Extra checks for dovecot
                    if service == 'dovecot':
                        check_dovecot_extras(instance)
                else:
                    print(f"2 {service} - {service} non attivo")
            else:
                print(f"3 {service} - {service} non trovato")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
