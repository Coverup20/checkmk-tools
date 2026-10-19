#!/usr/bin/python3
"""ydea_sync_tickets.py - sync one Ydea customer's tickets into the shadow DB

The Ydea v2 /tickets listing always returns 20 rows per page and ignores
every filter parameter (limit, per_page, search, updatedAfter,
anagrafica_id, anagraficaId, idAnagrafica, cliente): the only way to keep
one customer's tickets is to page through the whole listing and discard
the rows whose anagrafica_id does not match YDEA_SYNC_ANAGRAFICA_ID.

A ticket is kept only when its title starts with the alert prefix
([CRIT - Alert] by default): the customer's ordinary tickets stay out of
the shadow database.

Full ticket details are fetched from /ticket/<id> only when a ticket is
new or its dataModifica changed, so a full scan costs one request per
listing page plus one per changed ticket.

Tables created in the shadow database (kept separate from the
alert-driven tickets/ticket_details/ticket_history tables):
  synced_tickets         one row per ticket, latest known state
  synced_ticket_history  one row per distinct dataModifica
  sync_state             incremental watermark

Usage:
  ydea_sync_tickets.py --full [--dry-run]   scan every listing page
  ydea_sync_tickets.py --recent [N]         newest N pages (default 10)
  ydea_sync_tickets.py --self-test          offline checks, no network

Environment:
  YDEA_ID, YDEA_API_KEY                credentials (required)
  YDEA_SYNC_ANAGRAFICA_ID              customer id to keep (required)
  YDEA_SYNC_TITLE_PREFIX               title prefix to keep, default [CRIT - Alert]
  YDEA_BASE_URL                        API base, default app_api_v2 URL
  YDEA_CACHE_DIR                       default /opt/ydea-toolkit/cache
  YDEA_SYNC_LOG                        default /var/log/ydea-ticket-sync.log
  YDEA_SYNC_PAUSE                      seconds between pages, default 0.5
  YDEA_SYNC_TIMEOUT                    HTTP timeout, default 30

Version: 0.1.3"""

import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: install python3-requests")
    sys.exit(127)

VERSION = "0.1.3"

PAGE_SIZE = 20
MAX_RETRIES = 4
SAFETY_MARGIN_SECONDS = 86400

# Only alert tickets (the ones the monitoring integration creates) are
# synced; every other ticket of the customer stays out of the shadow DB.
DEFAULT_TITLE_PREFIX = "[CRIT - Alert]"

# Disk guards: the shadow DB lives on the Checkmk system volume, so a full
# sync must never be able to fill it. History older than the retention window
# is pruned once the DB passes the size threshold, then the file is vacuumed.
HISTORY_KEEP_DAYS = int(os.environ.get("YDEA_SYNC_HISTORY_KEEP_DAYS", "365"))
DB_MAX_MB = int(os.environ.get("YDEA_SYNC_MAX_DB_MB", "512"))
FREE_SPACE_WARN_MB = 2048

CONFIG = {}


## Useful

def load_env():
    """Load .env from the install directory when credentials are missing."""
    if os.getenv("YDEA_ID") and os.getenv("YDEA_API_KEY"):
        return
    for candidate in (Path(__file__).resolve().parent.parent / ".env",
                      Path("/opt/ydea-toolkit/.env")):
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            os.environ.setdefault(key, value.strip().strip("'\""))
        return


def log(message):
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    print(line, flush=True)
    path = CONFIG.get("log")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass


def epoch_now():
    return int(time.time())


def parse_iso(value):
    """Return a unix timestamp from an ISO 8601 string, or 0."""
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


## API

def is_alert_ticket(data):
    """True when the ticket title carries the alert prefix."""
    prefix = CONFIG.get("title_prefix", DEFAULT_TITLE_PREFIX)
    return (data.get("titolo") or "").startswith(prefix)


def load_token():
    path = Path(CONFIG["token_file"])
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("token")
    except (OSError, ValueError):
        return None


def save_token(token):
    path = Path(CONFIG["token_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"token": token, "obtained_at": epoch_now()}), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def login():
    url = CONFIG["base_url"].rstrip("/") + "/login"
    body = {"id": CONFIG["ydea_id"], "api_key": CONFIG["api_key"]}
    response = requests.post(url, json=body, timeout=CONFIG["timeout"])
    response.raise_for_status()
    data = response.json()
    token = data.get("token") or data.get("access_token") or data.get("jwt") or data.get("id_token")
    if not token:
        raise RuntimeError("login response carried no token")
    save_token(token)
    return token


def api_get(path):
    """GET with token refresh on 401 and backoff on transient errors."""
    url = CONFIG["base_url"].rstrip("/") + "/" + path.lstrip("/")
    token = load_token() or login()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=CONFIG["timeout"],
            )
            if response.status_code == 401:
                token = login()
                continue
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code}")
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == MAX_RETRIES:
                raise
            delay = 2 ** attempt
            log(f"WARN {path}: {exc} - retry in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"GET {path} failed")


def list_page(page):
    return api_get(f"/tickets?page={page}")


def unwrap_ticket(data):
    """The detail endpoint wraps the object as {"atks": ..., "ticket": {...}}."""
    if isinstance(data, dict) and isinstance(data.get("ticket"), dict):
        return data["ticket"]
    return data


def fetch_ticket(ticket_id):
    return unwrap_ticket(api_get(f"/ticket/{ticket_id}"))


## Database

def db_connect():
    conn = sqlite3.connect(CONFIG["db_path"], timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS synced_tickets (
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
            synced_at INTEGER,
            last_seen_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS synced_ticket_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            detected_at INTEGER NOT NULL,
            data_modifica TEXT,
            stato TEXT,
            priorita TEXT,
            assegnato_nome TEXT,
            raw_json TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_synced_history_unique
            ON synced_ticket_history(ticket_id, data_modifica);
        CREATE INDEX IF NOT EXISTS idx_synced_history_ticket
            ON synced_ticket_history(ticket_id, detected_at);
        CREATE INDEX IF NOT EXISTS idx_synced_tickets_anagrafica
            ON synced_tickets(anagrafica_id);
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT INTO sync_state(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    conn.commit()


def ticket_fields(data):
    """Map a /ticket/<id> payload to the synced_tickets columns."""
    assigned = data.get("assegnatoa") or data.get("assegnatoA")
    if isinstance(assigned, dict):
        assigned_name = ", ".join(str(v) for v in assigned.values()) or None
    else:
        assigned_name = str(assigned) if assigned else None
    attributes = data.get("customAttributes")
    return {
        "ticket_id": data.get("id"),
        "codice": data.get("codice"),
        "titolo": data.get("titolo"),
        "descrizione": data.get("descrizione"),
        "stato": data.get("stato"),
        "priorita": data.get("priorita"),
        "tipo": data.get("tipo"),
        "fonte": data.get("fonte"),
        "ragione_sociale": data.get("ragioneSociale"),
        "anagrafica_id": data.get("anagrafica_id"),
        "contratto_codice": data.get("contrattoCodice"),
        "contratto_id": data.get("contrattoId"),
        "assegnato_nome": assigned_name,
        "link": data.get("link"),
        "custom_attributes": json.dumps(attributes, ensure_ascii=False) if attributes else None,
        "data_creazione": data.get("dataCreazione"),
        "data_modifica": data.get("dataModifica"),
        "data_chiusura": data.get("dataChiusura"),
        "raw_json": json.dumps(data, ensure_ascii=False),
    }


def upsert_ticket(conn, fields, dry_run=False):
    """Insert or update one ticket; return True when the row was written."""
    previous = conn.execute(
        "SELECT data_modifica FROM synced_tickets WHERE ticket_id=?", (fields["ticket_id"],)
    ).fetchone()
    changed = previous is None or previous["data_modifica"] != fields["data_modifica"]
    if not changed:
        conn.execute(
            "UPDATE synced_tickets SET last_seen_at=? WHERE ticket_id=?",
            (epoch_now(), fields["ticket_id"]),
        )
        conn.commit()
        return False
    if dry_run:
        return True
    columns = list(fields) + ["synced_at", "last_seen_at"]
    values = list(fields.values()) + [epoch_now(), epoch_now()]
    assignments = ", ".join(f"{name}=excluded.{name}" for name in columns[1:])
    conn.execute(
        f"INSERT INTO synced_tickets({', '.join(columns)}) "
        f"VALUES({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT(ticket_id) DO UPDATE SET {assignments}",
        values,
    )
    try:
        conn.execute(
            "INSERT INTO synced_ticket_history"
            "(ticket_id, detected_at, data_modifica, stato, priorita, assegnato_nome, raw_json) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                fields["ticket_id"],
                epoch_now(),
                fields["data_modifica"],
                fields["stato"],
                fields["priorita"],
                fields["assegnato_nome"],
                fields["raw_json"],
            ),
        )
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    return True


## Disk guards

def db_size_mb():
    try:
        return os.path.getsize(CONFIG["db_path"]) / 1048576
    except OSError:
        return 0.0


def free_space_mb():
    try:
        return shutil.disk_usage(CONFIG["cache_dir"]).free / 1048576
    except OSError:
        return -1


def prune_history(conn, keep_days):
    cutoff = epoch_now() - keep_days * 86400
    return conn.execute(
        "DELETE FROM synced_ticket_history WHERE detected_at < ?", (cutoff,)
    ).rowcount


def enforce_limits(conn, dry_run=False):
    """Keep the DB bounded: prune old history past the size threshold."""
    free = free_space_mb()
    if 0 <= free < FREE_SPACE_WARN_MB:
        log(f"WARN low disk space: {free:.0f} MB free")
        if free < 512:
            log("ERROR less than 512 MB free, skipping writes and vacuum")
            return
    size = db_size_mb()
    if size > DB_MAX_MB:
        log(f"DB is {size:.1f} MB (limit {DB_MAX_MB} MB): pruning history older than {HISTORY_KEEP_DAYS} days")
        if not dry_run:
            removed = prune_history(conn, HISTORY_KEEP_DAYS)
            conn.commit()
            log(f"Pruned {removed} history rows")
            if free_space_mb() > 4096:
                conn.execute("VACUUM")
                log(f"Vacuum done, DB now {db_size_mb():.1f} MB")
    else:
        log(f"DB size {size:.1f} MB, free space {free:.0f} MB")


## Sync

def should_stop(page_items, watermark):
    """True when a page reached tickets older than the incremental watermark."""
    if not watermark or not page_items:
        return False
    oldest = min(parse_iso(item.get("dataCreazione")) for item in page_items)
    return oldest < watermark


def sync_once(full=True, recent_pages=10, dry_run=False, max_pages=None):
    anagrafica_id = CONFIG["anagrafica_id"]
    conn = db_connect()
    init_schema(conn)

    watermark = None
    if not full:
        stored = get_state(conn, "last_full_scan_utc")
        if stored:
            watermark = int(stored) - SAFETY_MARGIN_SECONDS
    started = epoch_now()

    page = 1
    matched = 0
    written = 0
    skipped = 0
    while True:
        if max_pages and page > max_pages:
            log(f"Stopped at --max-pages {max_pages}")
            break
        if not full and page > recent_pages:
            log(f"Stopped after {recent_pages} pages (recent mode)")
            break
        data = list_page(page)
        items = data.get("objs") or []
        if not items:
            break
        for item in items:
            if int(item.get("anagrafica_id") or 0) != anagrafica_id:
                continue
            listed_title = item.get("titolo") or ""
            if listed_title and not is_alert_ticket(item):
                continue
            matched += 1
            try:
                detail = fetch_ticket(item["id"])
            except Exception as exc:
                log(f"WARN ticket {item.get('id')}: {exc}")
                continue
            if not is_alert_ticket(detail):
                skipped += 1
                continue
            if upsert_ticket(conn, ticket_fields(detail), dry_run=dry_run):
                written += 1
                log(f"{'DRY ' if dry_run else ''}updated {item.get('id')} {item.get('codice')}")
        last_page = int(data.get("lastPage") or page)
        if page >= last_page:
            break
        if not full and should_stop(items, watermark):
            log("Reached watermark, stopping incremental scan")
            break
        page += 1
        time.sleep(CONFIG["pause"])

    if full and not dry_run:
        set_state(conn, "last_full_scan_utc", started)
        enforce_limits(conn)
    set_state(conn, "last_run_utc", epoch_now())
    conn.close()
    log(f"Done: pages={page} matched={matched} written={written} skipped={skipped} dry_run={dry_run}")


## Self-test

def self_test():
    checks = []
    global CONFIG

    sample = {"id": 1, "codice": "TK1", "titolo": "t", "stato": "Aperto", "dataModifica": "2026-01-01T00:00:00+00:00",
              "ragioneSociale": "X", "anagrafica_id": 7, "assegnatoA": {"1": "A", "2": "B"}}

    fields = ticket_fields(sample)
    checks.append(("fields map", fields["ticket_id"] == 1 and fields["assegnato_nome"] == "A, B"))
    checks.append(("parse_iso", parse_iso("1970-01-01T00:01:40+00:00") == 100))
    checks.append(("parse_iso invalid", parse_iso("nope") == 0))

    wrapped = {"atks": [], "ticket": sample}
    checks.append(("unwrap ticket", unwrap_ticket(wrapped) is sample))
    checks.append(("plain payload kept", unwrap_ticket(sample) is sample))

    CONFIG["title_prefix"] = DEFAULT_TITLE_PREFIX
    checks.append(("alert title kept", is_alert_ticket({"titolo": "[CRIT - Alert] fs-windows - Filesystem"})))
    checks.append(("other title dropped", not is_alert_ticket({"titolo": "Richiesta assistenza"})))

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    checks.append(("insert new", upsert_ticket(conn, fields) is True))
    checks.append(("same data_modifica", upsert_ticket(conn, fields) is False))
    history = conn.execute("SELECT count(*) FROM synced_ticket_history").fetchone()[0]
    checks.append(("one history row", history == 1))

    changed = dict(fields)
    changed["data_modifica"] = "2026-01-02T00:00:00+00:00"
    changed["stato"] = "Chiuso"
    checks.append(("update changed", upsert_ticket(conn, changed) is True))
    history = conn.execute("SELECT count(*) FROM synced_ticket_history").fetchone()[0]
    checks.append(("two history rows", history == 2))
    row = conn.execute("SELECT stato FROM synced_tickets WHERE ticket_id=1").fetchone()
    checks.append(("latest state", row["stato"] == "Chiuso"))

    watermark = parse_iso("2026-01-05T00:00:00+00:00")
    checks.append(("stop below watermark", should_stop([{"dataCreazione": "2026-01-01T00:00:00+00:00"}], watermark)))
    checks.append(("no stop above watermark", not should_stop([{"dataCreazione": "2026-01-06T00:00:00+00:00"}], watermark)))
    checks.append(("no stop without watermark", not should_stop([{"dataCreazione": "2026-01-01T00:00:00+00:00"}], None)))

    old = epoch_now() - 400 * 86400
    fresh = epoch_now() - 10 * 86400
    for detected in (old, fresh):
        conn.execute(
            "INSERT INTO synced_ticket_history(ticket_id, detected_at) VALUES(2, ?)",
            (detected,),
        )
    conn.commit()
    removed = prune_history(conn, 365)
    left = conn.execute("SELECT count(*) FROM synced_ticket_history WHERE ticket_id=2").fetchone()[0]
    checks.append(("prune old history", removed == 1 and left == 1))

    conn.close()

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"Self-test: {len(checks) - len(failed)}/{len(checks)} passed")
    return not failed


## Main

def main():
    load_env()
    CONFIG.update({
        "base_url": os.getenv("YDEA_BASE_URL", "https://my.ydea.cloud/app_api_v2"),
        "ydea_id": os.getenv("YDEA_ID", ""),
        "api_key": os.getenv("YDEA_API_KEY", ""),
        "cache_dir": os.getenv("YDEA_CACHE_DIR", "/opt/ydea-toolkit/cache"),
        "log": os.getenv("YDEA_SYNC_LOG", "/var/log/ydea-ticket-sync.log"),
        "pause": float(os.getenv("YDEA_SYNC_PAUSE", "0.5")),
        "timeout": float(os.getenv("YDEA_SYNC_TIMEOUT", "30")),
        "title_prefix": os.getenv("YDEA_SYNC_TITLE_PREFIX", DEFAULT_TITLE_PREFIX),
    })
    CONFIG["db_path"] = os.getenv("YDEA_DB_PATH") or os.path.join(CONFIG["cache_dir"], "ydea_checkmk.db")
    CONFIG["token_file"] = os.getenv("YDEA_SYNC_TOKEN_FILE") or os.path.join(CONFIG["cache_dir"], "ydea_sync_token.json")
    anagrafica = os.getenv("YDEA_SYNC_ANAGRAFICA_ID", "")
    if not anagrafica.isdigit():
        log("ERROR YDEA_SYNC_ANAGRAFICA_ID must be set to a numeric customer id")
        sys.exit(2)
    CONFIG["anagrafica_id"] = int(anagrafica)
    if not CONFIG["ydea_id"] or not CONFIG["api_key"]:
        log("ERROR YDEA_ID and YDEA_API_KEY must be set")
        sys.exit(2)

    full = "--full" in sys.argv or "--recent" not in sys.argv
    recent_pages = 10
    if "--recent" in sys.argv:
        index = sys.argv.index("--recent") + 1
        if index < len(sys.argv) and sys.argv[index].isdigit():
            recent_pages = int(sys.argv[index])
    max_pages = None
    if "--max-pages" in sys.argv:
        index = sys.argv.index("--max-pages") + 1
        if index < len(sys.argv):
            max_pages = int(sys.argv[index])
    log(f"ydea_sync_tickets v{VERSION} start anagrafica={CONFIG['anagrafica_id']} mode={'full' if full else 'recent'} dry_run={'--dry-run' in sys.argv}")
    sync_once(full=full, recent_pages=recent_pages, dry_run="--dry-run" in sys.argv, max_pages=max_pages)


if "--self-test" in sys.argv:
    sys.exit(0 if self_test() else 1)
else:
    main()
