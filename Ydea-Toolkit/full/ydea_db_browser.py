#!/usr/bin/env python3
"""ydea_db_browser - read-only web viewer for the Ydea ticket shadow-write SQLite cache.

Binds to 127.0.0.1 only - reachable exclusively via SSH tunnel or locally on
the host. Opens the database in SQLite's own read-only URI mode, so even a
bug here cannot write to or corrupt the cache the notification scripts use.
Serves HTTPS with a self-signed certificate behind a real login page and
server-side sessions (cookie-based) - not HTTP Basic Auth, so a real logout
is possible (Basic Auth credentials otherwise stay cached by the browser
until it is closed, with no way to clear them from the server side).

All Ydea-side fields (title, status, assignee, link, company, ...) come from
the ticket_details table, kept in sync by ydea_cache_validator.py - this
viewer never calls the Ydea API itself, it only reads the local database.

The only things this script can ever write are its own AUTH_FILE (one
"user:password" line per account, via /account) and in-memory sessions -
never the database.

The login page reuses Checkmk's own #login_window card look (the real
dark modern-dark theme) with the Ydea logo in place of Checkmk's. The
account page is a normal in-app settings page (two left-aligned panels
in the page flow), not a login-style centered card - that treatment
only makes sense full-screen, on its own, which is what the login page
actually is and the account page is not.

Version: 5.7.3"""

import html
import math
import os
import secrets
import sqlite3
import ssl
import subprocess
import time
from datetime import datetime, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = "/opt/ydea-toolkit/cache/ydea_checkmk.db"
BIND_HOST = "127.0.0.1"
BIND_PORT = 8765

CONFIG_DIR = "/opt/ydea-toolkit/config"
AUTH_FILE = f"{CONFIG_DIR}/db_browser_auth"
CERT_FILE = f"{CONFIG_DIR}/db_browser.crt"
KEY_FILE = f"{CONFIG_DIR}/db_browser.key"

COOKIE_NAME = "ydea_session"
SESSION_TTL = 12 * 3600  # hours a login stays valid without re-authenticating

# Checkmk's own brand colors and login-page layout values, pulled from the
# real theme shipped on this same server (not guessed), specifically from
# modern-dark/theme.css - the dark theme Checkmk actually renders by default,
# not the lighter "facelift" one an earlier pass of this file wrongly read:
# /omd/versions/*/share/check_mk/web/htdocs/themes/modern-dark/theme.css
# #login_window { background:#11181d; ... } is the real dark login card,
# input[type=text] { background-color:#303946; color:#fff; } the real
# text fields, and rgb(18.67,185.83,...) (~#13d389) the real button green.
CMK_BG = "#1e262e"
CMK_BG_PANEL = "#242e38"
CMK_ACCENT = "#13d389"
CMK_BORDER = "#2f3b45"
CMK_ERROR = "#c83232"
CMK_TEXT = "#e8e8ee"
CMK_TEXT_DIM = "#8c96a0"
CMK_CARD_BG = "#11181d"
CMK_CARD_TEXT = "#ffffff"
CMK_CARD_INPUT_BG = "#303946"

# Official Ydea logo (457x240 PNG with transparent background, as served by
# the public Ydea web app login page), embedded as base64 so the viewer stays
# a single self-contained file. Shown on the login card and in the page header.
YDEA_LOGO_W = 457
YDEA_LOGO_H = 240
YDEA_LOGO_B64 = (
    "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"
)


def ydea_logo_img(width: int) -> str:
    height = round(width * YDEA_LOGO_H / YDEA_LOGO_W)
    return f'<img src="data:image/png;base64,{YDEA_LOGO_B64}" width="{width}" height="{height}" alt="Ydea">'

# In-memory only: token -> (username, expires_at). A service restart logs
# everyone out, which is an acceptable trade-off for a tool with no database
# of its own to persist sessions into.
SESSIONS = {}


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


def is_today(iso):
    """True when the ISO timestamp falls on the current local day."""
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.date() == datetime.now().astimezone().date()
    except Exception:
        return False


def host_from_ticket(titolo, key):
    """Host column: the host part of a cmk key, or the object named in an alert title."""
    if key:
        return key.split("|", 1)[0]
    text = (titolo or "").strip()
    prefix = "[CRIT - Alert]"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    host = text.split(" - ", 1)[0].strip()
    return host or "-"


def query_tickets(search: str = ""):
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Synced tickets live in their own tables (ydea_sync_tickets.py) and are
        # merged with the alert-driven ones, without duplicates, as soon as the
        # sync has created those tables in the database.
        synced_sql = ""
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='synced_tickets'"
        ).fetchone():
            synced_sql = """
                UNION ALL
                SELECT NULL AS key, s.ticket_id, NULL AS cmk_created_at, NULL AS cmk_last_update,
                       s.codice, s.titolo, s.stato, s.priorita, s.tipo, s.ragione_sociale,
                       s.contratto_codice, s.assegnato_nome, s.link,
                       s.data_creazione, s.data_modifica, s.data_chiusura, s.synced_at
                FROM synced_tickets s
                WHERE s.ticket_id NOT IN (SELECT ticket_id FROM tickets)
            """
        where = "WHERE c.key LIKE ? OR c.ragione_sociale LIKE ? OR c.titolo LIKE ?" if search else ""
        params = (f"%{search}%", f"%{search}%", f"%{search}%") if search else ()
        rows = conn.execute(f"""
            SELECT * FROM (
                SELECT t.key, t.ticket_id, t.created_at AS cmk_created_at, t.last_update AS cmk_last_update,
                       d.codice, d.titolo, d.stato, d.priorita, d.tipo, d.ragione_sociale,
                       d.contratto_codice, d.assegnato_nome, d.link,
                       d.data_creazione, d.data_modifica, d.data_chiusura, d.synced_at
                FROM tickets t
                LEFT JOIN ticket_details d ON d.ticket_id = t.ticket_id
                {synced_sql}
            ) c
            {where}
            ORDER BY COALESCE(c.cmk_last_update, 0) DESC, c.data_modifica DESC
        """, params).fetchall()
    finally:
        conn.close()
    return rows


CMK_SHARED_CSS = f"""
  body {{ font-family: "Inter", system-ui, sans-serif; margin: 0; background: {CMK_BG}; color: {CMK_TEXT}; }}
  .page {{ max-width: 100%; padding: 1.5rem 2rem; }}
  header {{ display: flex; align-items: center; gap: 1.5rem; padding: 0.8rem 2rem; background: {CMK_BG_PANEL}; border-bottom: 2px solid {CMK_ACCENT}; }}
  .brand {{ display: flex; align-items: center; gap: 0.6rem; font-weight: 600; font-size: 1.05rem; }}
  .brand-text {{ color: {CMK_TEXT}; }}
  nav {{ font-size: 0.9rem; margin-left: auto; display: flex; align-items: center; }}
  nav a {{ margin-left: 1.4rem; color: {CMK_TEXT_DIM}; text-decoration: none; font-weight: 500; transition: color 0.15s; padding: 0.25rem 0; }}
  nav a:hover, nav a.active {{ color: {CMK_ACCENT}; }}
  nav a.active {{ font-weight: 600; border-bottom: 2px solid {CMK_ACCENT}; }}
  h1 {{ font-size: 1.2rem; color: {CMK_TEXT}; margin-top: 0; }}
  .meta {{ color: {CMK_TEXT_DIM}; font-size: 0.85rem; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ border: 1px solid {CMK_BORDER}; padding: 0.4rem 0.6rem; text-align: left; white-space: nowrap; }}
  th {{ background: {CMK_BG_PANEL}; color: {CMK_TEXT_DIM}; font-weight: 600; }}
  tr:hover td {{ background: {CMK_BG_PANEL}; }}

  /* Ticket list: the table sizes itself to the content, wraps long titles
     instead of forcing the page wider, and every header sorts on click. */
  .table-wrap {{ overflow-x: auto; }}
  table.tickets {{ table-layout: auto; }}
  table.tickets th, table.tickets td {{ white-space: normal; word-break: break-word; vertical-align: top; }}
  table.tickets .col-title {{ min-width: 18rem; }}
  table.tickets th[data-sort] {{ cursor: pointer; user-select: none; }}
  table.tickets th.sorted-asc::after {{ content: " \\25B2"; }}
  table.tickets th.sorted-desc::after {{ content: " \\25BC"; }}
  table.tickets tr.row-today td {{ background: rgba(19, 211, 137, 0.10); }}
  table.tickets tr.row-today td:first-child {{ box-shadow: inset 3px 0 0 {CMK_ACCENT}; }}
  .badge-today {{ display: inline-block; padding: 0.05rem 0.4rem; margin-right: 0.3rem; font-size: 0.68rem; font-weight: 700; color: #0a1410; background: {CMK_ACCENT}; border-radius: 3px; vertical-align: middle; }}

  /* Statistics page: full-width KPI grid and balanced 2-column charts. */
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }}
  .kpi {{ background: {CMK_BG_PANEL}; border: 1px solid {CMK_BORDER}; border-radius: 6px; padding: 1rem 1.25rem; }}
  .kpi .v {{ font-size: 1.8rem; font-weight: 700; color: {CMK_TEXT}; line-height: 1.1; }}
  .kpi .v.warn {{ color: #f59e0b; }}
  .kpi .l {{ font-size: 0.8rem; color: {CMK_TEXT_DIM}; margin-top: 0.35rem; }}
  .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
  @media (max-width: 1024px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  .chart {{ background: {CMK_BG_PANEL}; border: 1px solid {CMK_BORDER}; border-radius: 6px; padding: 1.2rem 1.5rem; }}
  .chart h2 {{ font-size: 1rem; font-weight: 600; margin: 0 0 0.25rem; color: {CMK_TEXT}; }}
  .chart .subtitle {{ font-size: 0.8rem; color: {CMK_TEXT_DIM}; margin-bottom: 1rem; }}
  .chart .subheading {{ font-size: 0.85rem; font-weight: 600; color: {CMK_TEXT}; margin-bottom: 0.4rem; }}
  a {{ color: {CMK_ACCENT}; }}
  .error {{ color: {CMK_ERROR}; }}
  .ok {{ color: {CMK_ACCENT}; }}

  /* Checkmk's own #login_window card, straight from modern-dark/theme.css:
     background #11181d, border-radius 8px, padding 25px 40px, width 370px -
     reused here for the login card itself and for every form panel on the
     account page (same visual language), with the real input styling
     (background #303946, color #fff, border-radius 4px, no border). */
  .cmk-card {{ background: {CMK_CARD_BG}; color: {CMK_CARD_TEXT}; border-radius: 8px; padding: 25px 40px; box-sizing: border-box; max-width: 370px; margin: 0 auto 1.5rem; }}
  .cmk-card h2, .cmk-card legend {{ font-size: 1rem; margin: 0 0 1rem; color: {CMK_CARD_TEXT}; }}
  .cmk-card label {{ display: block; font-size: 0.85rem; letter-spacing: 1px; margin: 0.8rem 0 0.2rem; color: {CMK_CARD_TEXT}; }}
  .cmk-card input[type=text], .cmk-card input[type=password] {{ width: 100%; padding: 6px 8px; background: {CMK_CARD_INPUT_BG}; color: {CMK_CARD_TEXT}; border: none; border-radius: 4px; box-shadow: none; box-sizing: border-box; }}
  .cmk-card button {{ margin-top: 1.2rem; width: 100%; }}
  .cmk-card .error {{ font-size: 0.85rem; }}
  .cmk-card .ok {{ font-size: 0.85rem; }}

  /* Account & Access management page: dark theme cards and user table */
  .account-grid {{ display: grid; grid-template-columns: 1.1fr 1fr; gap: 1.5rem; align-items: start; }}
  @media (max-width: 960px) {{ .account-grid {{ grid-template-columns: 1fr; }} }}
  .account-card {{ background: {CMK_BG_PANEL}; border: 1px solid {CMK_BORDER}; border-radius: 6px; padding: 1.5rem; }}
  .card-head {{ margin-bottom: 1.2rem; border-bottom: 1px solid {CMK_BORDER}; padding-bottom: 0.8rem; }}
  .card-head h2 {{ font-size: 1.05rem; font-weight: 600; margin: 0 0 0.3rem; color: #ffffff; }}
  .account-table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  .account-table th {{ background: #1a232c; color: {CMK_TEXT_DIM}; padding: 0.6rem 0.8rem; font-weight: 600; border: 1px solid {CMK_BORDER}; text-align: left; }}
  .account-table td {{ padding: 0.75rem 0.8rem; border: 1px solid {CMK_BORDER}; vertical-align: middle; }}
  .account-table tr:hover td {{ background: #1f2730; }}
  .badge {{ display: inline-block; padding: 0.2rem 0.55rem; font-size: 0.75rem; font-weight: 600; border-radius: 12px; }}
  .badge-active {{ background: rgba(19, 211, 137, 0.15); color: {CMK_ACCENT}; border: 1px solid rgba(19, 211, 137, 0.3); }}
  .badge-enabled {{ background: rgba(140, 150, 160, 0.15); color: {CMK_TEXT_DIM}; border: 1px solid {CMK_BORDER}; }}
  .dark-form label {{ display: block; font-size: 0.85rem; font-weight: 500; color: {CMK_TEXT_DIM}; margin: 0.8rem 0 0.35rem; }}
  .dark-form input[type=text], .dark-form input[type=password] {{
    width: 100%; padding: 0.6rem 0.8rem; background: #303946; color: #ffffff; border: 1px solid {CMK_BORDER};
    border-radius: 4px; box-sizing: border-box; font-size: 0.9rem;
  }}
  .dark-form input[type=text]:focus, .dark-form input[type=password]:focus {{
    outline: none; border-color: {CMK_ACCENT}; box-shadow: 0 0 0 2px rgba(19, 211, 137, 0.25);
  }}
  .btn-primary {{ padding: 0.55rem 1.2rem; background: {CMK_ACCENT}; color: #0a1410; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 0.85rem; }}
  .btn-primary:hover {{ opacity: 0.9; }}
  .btn-danger {{ padding: 0.3rem 0.65rem; background: transparent; color: {CMK_ERROR}; border: 1px solid {CMK_ERROR}; border-radius: 3px; font-size: 0.75rem; font-weight: 600; cursor: pointer; }}
  .btn-danger:hover {{ background: {CMK_ERROR}; color: #ffffff; }}
  .alert-box {{ padding: 0.8rem 1.2rem; border-radius: 4px; margin-bottom: 1.5rem; font-size: 0.9rem; }}
  .alert-box.ok {{ background: rgba(19, 211, 137, 0.15); border: 1px solid {CMK_ACCENT}; color: {CMK_ACCENT}; }}
  .alert-box.error {{ background: rgba(255, 85, 85, 0.15); border: 1px solid {CMK_ERROR}; color: {CMK_ERROR}; }}

  button {{ padding: 0.5rem 1rem; background: {CMK_ACCENT}; color: #0a1410; border: none; border-radius: 3px; font-weight: 600; cursor: pointer; }}
  button:hover {{ opacity: 0.85; }}
"""


def page_shell(title: str, body: str, current_user: str = "", active_tab: str = "") -> bytes:
    brand = f'{ydea_logo_img(56)}<span class="brand-text">Ydea Ticket DB</span>'
    nav_links = ""
    if current_user:
        def item(path, label, key):
            cls = ' class="active"' if active_tab == key else ""
            return f'<a href="{path}"{cls}>{label}</a>'
        nav_links = (
            item("/", "Ticket", "tickets")
            + item("/stats", "Statistiche", "stats")
            + item("/account", "Account", "account")
            + '<a href="/logout">Esci</a>'
        )
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>{CMK_SHARED_CSS}
  form {{ margin-bottom: 1rem; }}
  input[type=text], input[type=password] {{ padding: 0.4rem; width: 20rem; background: {CMK_BG}; color: {CMK_TEXT}; border: 1px solid {CMK_BORDER}; border-radius: 3px; }}
</style>
</head>
<body>
<header>
  <div class="brand">{brand}</div>
  <nav>{nav_links}</nav>
</header>
<div class="page">
{body}
</div>
</body>
</html>""".encode("utf-8")


def render_login_page(message: str = "") -> bytes:
    msg_html = f'<p class="error">{html.escape(message)}</p>' if message else ""
    # Mirrors Checkmk's own login.py structure: #login (full-screen, centered)
    # > #login_window (the card) > logo, then the form, same as every real
    # Checkmk login page - not just the colors.
    return f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Login - Ydea Ticket DB</title>
<style>{CMK_SHARED_CSS}
  body.login {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
  #login_window {{ margin: 0; }}
  .login_window_logo_link {{ display: block; width: 160px; margin: 0 auto 1.2rem; }}
  .login_window_logo_link img {{ display: block; }}
  #login_window form {{ margin: 0; }}
  #login_window table {{ width: 100%; font-size: 0.85rem; margin-bottom: 0.5rem; }}
  #login_window td {{ border: none; padding: 0.35rem 0; white-space: normal; }}
  #login_window tr:hover td {{ background: none; }}
  #login_window td.login_label {{ width: 1%; white-space: nowrap; padding-right: 1rem; letter-spacing: 1px; }}
  td.login_label label {{ margin: 0; }}
  #login_window #button_text {{ text-align: center; }}
  #login_window #button_text button {{ width: auto; min-width: 8rem; }}
  #foot {{ margin-top: 1.5rem; color: rgba(255, 255, 255, 0.5); font-size: 0.75rem; text-align: center; }}
</style>
</head>
<body class="login">
<div id="login_window" class="cmk-card">
  <a class="login_window_logo_link" href="/">{ydea_logo_img(160)}</a>
  {msg_html}
  <form method="post" action="/login">
    <table>
      <tr>
        <td class="login_label"><label for="input_user">Utente:</label></td>
        <td class="login_input"><input type="text" name="username" id="input_user" required autofocus autocomplete="username"></td>
      </tr>
      <tr>
        <td class="login_label"><label for="input_pass">Password:</label></td>
        <td class="login_input"><input type="password" name="password" id="input_pass" required autocomplete="current-password"></td>
      </tr>
    </table>
    <div id="button_text"><button type="submit" class="hot">Accedi</button></div>
    <div id="foot">Ydea Ticket DB</div>
  </form>
</div>
</body>
</html>""".encode("utf-8")


def render_tickets_page(search: str, current_user: str) -> bytes:
    try:
        rows = query_tickets(search)
        error = None
    except Exception as e:
        rows, error = [], str(e)

    body_rows = []
    for r in rows:
        link = r["link"] or f"https://my.ydea.cloud/ticket/{r['ticket_id']}"
        synced_note = fmt_ts(r["synced_at"]) if r["synced_at"] else "mai sincronizzato"
        host = host_from_ticket(r["titolo"], r["key"])
        code = r["codice"] or f"#{r['ticket_id']}"
        today = is_today(r["data_creazione"]) or is_today(r["data_modifica"])
        row_cls = ' class="row-today"' if today else ""
        badge = '<span class="badge-today">OGGI</span> ' if today else ""
        body_rows.append(f"""
        <tr{row_cls}>
            <td data-v="{html.escape(host)}">{badge}{html.escape(host)}</td>
            <td data-v="{html.escape(code)}"><a href="{html.escape(link)}" target="_blank" rel="noopener">{html.escape(code)}</a></td>
            <td data-v="{html.escape(r["titolo"] or "")}" class="col-title">{html.escape(r["titolo"] or "-")}</td>
            <td data-v="{html.escape(r["stato"] or "")}">{html.escape(r["stato"] or "-")}</td>
            <td data-v="{html.escape(r["priorita"] or "")}">{html.escape(r["priorita"] or "-")}</td>
            <td data-v="{html.escape(r["tipo"] or "")}">{html.escape(r["tipo"] or "-")}</td>
            <td data-v="{html.escape(r["assegnato_nome"] or "")}">{html.escape(r["assegnato_nome"] or "-")}</td>
            <td data-v="{html.escape(r["ragione_sociale"] or "")}">{html.escape(r["ragione_sociale"] or "-")}</td>
            <td data-v="{html.escape(r["contratto_codice"] or "")}">{html.escape(r["contratto_codice"] or "-")}</td>
            <td data-v="{html.escape(r["data_creazione"] or "")}">{fmt_iso(r["data_creazione"])}</td>
            <td data-v="{html.escape(r["data_modifica"] or "")}">{fmt_iso(r["data_modifica"])}</td>
            <td data-v="{r['synced_at'] or 0}" title="ultimo sync del ticket">{synced_note}</td>
        </tr>""")

    error_html = f'<p class="error">Errore: {html.escape(error)}</p>' if error else ""

    body = f"""
<h1>Search</h1>
<form method="get">
  <input type="text" name="q" placeholder="filtra per host, azienda o titolo..." value="{html.escape(search)}">
  <button type="submit">Cerca</button>
</form>
{error_html}
<div class="table-wrap">
<table class="tickets">
<thead>
<tr>
  <th data-sort>Host</th><th data-sort>Ticket</th><th data-sort>Titolo</th><th data-sort>Stato</th><th data-sort>Priorita</th><th data-sort>Tipo</th>
  <th data-sort>Assegnatario</th><th data-sort>Azienda</th><th data-sort>Contratto</th>
  <th data-sort>Creato (Ydea)</th><th data-sort>Modificato (Ydea)</th><th data-sort>Sync</th>
</tr>
</thead>
<tbody>
{"".join(body_rows) if body_rows else "<tr><td colspan='12'>Nessun ticket in cache.</td></tr>"}
</tbody>
</table>
</div>
<script>
(function () {{
  var table = document.querySelector("table.tickets");
  if (!table || !table.tBodies.length) return;
  var tbody = table.tBodies[0];
  var headers = table.querySelectorAll("th[data-sort]");
  headers.forEach(function (th) {{
    th.addEventListener("click", function () {{
      var dir = th.dataset.dir === "asc" ? "desc" : "asc";
      headers.forEach(function (h) {{ h.dataset.dir = ""; h.classList.remove("sorted-asc", "sorted-desc"); }});
      th.dataset.dir = dir;
      th.classList.add(dir === "asc" ? "sorted-asc" : "sorted-desc");
      var idx = th.cellIndex;
      Array.from(tbody.rows).sort(function (a, b) {{
        var av = a.cells[idx].dataset.v || a.cells[idx].textContent.trim();
        var bv = b.cells[idx].dataset.v || b.cells[idx].textContent.trim();
        var numeric = /^-?\\d+(?:\\.\\d+)?$/.test(av) && /^-?\\d+(?:\\.\\d+)?$/.test(bv);
        var cmp;
        if (numeric) cmp = parseFloat(av) - parseFloat(bv);
        else cmp = av.localeCompare(bv, "it", {{ numeric: true, sensitivity: "base" }});
        return dir === "asc" ? cmp : -cmp;
      }}).forEach(function (row) {{ tbody.appendChild(row); }});
    }});
  }});
}})();
</script>"""
    return page_shell("Ydea Ticket DB", body, current_user, active_tab="tickets")


## Statistics

def problem_category(service: str) -> str:
    """Group Checkmk services into operational problem families."""
    s = (service or "").lower()
    if "memory" in s or "ram" in s:
        return "Memoria / RAM"
    if "filesystem" in s or "disk" in s:
        return "Disco / Filesystem"
    if "dns" in s or "net" in s or "ping" in s or "conn" in s:
        return "Rete & Connettivita"
    return "Container & Servizi"


def query_stats():
    """Aggregates over the synced alert tickets; None when the sync never ran."""
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='synced_tickets'"
        ).fetchone():
            return None
        months = conn.execute(
            "SELECT substr(data_creazione, 1, 7) AS k, COUNT(*) AS n FROM synced_tickets "
            "WHERE data_creazione IS NOT NULL AND data_creazione <> '' GROUP BY k ORDER BY k"
        ).fetchall()
        states = conn.execute(
            "SELECT COALESCE(NULLIF(stato, ''), '-') AS k, COUNT(*) AS n "
            "FROM synced_tickets GROUP BY k ORDER BY n DESC"
        ).fetchall()
        types = conn.execute(
            "SELECT COALESCE(NULLIF(tipo, ''), '-') AS k, COUNT(*) AS n "
            "FROM synced_tickets GROUP BY k ORDER BY n DESC LIMIT 8"
        ).fetchall()
        operators = conn.execute(
            "SELECT COALESCE(NULLIF(assegnato_nome, ''), 'Non assegnato') AS k, COUNT(*) AS n "
            "FROM synced_tickets GROUP BY k ORDER BY n DESC LIMIT 5"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM synced_tickets").fetchone()[0]
        titles = [row[0] for row in conn.execute("SELECT titolo FROM synced_tickets")]
    finally:
        conn.close()

    host_counts = {}
    service_counts = {}
    problem_counts = {}
    for title in titles:
        h = host_from_ticket(title, None)
        host_counts[h] = host_counts.get(h, 0) + 1
        t = (title or "").strip()
        if t.startswith("[CRIT - Alert]"):
            t = t[len("[CRIT - Alert]"):].strip()
        srv = t.split(" - ", 1)[1].strip() if " - " in t else "Altro"
        service_counts[srv] = service_counts.get(srv, 0) + 1
        cat = problem_category(srv)
        problem_counts[cat] = problem_counts.get(cat, 0) + 1

    top_hosts = sorted(host_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
    top_services = sorted(service_counts.items(), key=lambda item: (-item[1], item[0]))[:8]

    problem_order = ["Memoria / RAM", "Disco / Filesystem", "Rete & Connettivita", "Container & Servizi"]
    problem_families = [(k, problem_counts[k]) for k in problem_order if k in problem_counts]
    for k, v in problem_counts.items():
        if k not in problem_order:
            problem_families.append((k, v))

    in_attesa = sum(n for k, n in states if k.lower().startswith("in attesa"))
    effettuati = sum(n for k, n in states if k.lower() == "effettuato")
    chiusi = sum(n for k, n in states if k.lower() == "chiuso")
    ram_count = service_counts.get("Memory", 0) + service_counts.get("DotNet Memory Management _Global_", 0)
    disk_count = sum(n for s, n in service_counts.items() if "filesystem" in s.lower() or "disk" in s.lower())

    return {
        "total": total,
        "in_attesa": in_attesa,
        "completati": effettuati + chiusi,
        "ram_count": ram_count,
        "disk_count": disk_count,
        "months": [(row["k"], row["n"]) for row in months],
        "services": top_services,
        "hosts": top_hosts,
        "states": [(row["k"], row["n"]) for row in states],
        "types": [(row["k"], row["n"]) for row in types],
        "operators": [(row["k"], row["n"]) for row in operators],
        "problem_families": problem_families,
    }


def svg_donut(rows, colors=None):
    """Donut chart as inline SVG with side legend, no external lib."""
    if not rows:
        return '<p class="meta">Nessun dato.</p>'
    if colors is None:
        colors = ["#13d389", "#38bdf8", "#f59e0b", "#a855f7", "#ec4899", "#64748b"]
    total = sum(n for _, n in rows) or 1
    size = 180
    cx, cy, r, stroke_w = 90, 90, 62, 26
    c = 2 * math.pi * r
    parts = [
        '<div style="display:flex; align-items:center; justify-content:space-around; gap:1.5rem; flex-wrap:wrap; padding:0.4rem 0;">',
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="transform: rotate(-90deg); flex-shrink:0;">',
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1a232c" stroke-width="{stroke_w}"/>'
    ]
    accum = 0.0
    for idx, (label, count) in enumerate(rows):
        if count <= 0:
            continue
        color = colors[idx % len(colors)]
        length = (count / total) * c
        dash = max(1.0, length - (2.0 if len(rows) > 1 else 0))
        gap = c - dash
        offset = -accum
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke_w}" '
            f'stroke-dasharray="{dash:.2f} {gap:.2f}" stroke-dashoffset="{offset:.2f}"/>'
        )
        accum += length
    parts.append(
        '</svg>'
        '<div class="donut-legend" style="display:flex; flex-direction:column; gap:0.6rem; min-width:14rem; flex:1;">'
    )
    for idx, (label, count) in enumerate(rows):
        color = colors[idx % len(colors)]
        pct = round(100 * count / total)
        parts.append(
            f'<div style="display:flex; align-items:center; justify-content:space-between; font-size:0.85rem;">'
            f'<span style="display:flex; align-items:center; gap:0.55rem;">'
            f'<span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:{color}; flex-shrink:0;"></span>'
            f'<span style="color:{CMK_TEXT};">{html.escape(label)}</span>'
            f'</span>'
            f'<span style="font-weight:600; color:{CMK_TEXT_DIM};">{count} <span style="font-size:0.75rem; font-weight:normal;">({pct}%)</span></span>'
            f'</div>'
        )
    parts.append('</div></div>')
    return "".join(parts)


def svg_hbars(rows, show_pct=True):
    """Horizontal bar chart as inline SVG, right-aligned labels, no external lib."""
    if not rows:
        return '<p class="meta">Nessun dato.</p>'
    total = sum(n for _, n in rows) or 1
    max_n = max(n for _, n in rows) or 1
    label_w, bar_max, row_h = 175, 250, 26
    height = len(rows) * row_h + 8
    parts = [f'<svg viewBox="0 0 {label_w + bar_max + 80} {height}" width="100%" height="{height}" style="display:block;">']
    for index, (label, count) in enumerate(rows):
        y = index * row_h + 4
        width = max(3, round(bar_max * count / max_n))
        pct = f'<tspan fill="{CMK_TEXT_DIM}" font-size="10"> ({round(100 * count / total)}%)</tspan>' if show_pct and total > 0 else ""
        parts.append(
            f'<text x="{label_w - 12}" y="{y + 13}" font-size="12" text-anchor="end" fill="{CMK_TEXT_DIM}">'
            f'{html.escape(label[:24])}</text>'
        )
        parts.append(f'<rect x="{label_w}" y="{y}" width="{width}" height="17" rx="3" fill="{CMK_ACCENT}"/>')
        parts.append(
            f'<text x="{label_w + width + 8}" y="{y + 13}" font-size="12" font-weight="500" fill="{CMK_TEXT}">'
            f'{count}{pct}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_columns(rows):
    """Vertical bar chart for monthly series, centered with clean baseline."""
    if not rows:
        return '<p class="meta">Nessun dato.</p>'
    max_n = max(n for _, n in rows) or 1
    chart_w, chart_h, baseline_y = 500, 140, 165
    col_w = 38
    n_cols = len(rows)
    gap = min(36, max(12, round((chart_w - 80 - n_cols * col_w) / max(1, n_cols - 1))))
    total_w = n_cols * col_w + (n_cols - 1) * gap
    start_x = round((chart_w - total_w) / 2)
    parts = [
        f'<svg viewBox="0 0 {chart_w} {baseline_y + 35}" width="100%" height="{baseline_y + 35}" style="display:block;">',
        f'<line x1="30" y1="{baseline_y}" x2="{chart_w - 30}" y2="{baseline_y}" stroke="{CMK_BORDER}" stroke-width="1"/>'
    ]
    for index, (label, count) in enumerate(rows):
        height = max(4, round(chart_h * count / max_n))
        x = start_x + index * (col_w + gap)
        y = baseline_y - height
        caption = f"{label[5:7]}/{label[2:4]}" if len(label) == 7 else label
        parts.append(f'<rect x="{x}" y="{y}" width="{col_w}" height="{height}" rx="3" fill="{CMK_ACCENT}"/>')
        parts.append(
            f'<text x="{x + col_w / 2}" y="{y - 6}" font-size="12" font-weight="600" text-anchor="middle" '
            f'fill="{CMK_TEXT}">{count}</text>'
        )
        parts.append(
            f'<text x="{x + col_w / 2}" y="{baseline_y + 18}" font-size="11" text-anchor="middle" '
            f'fill="{CMK_TEXT_DIM}">{html.escape(caption)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_stats_page(current_user: str) -> bytes:
    try:
        stats = query_stats()
        error = None
    except Exception as e:
        stats, error = None, str(e)

    if error:
        body = f'<p class="error">Errore: {html.escape(error)}</p>'
    elif not stats:
        body = '<p class="meta">Nessun ticket sincronizzato. Esegui ydea_sync_tickets.py --full.</p>'
    else:
        body = f"""
<h1>Statistiche</h1>
<div class="kpis">
  <div class="kpi"><div class="v">{stats['total']}</div><div class="l">Alert critici totali</div></div>
  <div class="kpi"><div class="v warn">{stats['in_attesa']}</div><div class="l">In attesa (attivo)</div></div>
  <div class="kpi"><div class="v">{stats['completati']}</div><div class="l">Completati o chiusi (98%)</div></div>
  <div class="kpi"><div class="v">{stats['ram_count']}</div><div class="l">Problemi RAM / Memoria</div></div>
  <div class="kpi"><div class="v">{stats['disk_count']}</div><div class="l">Problemi Filesystem / Disco</div></div>
</div>
<div class="charts">
  <div class="chart">
    <h2>Tipologie di problema</h2>
    <div class="subtitle">Ripartizione macro-aree dei 61 alert critici</div>
    {svg_donut(stats['problem_families'])}
  </div>
  <div class="chart">
    <h2>Andamento mensile alert</h2>
    <div class="subtitle">Aperture per mese di creazione</div>
    {svg_columns(stats['months'])}
  </div>
  <div class="chart">
    <h2>Controlli e servizi piu allarmati</h2>
    <div class="subtitle">Causa Checkmk dell'alert critico</div>
    {svg_hbars(stats['services'])}
  </div>
  <div class="chart">
    <h2>Host con piu allarmi (Top 10)</h2>
    <div class="subtitle">Apparati con il maggior numero di criticita</div>
    {svg_hbars(stats['hosts'], show_pct=False)}
  </div>
  <div class="chart">
    <h2>Classe e tipologia apparati</h2>
    <div class="subtitle">Ripartizione ambiente secondo classificazione Ydea</div>
    {svg_donut(stats['types'], colors=['#38bdf8', '#13d389', '#f59e0b', '#ec4899'])}
  </div>
  <div class="chart">
    <h2>Operatori e stato di avanzamento</h2>
    <div class="subheading">Operatori assegnatari (Top 5)</div>
    {svg_hbars(stats['operators'])}
    <div class="subheading" style="margin-top: 1.1rem;">Stato di avanzamento</div>
    {svg_hbars(stats['states'])}
  </div>
</div>"""
    return page_shell("Statistiche - Ydea Ticket DB", body, current_user, active_tab="stats")


def render_account_page(current_user: str, message: str = "", is_error: bool = False) -> bytes:
    users = list(load_all_credentials().keys())
    msg_html = f'<div class="alert-box {"error" if is_error else "ok"}">{html.escape(message)}</div>' if message else ""

    rows = []
    for u in users:
        is_me = (u == current_user)
        badge = '<span class="badge badge-active">Sessione corrente</span>' if is_me else '<span class="badge badge-enabled">Abilitato</span>'
        action_btn = f'<span style="color:{CMK_TEXT_DIM}; font-size:0.8rem;">(account in uso)</span>'
        if not is_me:
            action_btn = f'''<form method="post" action="/account" style="display:inline; margin:0;" onsubmit="return confirm('Eliminare l\\\'utente {html.escape(u)}?');">
                <input type="hidden" name="action" value="delete_user">
                <input type="hidden" name="target_username" value="{html.escape(u)}">
                <button type="submit" class="btn-danger">Elimina</button>
            </form>'''
        rows.append(f"""
        <tr>
          <td><b style="color:#ffffff;">{html.escape(u)}</b></td>
          <td>{badge}</td>
          <td style="text-align:right;">{action_btn}</td>
        </tr>""")

    body = f"""
<h1>Gestione Account & Accessi</h1>
<div style="color:{CMK_TEXT_DIM}; margin-bottom:1.5rem; font-size:0.9rem;">
  Amministrazione delle credenziali di accesso alla console locale Ydea Ticket DB.
</div>
{msg_html}

<div class="account-grid">
  <!-- Colonna 1: Elenco utenti abilitati -->
  <div class="account-card">
    <div class="card-head">
      <h2>Utenti abilitati ({len(users)})</h2>
      <span style="font-size:0.8rem; color:{CMK_TEXT_DIM};">Account che possono accedere al visualizzatore</span>
    </div>
    <table class="account-table">
      <thead>
        <tr>
          <th>Nome utente</th>
          <th>Stato</th>
          <th style="text-align:right;">Azione</th>
        </tr>
      </thead>
      <tbody>
        {"".join(rows)}
      </tbody>
    </table>
  </div>

  <!-- Colonna 2: Form di modifica e creazione -->
  <div style="display:flex; flex-direction:column; gap:1.5rem;">
    <!-- Card Cambia Password -->
    <div class="account-card">
      <div class="card-head">
        <h2>Cambia la tua password</h2>
        <span style="font-size:0.8rem; color:{CMK_TEXT_DIM};">Aggiorna la password per <b>{html.escape(current_user)}</b></span>
      </div>
      <form method="post" action="/account" class="dark-form">
        <input type="hidden" name="action" value="change_password">
        <label for="new_password">Nuova password</label>
        <input type="password" name="new_password" id="new_password" placeholder="Almeno 8 caratteri" required minlength="8">
        <label for="confirm_password">Conferma nuova password</label>
        <input type="password" name="confirm_password" id="confirm_password" placeholder="Ripeti la password" required minlength="8">
        <div style="margin-top:1.2rem;">
          <button type="submit" class="btn-primary">Aggiorna password</button>
        </div>
      </form>
    </div>

    <!-- Card Aggiungi Utente -->
    <div class="account-card">
      <div class="card-head">
        <h2>Crea nuovo utente</h2>
        <span style="font-size:0.8rem; color:{CMK_TEXT_DIM};">Aggiungi un account per un nuovo operatore</span>
      </div>
      <form method="post" action="/account" class="dark-form">
        <input type="hidden" name="action" value="add_user">
        <label for="new_username">Nome utente</label>
        <input type="text" name="new_username" id="new_username" placeholder="es. mrossi" required autocomplete="off">
        <label for="new_user_password">Password iniziale</label>
        <input type="password" name="new_user_password" id="new_user_password" placeholder="Almeno 8 caratteri" required minlength="8">
        <div style="margin-top:1.2rem;">
          <button type="submit" class="btn-primary">Crea account</button>
        </div>
      </form>
    </div>
  </div>
</div>"""
    return page_shell("Account - Ydea Ticket DB", body, current_user, active_tab="account")


def load_all_credentials() -> dict:
    """Read every 'username:password' line from AUTH_FILE. Generates a
    first admin user on first run if the file is missing, so a fresh
    deploy never starts without auth."""
    if not os.path.exists(AUTH_FILE):
        os.makedirs(CONFIG_DIR, exist_ok=True, mode=0o750)
        username = "ydea-viewer"
        password = secrets.token_urlsafe(18)
        with open(AUTH_FILE, "w") as f:
            f.write(f"{username}:{password}\n")
        os.chmod(AUTH_FILE, 0o600)
        print(f"Generated credentials in {AUTH_FILE}: {username}:{password}")
    creds = {}
    with open(AUTH_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            user, _, pwd = line.partition(":")
            creds[user] = pwd
    return creds


def save_all_credentials(creds: dict):
    with open(AUTH_FILE, "w") as f:
        for user, pwd in creds.items():
            f.write(f"{user}:{pwd}\n")
    os.chmod(AUTH_FILE, 0o600)


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


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = (username, time.time() + SESSION_TTL)
    return token


def resolve_session(token: str):
    entry = SESSIONS.get(token)
    if not entry:
        return None
    username, expires_at = entry
    if time.time() > expires_at:
        SESSIONS.pop(token, None)
        return None
    return username


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout clean under systemd; journald captures connections separately if needed

    def _current_user(self):
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        jar = cookies.SimpleCookie()
        jar.load(raw_cookie)
        morsel = jar.get(COOKIE_NAME)
        if not morsel:
            return None
        return resolve_session(morsel.value)

    def _set_session_cookie(self, token: str):
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}={token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={SESSION_TTL}"
        )

    def _clear_session_cookie(self):
        self.send_header("Set-Cookie", f"{COOKIE_NAME}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0")

    def _redirect(self, location: str, clear_cookie: bool = False):
        self.send_response(302)
        self.send_header("Location", location)
        if clear_cookie:
            self._clear_session_cookie()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_html(self, body: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_form(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return parse_qs(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        current_user = self._current_user()

        if parsed.path == "/login":
            if current_user:
                self._redirect("/")
                return
            self._send_html(render_login_page())
            return

        if parsed.path == "/logout":
            self._redirect("/login", clear_cookie=True)
            return

        if not current_user:
            self._redirect("/login")
            return

        if parsed.path in ("/", ""):
            search = parse_qs(parsed.query).get("q", [""])[0]
            self._send_html(render_tickets_page(search, current_user))
        elif parsed.path == "/stats":
            self._send_html(render_stats_page(current_user))
        elif parsed.path == "/account":
            self._send_html(render_account_page(current_user))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/login":
            fields = self._read_form()
            username = fields.get("username", [""])[0]
            password = fields.get("password", [""])[0]
            creds = load_all_credentials()
            expected = creds.get(username)
            if expected is not None and secrets.compare_digest(password, expected):
                token = create_session(username)
                self.send_response(302)
                self.send_header("Location", "/")
                self._set_session_cookie(token)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_html(render_login_page("Utente o password non validi."), status=401)
            return

        current_user = self._current_user()
        if not current_user:
            self._redirect("/login")
            return

        if parsed.path != "/account":
            self.send_response(404)
            self.end_headers()
            return

        fields = self._read_form()
        action = fields.get("action", [""])[0]
        creds = load_all_credentials()
        message, is_error = "", False

        if action == "change_password":
            new_pwd = fields.get("new_password", [""])[0]
            confirm_pwd = fields.get("confirm_password", [""])[0]
            if len(new_pwd) < 8:
                message, is_error = "La password deve avere almeno 8 caratteri.", True
            elif new_pwd != confirm_pwd:
                message, is_error = "Le due password non coincidono.", True
            else:
                creds[current_user] = new_pwd
                save_all_credentials(creds)
                message = "Password aggiornata."

        elif action == "add_user":
            new_user = fields.get("new_username", [""])[0].strip()
            new_pwd = fields.get("new_user_password", [""])[0]
            if not new_user:
                message, is_error = "Nome utente mancante.", True
            elif new_user in creds:
                message, is_error = f"L'utente '{new_user}' esiste gia'.", True
            elif len(new_pwd) < 8:
                message, is_error = "La password deve avere almeno 8 caratteri.", True
            else:
                creds[new_user] = new_pwd
                save_all_credentials(creds)
                message = f"Utente '{new_user}' creato."

        elif action == "delete_user":
            del_user = fields.get("target_username", [""])[0].strip()
            if not del_user:
                message, is_error = "Nome utente mancante.", True
            elif del_user == current_user:
                message, is_error = "Non puoi eliminare il tuo stesso account.", True
            elif del_user not in creds:
                message, is_error = f"L'utente '{del_user}' non esiste.", True
            elif len(creds) <= 1:
                message, is_error = "Impossibile eliminare l'unico utente rimasto.", True
            else:
                creds.pop(del_user, None)
                save_all_credentials(creds)
                message = f"Utente '{del_user}' eliminato."

        else:
            message, is_error = "Azione sconosciuta.", True

        self._send_html(render_account_page(current_user, message, is_error))


def main():
    ensure_cert()
    load_all_credentials()  # generates the first user on first run if missing
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"ydea_db_browser listening on https://{BIND_HOST}:{BIND_PORT} (read-only, login required)")
    server.serve_forever()


main()
