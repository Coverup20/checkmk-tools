#!/usr/bin/env python3
"""ydea_db_browser - read-only web viewer for the Ydea ticket shadow-write SQLite cache.

Binds to 127.0.0.1 only - reachable exclusively via SSH tunnel or locally on
the host. Opens the database in SQLite's own read-only URI mode, so even a
bug here cannot write to or corrupt the cache the notification scripts use.

Version: 1.0.0"""

import html
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = "/opt/ydea-toolkit/cache/ydea_checkmk.db"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765


def fmt_ts(ts):
    if ts is None:
        return "-"
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def query_tickets(search: str = ""):
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        if search:
            rows = conn.execute(
                "SELECT key, ticket_id, state, created_at, last_update, resolved_at "
                "FROM tickets WHERE key LIKE ? ORDER BY last_update DESC",
                (f"%{search}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key, ticket_id, state, created_at, last_update, resolved_at "
                "FROM tickets ORDER BY last_update DESC"
            ).fetchall()
        flap_counts = dict(conn.execute(
            "SELECT key, COUNT(*) FROM flapping_events GROUP BY key"
        ).fetchall())
    finally:
        conn.close()
    return rows, flap_counts


def render_page(search: str = "") -> bytes:
    try:
        rows, flap_counts = query_tickets(search)
        error = None
    except Exception as e:
        rows, flap_counts, error = [], {}, str(e)

    body_rows = []
    for key, ticket_id, state, created_at, last_update, resolved_at in rows:
        status_class = "resolved" if resolved_at else "active"
        body_rows.append(f"""
        <tr class="{status_class}">
            <td>{html.escape(key)}</td>
            <td>#{ticket_id}</td>
            <td>{html.escape(state or '')}</td>
            <td>{fmt_ts(created_at)}</td>
            <td>{fmt_ts(last_update)}</td>
            <td>{fmt_ts(resolved_at)}</td>
            <td>{flap_counts.get(key, 0)}</td>
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
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #333; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }}
  th {{ background: #1b1b1b; }}
  tr.resolved {{ color: #777; }}
  tr.active {{ color: #ddd; }}
  .error {{ color: #e55; }}
</style>
</head>
<body>
<h1>Ydea ticket cache - shadow SQLite (sola lettura)</h1>
<div class="meta">DB: {html.escape(DB_PATH)} - JSON resta la fonte autorevole, questa pagina non scrive mai nulla.</div>
<form method="get">
  <input type="text" name="q" placeholder="filtra per host..." value="{html.escape(search)}">
  <button type="submit">Cerca</button>
</form>
{error_html}
<table>
<tr><th>Host/key</th><th>Ticket</th><th>Stato</th><th>Creato</th><th>Ultimo update</th><th>Risolto</th><th>Flapping events</th></tr>
{"".join(body_rows) if body_rows else "<tr><td colspan='7'>Nessun ticket in cache.</td></tr>"}
</table>
</body>
</html>""".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout clean under systemd; journald captures connections separately if needed

    def do_GET(self):
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
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    print(f"ydea_db_browser listening on {BIND_HOST}:{BIND_PORT} (read-only)")
    server.serve_forever()


main()
