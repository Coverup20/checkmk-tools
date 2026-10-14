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

Login and account pages reuse Checkmk's own #login_window card look (the
real dark modern-dark theme, not the lighter facelift one a prior pass of
this file mistakenly used) and the real rounded-hexagon logo vector, not
an approximation of either.

Version: 5.2.0"""

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

# Checkmk's own real rounded-hexagon icon (icon_checkmk_logo_min.svg from
# the facelift theme images, the same file every Checkmk login page links
# to via .login_window_logo_link) - the actual vector path, not a PNG
# approximation of something else. Rendered at 120px on the login card
# (the real .login_window_logo_link width) and smaller in the page header.
def cmk_logo_svg(width: int) -> str:
    height = round(width * 28 / 24)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 28" width="{width}" height="{height}">
  <path fill="#15d1a0" fill-rule="evenodd" clip-rule="evenodd"
    d="M12,0l12,7v13.9l-12,7l-12-7V7L12,0z M4.1,10.1v4.6L9.8,11v9.5l2.2,1.3l2.2-1.3V11l5.7,3.7v-4.6l-7.9-5L4.1,10.1z"/>
</svg>'''

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

  button {{ padding: 0.5rem 1rem; background: {CMK_ACCENT}; color: #0a1410; border: none; border-radius: 3px; font-weight: 600; cursor: pointer; }}
  button:hover {{ opacity: 0.85; }}
"""


def page_shell(title: str, body: str, current_user: str = "") -> bytes:
    brand = f'{cmk_logo_svg(24)}<span class="brand-text">Ydea ticket cache</span>'
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
<title>Login - Ydea ticket cache</title>
<style>{CMK_SHARED_CSS}
  body.login {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
  #login_window {{ text-align: center; }}
  #logo {{ margin-bottom: 1.2rem; }}
  .cmk-card form {{ text-align: left; }}
  #foot {{ margin-top: 1.5rem; color: {CMK_TEXT_DIM}; font-size: 0.75rem; text-align: center; }}
</style>
</head>
<body class="login">
<div id="login_window" class="cmk-card">
  <div id="logo">{cmk_logo_svg(120)}</div>
  {msg_html}
  <form method="post" action="/login">
    <label for="input_user">Utente:</label>
    <input type="text" name="username" id="input_user" required autofocus autocomplete="username">
    <label for="input_pass">Password:</label>
    <input type="password" name="password" id="input_pass" required autocomplete="current-password">
    <button type="submit">Accedi</button>
  </form>
</div>
<div id="foot">Ydea ticket cache</div>
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
<h1>Ydea ticket cache - shadow SQLite (sola lettura)</h1>
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
    return page_shell("Ydea ticket cache", body, current_user)


def render_account_page(current_user: str, message: str = "", is_error: bool = False) -> bytes:
    users = list(load_all_credentials().keys())
    msg_html = f'<p class="{"error" if is_error else "ok"}">{html.escape(message)}</p>' if message else ""
    users_html = "".join(f"<li>{html.escape(u)}</li>" for u in users)
    body = f"""
<h1>Account</h1>
<div class="meta">Autenticato come <b>{html.escape(current_user)}</b>. Utenti esistenti: <ul>{users_html}</ul></div>
{msg_html}
<div class="cmk-card">
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
<div class="cmk-card">
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
