#!/usr/bin/env python3
"""
check_podman_events.py - CheckMK Local Check per Eventi Podman

Monitora eventi recenti Podman (ultimi 5 minuti) da log file.
Mostra ultimo evento rilevante (create/start/stop/remove) escludendo redis.

Version: 1.0.0
"""

import sys
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

VERSION = "1.0.0"
SERVICE = "Podman_Status"
LOGFILE = Path("/var/log/podman_events.log")
TIME_WINDOW_MINUTES = 5


def get_recent_timestamp() -> str:
    """
    Calculate timestamp for filtering recent events (5 minutes ago).
    
    Returns:
        Timestamp string in format 'YYYY-MM-DD HH:MM:SS'
    """
    recent = datetime.now() - timedelta(minutes=TIME_WINDOW_MINUTES)
    return recent.strftime("%Y-%m-%d %H:%M:%S")


def parse_log_events() -> Optional[Tuple[str, str]]:
    """
    Parse podman events log and extract last relevant event.
    
    Filters:
    - Only events after TIME_WINDOW_MINUTES ago
    - Only actions: create, start, stop, remove
    - Excludes redis containers
    
    Returns:
        Tuple of (container_name, action) or None if no events
    """
    if not LOGFILE.exists():
        return None
    
    try:
        recent_ts = get_recent_timestamp()
        relevant_events = []
        
        with open(LOGFILE, 'r') as f:
            for line in f:
                # Skip lines older than recent_ts
                if line.strip() < recent_ts:
                    continue
                
                # Skip redis containers (case insensitive)
                if re.search(r'redis', line, re.IGNORECASE):
                    continue
                
                # Filter only relevant actions
                if re.search(r'\s(create|start|stop|remove)\s', line):
                    relevant_events.append(line.strip())
        
        if not relevant_events:
            return None
        
        # Parse last event: extract action (field 5) and name (field 6)
        last_event = relevant_events[-1]
        parts = last_event.split()
        
        if len(parts) >= 6:
            action = parts[4]  # Field 5 (0-indexed = 4)
            name = parts[5]    # Field 6 (0-indexed = 5)
            return (name, action)
        
        return None
        
    except Exception as e:
        # Fail silently, return no events
        return None


def main() -> int:
    """
    Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)
    """
    event = parse_log_events()
    
    if event:
        name, action = event
        # Capitalize first letter for display
        name_display = name.capitalize()
        action_display = action.capitalize()
        
        # WARNING state when event detected
        print(f"1 {SERVICE} - {name_display} {action_display}")
    else:
        # OK state when no events
        print(f"0 {SERVICE} - Nessun Evento")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
