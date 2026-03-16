#!/usr/bin/env python3
"""
notify_ticket_watcher.py - Watcher log CheckMK per notifiche Telegram ticket
Legge notify.log, intercetta [TICKET-EVENT] [CREATO] e manda messaggio Telegram.
Completamente indipendente dal sistema di notifica CheckMK.

Version: 1.2.0
"""

import os
import re
import json
import urllib.request
import urllib.parse
import sys

VERSION = "1.2.0"

LOG_FILE   = "/omd/sites/monitoring/var/log/notify.log"
STATE_FILE = "/omd/sites/monitoring/var/log/notify_ticket_watcher.json"

TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID  = "-1003770828164"
CMK_URL  = "https://monitor.nethlab.it/monitoring"

# Matcha solo le righe [cmk.base.notify] Output: per evitare duplicati
PATTERN = re.compile(
    r'\[cmk\.base\.notify\].*Output:.*\[TICKET-EVENT\] \[CREATO\] #(\d+) ([^/\n]+)/(.+?) (CRIT\w*|DOWN\w*|CRITICAL)'
)


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"pos": 0, "sent": []}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_telegram(ticket_id: str, hostname: str, service: str, state_str: str):
    emoji = "\U0001f534" if "CRIT" in state_str.upper() else "\U0001f7e0"
    host_enc = urllib.parse.quote(hostname, safe="")
    text = (
        f"\U0001f3ab <b>Ticket #{ticket_id} aperto</b>\n"
        f"{emoji} <b>{state_str}</b> \u2014 {hostname} / {service}\n"
        f'<a href="{CMK_URL}/check_mk/view.py?view_name=host&host={host_enc}">Vai a CheckMK</a>'
    )
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=10)


def main():
    if not os.path.exists(LOG_FILE):
        return

    state = load_state()
    pos = state.get("pos", 0)
    sent = set(state.get("sent", []))

    # Pulisci sent vecchi (tieni solo ultimi 500)
    if len(sent) > 500:
        sent = set(list(sent)[-500:])

    file_size = os.path.getsize(LOG_FILE)

    # Log ruotato (file piu piccolo di pos)
    if file_size < pos:
        pos = 0

    with open(LOG_FILE, "r", errors="replace") as f:
        f.seek(pos)
        new_lines = f.read()
        new_pos = f.tell()

    errors = []
    for match in PATTERN.finditer(new_lines):
        ticket_id = match.group(1)
        hostname  = match.group(2).strip()
        service   = match.group(3).strip()
        state_str = match.group(4).strip()

        if ticket_id in sent:
            continue

        try:
            send_telegram(ticket_id, hostname, service, state_str)
            sent.add(ticket_id)
        except Exception as e:
            errors.append(str(e))

    state["pos"] = new_pos
    state["sent"] = list(sent)
    save_state(state)

    if errors:
        print(f"WARN: {errors}", file=sys.stderr)


if __name__ == "__main__":
    main()