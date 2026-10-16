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

Version: 5.4.2"""

import html
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

# Light form-card palette for the in-app account page, taken from the compiled
# CSS bundle of a NethSecurity 8 instance (most frequent real values):
# white card, #101828 text, #6a7282 labels, #aaaeb7 input borders.
NS_CARD_BG = "#ffffff"
NS_CARD_BORDER = "#e3e5e8"
NS_TEXT = "#101828"
NS_LABEL = "#6a7282"
NS_INPUT_BORDER = "#aaaeb7"

# Official Ydea logo (457x240 PNG with transparent background, as served by
# the public Ydea web app login page), embedded as base64 so the viewer stays
# a single self-contained file. Shown on the login card and in the page header.
YDEA_LOGO_W = 457
YDEA_LOGO_H = 240
YDEA_LOGO_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAckAAADwCAMAAABc42+SAAAAAXNSR0IB2cksfwAAAAlwSFlzAABCcAAAQnABbvJfbQAAAwBQTFRF"
    "AAAAAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/jAJ/j"
    "AJ/jAJ/jAJ/jAJ/jAJ/jAJ/jHRSVwAAAAQB0Uk5TAAQnb7TP4+rlyYkoQ8H4//JrACWrhAHW/Tw5vkDw9SBFRksrN+k15MRPLFSP"
    "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"
    "dlQgoo2H26D84XJcfR24D1mqsz/kf5lS+yCiAgePkB/o7i19+0aY9LZGnFJYAkadSddx5JV3Yr+mCJPeo0zYqHaaC6jsUC8MURyJ"
    "H/q/WDHDPbgol2ui7Evp6Sn7LerAFP08SVjmEtkp77hbeCh/BMDfsRfcxb9sVwt5Jgzj2AtoyLx3SDvPvTeY2Ns0lEyZY8g/ZMN4"
    "S54RovPOd16MiWIim/ROv5ErMGsYYqfvXVV7y3qyO1woEZ3x+kh4NO/6jT1jsNfLRM7k/yp89pxsXPDR9WzMigvn5CujrFiUm3s3"
    "sSgoFAqFQqFQKBQKhUKhUCgUCoVCoZRLtl+vO3r06H3CzI6b1XzjZr6/desYWfKTh34ayf81rE/GZTblmH3SySE8e30H11jzUWtx"
    "TF3Td9auiGyXd/371+aeDYB8HNOfgRHD8wCYy3ZYfYPs8wWBsVkDdshiLlhzbxWKkK2IVTg+HsjFAdSOdlmBWZP+7SYXYUSm8Avg"
    "cCs7SKDL7xnO9q1skf+0OdBXe27zBhB3F/94VWmy3xF/V/OxUQDEXfd/GskupRW9lhVZq2cuDP1KGk4Su5xKyiXRagFXiwb7BuOo"
    "NCkQ/RYAj4mTX6vP5NKLLrhnNrFuRmQJbsiZZpOufOlgquwTAHiqtw3+Silk2FHmw7FjBw0wyZ6gL25FCopxsAWNn+hrkMlrwV4l"
    "RRlLTCJm2FGMhposL7AFXatIytSFfKxBJo+frCemWXmeJm4Tseh3+q38KqkGmZRRXM1FMZhw5DqoIIMXZJZJ8ze7r3iErNogXT8j"
    "tNh0kxH0O2k80cnS5coKDxltcqN0/9dleS6KBYw22iStu9qEgsnh1GRZgWyyTigAL/N/UpPOJqkWyWSTO9gXRP5vatLRJP2NKftb"
    "n+f+djPSxHNbY9nOxgxf1wY16STeWRUl6qlI7cK+Jfi2DegGQGhDWGUsO5d92lXfJ7Um6QABC0jt5PH0KakaGDFwmN3TwV3V15p2"
    "mPmQs+dyoBWvhJ3a32e8/2C1JptfljYHLi/Hi3DYxNfF8vd2z/3+juH1n8tj+wj7tKkxWRPZxuOhE/6NZsUlmUrPPKF9u/YOaWz7"
    "cOFgdmzd8+L8mGfzPaKAvLpIld+6KAbj3XZfU6Gh7vGMjEeOwgux7J/3X1FLXnN458RBu0NbSRb7GBl22xVxSOm4HbL2wNDWkmXS"
    "LOP/Ab+0pvZAyvdyAAAAAElFTkSuQmCC"
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


CMK_SHARED_CSS = f"""
  body {{ font-family: "Inter", system-ui, sans-serif; margin: 0; background: {CMK_BG}; color: {CMK_TEXT}; }}
  .page {{ max-width: 100%; padding: 1.5rem 2rem; }}
  header {{ display: flex; align-items: center; gap: 1.5rem; padding: 0.8rem 2rem; background: {CMK_BG_PANEL}; border-bottom: 2px solid {CMK_ACCENT}; }}
  .brand {{ display: flex; align-items: center; gap: 0.6rem; font-weight: 600; font-size: 1.05rem; }}
  .brand-text {{ color: {CMK_TEXT}; }}
  nav {{ font-size: 0.9rem; margin-left: auto; }}
  nav a {{ margin-left: 1.2rem; color: {CMK_TEXT_DIM}; text-decoration: none; }}
  nav a:hover {{ color: {CMK_ACCENT}; }}
  h1 {{ font-size: 1.2rem; color: {CMK_TEXT}; margin-top: 0; }}
  .meta {{ color: {CMK_TEXT_DIM}; font-size: 0.85rem; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
  th, td {{ border: 1px solid {CMK_BORDER}; padding: 0.4rem 0.6rem; text-align: left; white-space: nowrap; }}
  th {{ background: {CMK_BG_PANEL}; color: {CMK_TEXT_DIM}; font-weight: 600; }}
  tr:hover td {{ background: {CMK_BG_PANEL}; }}
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

  /* In-app settings panel (account page): a normal section in the page
     flow, left-aligned under the title - NOT the centered login-style
     card above, which only makes sense full-screen on its own. */
  .panel {{ background: {NS_CARD_BG}; color: {NS_TEXT}; border: 1px solid {NS_CARD_BORDER}; border-radius: 8px; box-shadow: 0 1px 3px rgba(16, 24, 40, 0.15); padding: 1.2rem 1.5rem; margin-bottom: 1.2rem; max-width: 26rem; }}
  .panel h2 {{ font-size: 1.05rem; font-weight: 600; margin: 0 0 0.8rem; color: {NS_TEXT}; }}
  .panel label {{ display: block; font-size: 0.85rem; font-weight: 500; color: {NS_LABEL}; margin: 0.8rem 0 0.25rem; }}
  .panel input[type=text], .panel input[type=password] {{ width: 100%; padding: 0.5rem 0.6rem; background: #ffffff; color: {NS_TEXT}; border: 1px solid {NS_INPUT_BORDER}; border-radius: 6px; box-sizing: border-box; }}
  .panel input[type=text]:focus, .panel input[type=password]:focus {{ outline: 2px solid {CMK_ACCENT}; outline-offset: 0; border-color: {CMK_ACCENT}; }}
  .panel button {{ margin-top: 1.2rem; }}

  button {{ padding: 0.5rem 1rem; background: {CMK_ACCENT}; color: #0a1410; border: none; border-radius: 3px; font-weight: 600; cursor: pointer; }}
  button:hover {{ opacity: 0.85; }}
"""


def page_shell(title: str, body: str, current_user: str = "") -> bytes:
    brand = f'{ydea_logo_img(56)}<span class="brand-text">Ydea Ticket DB</span>'
    nav_links = ""
    if current_user:
        nav_links = f'<a href="/">Ticket</a><a href="/account">Account ({html.escape(current_user)})</a><a href="/logout">Esci</a>'
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

    body = f"""
<h1>Search</h1>
<form method="get">
  <input type="text" name="q" placeholder="filtra per host, azienda o titolo..." value="{html.escape(search)}">
  <button type="submit">Cerca</button>
</form>
{error_html}
<table>
<tr>
  <th>Host</th><th>Ticket</th><th>Titolo</th><th>Stato</th><th>Priorita</th><th>Tipo</th>
  <th>Assegnatario</th><th>Azienda</th><th>Contratto</th>
  <th>Creato (Ydea)</th><th>Modificato (Ydea)</th><th>Chiuso (Ydea)</th><th>Sync</th>
</tr>
{"".join(body_rows) if body_rows else "<tr><td colspan='13'>Nessun ticket in cache.</td></tr>"}
</table>"""
    return page_shell("Ydea Ticket DB", body, current_user)


def render_account_page(current_user: str, message: str = "", is_error: bool = False) -> bytes:
    users = list(load_all_credentials().keys())
    msg_html = f'<p class="{"error" if is_error else "ok"}">{html.escape(message)}</p>' if message else ""
    users_html = "".join(f"<li>{html.escape(u)}</li>" for u in users)
    body = f"""
<h1>Account</h1>
<div class="meta">Autenticato come <b>{html.escape(current_user)}</b>. Utenti esistenti: <ul>{users_html}</ul></div>
{msg_html}
<div class="panel">
<h2>Cambia la tua password</h2>
<form method="post" action="/account">
  <input type="hidden" name="action" value="change_password">
  <label for="new_password">Nuova password:</label>
  <input type="password" name="new_password" id="new_password" required minlength="8">
  <label for="confirm_password">Conferma:</label>
  <input type="password" name="confirm_password" id="confirm_password" required minlength="8">
  <button type="submit">Cambia password</button>
</form>
</div>
<div class="panel">
<h2>Crea nuovo utente</h2>
<form method="post" action="/account">
  <input type="hidden" name="action" value="add_user">
  <label for="new_username">Nome utente:</label>
  <input type="text" name="new_username" id="new_username" required>
  <label for="new_user_password">Password:</label>
  <input type="password" name="new_user_password" id="new_user_password" required minlength="8">
  <button type="submit">Crea utente</button>
</form>
</div>"""
    return page_shell("Account", body, current_user)


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
