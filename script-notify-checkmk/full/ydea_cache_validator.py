#!/usr/bin/env python3
"""ydea_cache_validator.py - Cache Integrity Validator for Ydea Integration

Periodically checks if tickets in the local JSON cache actually exist on Ydea.
Removes "orphan" entries (tickets present in cache but deleted on Ydea).
Prevents cache misalignment issues.

Usage: python3 ydea_cache_validator.py [--dry-run]"""

import os
import sys
import json
import subprocess
import fcntl
import sqlite3
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

VERSION = "1.1.0"

# ===== CONFIG (Must match ydea_la.py) =====
YDEA_TOOLKIT_DIR = "/opt/ydea-toolkit"
YDEA_ENV_LA = f"{YDEA_TOOLKIT_DIR}/.env.la"
YDEA_ENV_AG = f"{YDEA_TOOLKIT_DIR}/.env.ag"
YDEA_CACHE_DIR = "/opt/ydea-toolkit/cache"
TICKET_CACHE = f"{YDEA_CACHE_DIR}/ydea_checkmk_tickets.json"
CACHE_LOCK = f"{YDEA_CACHE_DIR}/ydea_cache.lock"
YDEA_TOOLKIT_TIMEOUT = int(os.getenv("YDEA_TOOLKIT_TIMEOUT", "25"))

# Same shadow database ydea_la.py/ydea_ag.py write to - this script is the
# only one that ever stores the full Ydea-side fields (title, status,
# assignee, link, company, ...), reusing the 'get' call it already makes
# for orphan detection instead of an extra API round trip.
DB_PATH = f"{YDEA_CACHE_DIR}/ydea_checkmk.db"

DRY_RUN = "--dry-run" in sys.argv


def resolve_toolkit_command() -> Optional[List[str]]:
    """Resolve ydea toolkit executable (prefer Python implementation)."""
    python_cmd = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else "python3"
    candidates: List[Tuple[str, List[str]]] = [
        (f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.py", [python_cmd, f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.py"]),
        (f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.py", [python_cmd, f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.py"]),
        (f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.sh", [f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.sh"]),
        (f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.sh", [f"{YDEA_TOOLKIT_DIR}/rydea-toolkit.sh"]),
    ]
    for check_path, cmd in candidates:
        if os.path.exists(check_path):
            return cmd
    return None

def log(msg: str):
    """Log message to stderr."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", file=sys.stderr)

def toolkit_cmd(args: List[str], timeout: Optional[int] = None, env_file: Optional[str] = None) -> Tuple[int, str, str]:
    """Execute ydea-toolkit command with environment loaded from YDEA_ENV."""
    if timeout is None:
        timeout = YDEA_TOOLKIT_TIMEOUT
    
    # Load environment variables from selected env file
    env = os.environ.copy()
    selected_env = env_file or YDEA_ENV_LA
    if os.path.exists(selected_env):
        try:
            with open(selected_env, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        line = line.replace('export ', '', 1).strip()
                        key, value = line.split('=', 1)
                        value = value.strip().strip('"').strip("'")
                        value = value.replace('${HOME}', os.path.expanduser('~'))
                        env[key.strip()] = value
        except Exception as e:
            log(f"WARNING: Failed to load {selected_env}: {e}")
    
    base_cmd = resolve_toolkit_command()
    if not base_cmd:
        log(
            "ERROR: Ydea toolkit not found "
            f"(checked: {YDEA_TOOLKIT_DIR}/ydea-toolkit.py, {YDEA_TOOLKIT_DIR}/rydea-toolkit.py, "
            f"{YDEA_TOOLKIT_DIR}/ydea-toolkit.sh, {YDEA_TOOLKIT_DIR}/rydea-toolkit.sh)"
        )
        return 127, "", "Command not found"

    cmd = base_cmd + args
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=env
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        log(f"ERROR: toolkit command timeout after {timeout}s")
        return 124, "", "Timeout"
    except Exception as e:
        log(f"ERROR: toolkit command failed: {e}")
        return 1, "", str(e)

def atomic_cache_write(cache_file: str, content: str) -> bool:
    """Atomic cache write with flock."""
    if DRY_RUN:
        log("[DRY-RUN] Would write cache file")
        return True

    cache_path = Path(cache_file)
    cache_dir = cache_path.parent
    
    # Check permissions
    if not os.access(cache_dir, os.W_OK):
        try:
            # Try to fix permissions if we are root/owner
            os.chmod(cache_file, 0o666)
        except:
            pass
        if not os.access(cache_dir, os.W_OK):
            log(f"ERROR: No write permission on {cache_dir}")
            return False
    
    temp_file = f"{cache_file}.tmp.{os.getpid()}"
    lock_file = Path(CACHE_LOCK)
    
    try:
        lock_file.touch(mode=0o666, exist_ok=True)
        
        with open(lock_file, 'r') as lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except IOError:
                # Wait for lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            
            with open(temp_file, 'w') as f:
                f.write(content)
            os.chmod(temp_file, 0o666)
            os.sync()
            
            os.replace(temp_file, cache_file)
            os.chmod(cache_file, 0o666)
            os.sync()
            
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        
        return True
        
    except Exception as e:
        log(f"ERROR: atomic_cache_write failed: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False

def iter_env_files() -> List[Optional[str]]:
    """Return env files to test in order (LA then AG if present)."""
    envs: List[Optional[str]] = []
    if os.path.exists(YDEA_ENV_LA):
        envs.append(YDEA_ENV_LA)
    if os.path.exists(YDEA_ENV_AG) and YDEA_ENV_AG not in envs:
        envs.append(YDEA_ENV_AG)
    if not envs:
        envs.append(None)
    return envs


def is_not_found_output(output_lower: str) -> bool:
    """Detect not-found responses across Ydea toolkit variants.

    NOTE: 'non trovato' / 'ticket non trovato' are intentionally excluded.
    The toolkit resolves ticket existence via GET /tickets?limit=100 (list search),
    not via GET /tickets/{id}. A ticket outside the first 100 results returns
    'Ticket non trovato' even when it actually exists, causing false cache
    invalidation. Only explicit HTTP 404 responses are a reliable signal.
    """
    return (
        '404' in output_lower
        or 'not found' in output_lower
    )


def _fix_db_perms():
    """Make the db file and its WAL/SHM sidecars world-writable - this
    script runs as root via cron while ydea_la.py/ydea_ag.py run as the
    OMD site user, so whichever touches the file first must not lock the
    other out (same reasoning as _fix_db_perms in ydea_la.py)."""
    for suffix in ("", "-wal", "-shm"):
        path = DB_PATH + suffix
        if os.path.exists(path):
            try:
                os.chmod(path, 0o666)
            except Exception:
                pass


def _db_connect() -> Optional["sqlite3.Connection"]:
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        _fix_db_perms()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
    except Exception as e:
        log(f"WARN: db_connect failed: {e}")
        return None


def init_details_table():
    conn = _db_connect()
    if not conn:
        return
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_details (
                ticket_id INTEGER PRIMARY KEY,
                codice TEXT,
                titolo TEXT,
                descrizione TEXT,
                stato TEXT,
                priorita TEXT,
                tipo TEXT,
                fonte TEXT,
                ragione_sociale TEXT,
                anagrafica_id INTEGER,
                contratto_codice TEXT,
                contratto_id INTEGER,
                assegnato_nome TEXT,
                link TEXT,
                custom_attributes TEXT,
                data_creazione TEXT,
                data_modifica TEXT,
                data_chiusura TEXT,
                raw_json TEXT,
                synced_at INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ticket_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id INTEGER,
                detected_at INTEGER,
                codice TEXT,
                titolo TEXT,
                descrizione TEXT,
                stato TEXT,
                priorita TEXT,
                tipo TEXT,
                fonte TEXT,
                ragione_sociale TEXT,
                contratto_codice TEXT,
                assegnato_nome TEXT,
                link TEXT,
                data_modifica TEXT,
                raw_json TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_ticket ON ticket_history(ticket_id, detected_at)")
        conn.commit()
    except Exception as e:
        log(f"WARN: init_details_table failed: {e}")
    finally:
        conn.close()
        _fix_db_perms()


def _extract_assignee(data: Dict[Any, Any]) -> Optional[str]:
    assigned = data.get("assegnatoa") or data.get("assegnatoA")
    if isinstance(assigned, dict):
        return ", ".join(str(v) for v in assigned.values()) if assigned else None
    return str(assigned) if assigned else None


def sync_ticket_details(ticket_id: int, stdout: str):
    """Parse the ticket JSON already fetched by check_ticket_exists and
    store every field Ydea gives us. Best-effort: never raises, a failure
    here must not affect the orphan-cleanup logic that calls this."""
    try:
        data = json.loads(stdout)
    except Exception as e:
        log(f"WARN: sync_ticket_details({ticket_id}) - could not parse JSON: {e}")
        return

    conn = _db_connect()
    if not conn:
        return
    try:
        new_data_modifica = data.get("dataModifica")
        previous = conn.execute(
            "SELECT data_modifica FROM ticket_details WHERE ticket_id=?", (ticket_id,)
        ).fetchone()
        changed = previous is None or previous[0] != new_data_modifica

        if changed:
            conn.execute("""
                INSERT INTO ticket_history (
                    ticket_id, detected_at, codice, titolo, descrizione, stato, priorita, tipo,
                    fonte, ragione_sociale, contratto_codice, assegnato_nome, link,
                    data_modifica, raw_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ticket_id, int(time.time()),
                data.get("codice"), data.get("titolo"), data.get("descrizione"),
                data.get("stato"), data.get("priorita"), data.get("tipo"), data.get("fonte"),
                data.get("ragioneSociale"), data.get("contrattoCodice"),
                _extract_assignee(data), data.get("link"),
                new_data_modifica, json.dumps(data, ensure_ascii=False)
            ))
            log(f"Ticket #{ticket_id}: dataModifica cambiata ({previous[0] if previous else 'nuovo'} -> {new_data_modifica}), storico aggiornato")

        conn.execute("""
            INSERT INTO ticket_details (
                ticket_id, codice, titolo, descrizione, stato, priorita, tipo, fonte,
                ragione_sociale, anagrafica_id, contratto_codice, contratto_id,
                assegnato_nome, link, custom_attributes, data_creazione, data_modifica,
                data_chiusura, raw_json, synced_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                codice=excluded.codice, titolo=excluded.titolo, descrizione=excluded.descrizione,
                stato=excluded.stato, priorita=excluded.priorita, tipo=excluded.tipo,
                fonte=excluded.fonte, ragione_sociale=excluded.ragione_sociale,
                anagrafica_id=excluded.anagrafica_id, contratto_codice=excluded.contratto_codice,
                contratto_id=excluded.contratto_id, assegnato_nome=excluded.assegnato_nome,
                link=excluded.link, custom_attributes=excluded.custom_attributes,
                data_creazione=excluded.data_creazione, data_modifica=excluded.data_modifica,
                data_chiusura=excluded.data_chiusura, raw_json=excluded.raw_json,
                synced_at=excluded.synced_at
        """, (
            ticket_id,
            data.get("codice"), data.get("titolo"), data.get("descrizione"),
            data.get("stato"), data.get("priorita"), data.get("tipo"), data.get("fonte"),
            data.get("ragioneSociale"), data.get("anagrafica_id"),
            data.get("contrattoCodice"), data.get("contrattoId"),
            _extract_assignee(data), data.get("link"),
            json.dumps(data.get("customAttributes"), ensure_ascii=False) if data.get("customAttributes") else None,
            data.get("dataCreazione"), data.get("dataModifica"), data.get("dataChiusura"),
            json.dumps(data, ensure_ascii=False),
            int(time.time())
        ))
        conn.commit()
    except Exception as e:
        log(f"WARN: sync_ticket_details({ticket_id}) failed: {e}")
    finally:
        conn.close()


def check_ticket_exists(ticket_id: int) -> bool:
    """Verify if ticket exists on Ydea API. Also syncs the full ticket
    record into the shadow SQLite database (ticket_details) when found,
    reusing this same API response instead of a second round trip."""
    saw_not_found = False

    for env_file in iter_env_files():
        exitcode, stdout, stderr = toolkit_cmd(['get', str(ticket_id)], env_file=env_file)

        if exitcode == 0:
            sync_ticket_details(ticket_id, stdout)
            return True

        output_lower = (stdout + stderr).lower()
        if is_not_found_output(output_lower):
            saw_not_found = True
            continue

        # Other errors (500, timeout, auth) -> assume exists to be safe
        source = env_file if env_file else "process-env"
        log(f"WARN: API check failed for #{ticket_id} via {source} (code {exitcode}), assuming valid.")
        return True

    return not saw_not_found

def main():
    log("Starting Ydea Cache Validation...")
    if DRY_RUN:
        log("Running in DRY-RUN mode (no changes will be applied)")

    init_details_table()

    if not os.path.exists(TICKET_CACHE):
        log("No cache file found. Exiting.")
        return

    try:
        with open(TICKET_CACHE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        log(f"ERROR: Failed to load cache: {e}")
        return

    tickets_to_remove = []
    total_tickets = len(data)
    log(f"Found {total_tickets} tickets in cache.")

    for i, (key, info) in enumerate(data.items(), 1):
        ticket_id = info.get('ticket_id')
        if not ticket_id:
            continue
            
        print(f"[{i}/{total_tickets}] Checking {key} -> #{ticket_id}... ", end='', flush=True)
        
        if check_ticket_exists(ticket_id):
            print("OK")
        else:
            print("MISSING (404)")
            tickets_to_remove.append(key)
        
        # Small sleep to be nice to the API
        time.sleep(1)

    if not tickets_to_remove:
        log("Cache is healthy. No changes needed.")
        return

    log(f"Found {len(tickets_to_remove)} invalid tickets. Cleaning up...")
    
    for key in tickets_to_remove:
        log(f"Removing invalid entry: {key} (Ticket #{data[key]['ticket_id']})")
        del data[key]

    if atomic_cache_write(TICKET_CACHE, json.dumps(data)):
        log("Cache updated successfully.")
    else:
        log("Failed to update cache file.")

if __name__ == "__main__":
    main()
