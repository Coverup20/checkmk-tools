#!/usr/bin/env python3
"""ydea_db_browser - read-only web viewer for the Ydea ticket shadow-write SQLite cache.

Binds to 127.0.0.1 only - reachable exclusively via SSH tunnel or locally on
the host. Opens the database in SQLite's own read-only URI mode, so even a
bug here cannot write to or corrupt the cache the notification scripts use.
Serves HTTPS with a self-signed certificate and requires HTTP Basic Auth.

All Ydea-side fields (title, status, assignee, link, company, ...) come from
the ticket_details table, kept in sync by ydea_cache_validator.py - this
viewer never calls the Ydea API itself, it only reads the local database.

Version: 3.0.0"""

import base64
import html
import os
import secrets
import sqlite3
import ssl
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = "/opt/ydea-toolkit/cache/ydea_checkmk.db"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765

CONFIG_DIR = "/opt/ydea-toolkit/config"
AUTH_FILE = f"{CONFIG_DIR}/db_browser_auth"
CERT_FILE = f"{CONFIG_DIR}/db_browser.crt"
KEY_FILE = f"{CONFIG_DIR}/db_browser.key"


def fmt_ts(ts):
    if ts is None:
        return "-"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def fmt_iso(iso):
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return html.escape(str(iso))


def query_tickets(search: str = ""):
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        where = "WHERE t.key LIKE ? OR d.ragione_sociale LIKE ? OR d.titolo LIKE ?" if search else ""
        params = (f"%{search}%", f"%{search}%", f"%{search}%") if search else ()
        rows = conn.execute(f"""
            SELECT t.key, t.ticket_id, t.created_at AS cmk_created_at, t.last_update AS cmk_last_update,
                   d.codice, d.titolo, d.stato, d.priorita, d.tipo, d.ragione_sociale,
                   d.contratto_codice, d.assegnato_nome, d.link,
                   d.data_creazione, d.data_modifica, d.data_chiusura, d.synced_at
            FROM tickets t
            LEFT JOIN ticket_details d ON d.ticket_id = t.ticket_id
            {where}
            ORDER BY t.last_update DESC
        """, params).fetchall()
    finally:
        conn.close()
    return rows


def render_page(search: str = "") -> bytes:
    try:
        rows = query_tickets(search)
        error = None
    except Exception as e:
        rows, error = [], str(e)

    body_rows = []
    for r in rows:
        link = r["link"] or f"https://my.ydea.cloud/ticket/{r['ticket_id']}"
        synced_note = fmt_ts(r["synced_at"]) if r["synced_at"] else "mai sincronizzato"
        body_rows.append(f"""
        <tr>
            <td>{html.escape(r["key"])}</td>
            <td><a href="{html.escape(link)}" target="_blank" rel="noopener">{html.escape(r["codice"] or f"#{r['ticket_id']}")}</a></td>
            <td>{html.escape(r["titolo"] or "-")}</td>
            <td>{html.escape(r["stato"] or "-")}</td>
            <td>{html.escape(r["priorita"] or "-")}</td>
            <td>{html.escape(r["tipo"] or "-")}</td>
            <td>{html.escape(r["assegnato_nome"] or "-")}</td>
            <td>{html.escape(r["ragione_sociale"] or "-")}</td>
            <td>{html.escape(r["contratto_codice"] or "-")}</td>
            <td>{fmt_iso(r["data_creazione"])}</td>
            <td>{fmt_iso(r["data_modifica"])}</td>
            <td>{fmt_iso(r["data_chiusura"])}</td>
            <td title="ultimo sync da ydea_cache_validator.py">{synced_note}</td>
        </tr>""")

    error_html = f'<p class="error">Errore: {html.escape(error)}</p>' if error else ""

    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Ydea ticket cache (sola lettura)</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #111; color: #ddd; }}
  h1 {{ font-size: 1.3rem; }}
  .meta {{ color: #888; font-size: 0.85rem; margin-bottom: 1rem; }}
  form {{ margin-bottom: 1rem; }}
  input[type=text] {{ padding: 0.4rem; width: 20rem; background: #222; color: #eee; border: 1px solid #444; }}
  button {{ padding: 0.4rem 0.8rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ border: 1px solid #333; padding: 0.35rem 0.5rem; text-align: left; white-space: nowrap; }}
  th {{ background: #1b1b1b; }}
  a {{ color: #6cf; }}
  .error {{ color: #e55; }}
</style>
</head>
<body>
<h1>Ydea ticket cache - shadow SQLite (sola lettura)</h1>
<div class="meta">DB: {html.escape(DB_PATH)} - JSON resta la fonte autorevole per le decisioni dello script di notifica. I campi Ydea (stato, assegnatario, ...) sono sincronizzati periodicamente da ydea_cache_validator.py, non letti in tempo reale.</div>
<form method="get">
  <input type="text" name="q" placeholder="filtra per host, azienda o titolo..." value="{html.escape(search)}">
  <button type="submit">Cerca</button>
</form>
{error_html}
<table>
<tr>
  <th>Host/key</th><th>Ticket</th><th>Titolo</th><th>Stato</th><th>Priorita</th><th>Tipo</th>
  <th>Assegnatario</th><th>Azienda</th><th>Contratto</th>
  <th>Creato (Ydea)</th><th>Modificato (Ydea)</th><th>Chiuso (Ydea)</th><th>Sync</th>
</tr>
{"".join(body_rows) if body_rows else "<tr><td colspan='13'>Nessun ticket in cache.</td></tr>"}
</table>
</body>
</html>""".encode("utf-8")


def load_credentials():
    """Read 'username:password' from AUTH_FILE. Generates one on first run
    if missing, so a fresh deploy never starts without auth."""
    if not os.path.exists(AUTH_FILE):
        os.makedirs(CONFIG_DIR, exist_ok=True, mode=0o750)
        username = "ydea-viewer"
        password = secrets.token_urlsafe(18)
        with open(AUTH_FILE, "w") as f:
            f.write(f"{username}:{password}\n")
        os.chmod(AUTH_FILE, 0o600)
        print(f"Generated credentials in {AUTH_FILE}: {username}:{password}")
    with open(AUTH_FILE, "r") as f:
        line = f.read().strip()
    user, _, pwd = line.partition(":")
    return user, pwd


def ensure_cert():
    """Generate a self-signed certificate on first run if missing."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    os.makedirs(CONFIG_DIR, exist_ok=True, mode=0o750)
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
        "-subj", "/CN=ydea-db-browser.local",
        "-keyout", KEY_FILE, "-out", CERT_FILE
    ], check=True, capture_output=True)
    os.chmod(KEY_FILE, 0o600)
    os.chmod(CERT_FILE, 0o644)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout clean under systemd; journald captures connections separately if needed

    def _check_auth(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8")
        except Exception:
            return False
        user, _, pwd = decoded.partition(":")
        expected_user, expected_pwd = load_credentials()
        return secrets.compare_digest(user, expected_user) and secrets.compare_digest(pwd, expected_pwd)

    def _require_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Ydea ticket cache"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._check_auth():
            self._require_auth()
            return
        parsed = urlparse(self.path)
        if parsed.path not in ("/", ""):
            self.send_response(404)
            self.end_headers()
            return
        search = parse_qs(parsed.query).get("q", [""])[0]
        body = render_page(search)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ensure_cert()
    load_credentials()  # generates on first run if missing
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"ydea_db_browser listening on https://{BIND_HOST}:{BIND_PORT} (read-only, auth required)")
    server.serve_forever()


main()
