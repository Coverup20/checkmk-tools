#!/usr/bin/env python3
"""telegram_tmate.py - Telegram notifications for Check MK Tmate channel

Dedicated notification script. TOKEN and CHAT_ID read from .env file:
  /omd/sites/monitoring/local/share/check_mk/notifications/telegram_tmate.env

Version: 1.0.0"""

import os
import sys
import urllib.parse
import urllib.request

VERSION = "1.0.0"

# === CONFIG ===
ENV_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "telegram_tmate.env"
)
CMK_URL = os.environ.get("CMK_URL", "https://<your-checkmk-server>/monitoring")
SITE = "monitoring"
# ==============


def load_env_file(path: str) -> None:
    """Load variables from .env file if not already present in the environment."""
    if not os.path.isfile(path):
        return
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get_emoji(state: str) -> str:
    state = state.upper()
    if state in ("OK", "UP"):
        return ""
    elif state in ("WARN", "WARNING"):
        return ""
    elif state in ("CRIT", "CRITICAL", "DOWN"):
        return ""
    elif state == "UNKNOWN":
        return ""
    return ""


def urlencode(value: str) -> str:
    return urllib.parse.quote(value, safe='')


def send_telegram(token: str, chat_id: str, text: str, reply_markup: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "reply_markup": reply_markup,
        "parse_mode": "HTML",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception:
        pass  # Notifiche non devono bloccare CheckMK


def main() -> int:
    # Upload .env file
    load_env_file(ENV_FILE)

    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        sys.stderr.write(
            f"telegram_tmate v{VERSION}: TOKEN o CHAT_ID mancanti. "
            f"Verifica {ENV_FILE}\n"
        )
        return 1

    notify_what = os.environ.get("NOTIFY_WHAT", "SERVICE")
    hostname = os.environ.get("NOTIFY_HOSTNAME", "unknown")
    host_address = os.environ.get("NOTIFY_HOSTADDRESS", "")
    real_ip = os.environ.get("NOTIFY_HOSTLABEL_real_ip", host_address)

    if notify_what == "SERVICE":
        state = os.environ.get("NOTIFY_SERVICESTATE", "UNKNOWN")
        service = os.environ.get("NOTIFY_SERVICEDESC", "SERVICE")
        output = os.environ.get("NOTIFY_SERVICEOUTPUT", "N/A")
        emoji = get_emoji(state)

        service_enc = urlencode(service)
        service_link = (
            f"{CMK_URL}/check_mk/view.py?view_name=service"
            f"&host={hostname}&service={service_enc}&site={SITE}"
        )
        host_link = (
            f"{CMK_URL}/check_mk/view.py?view_name=host"
            f"&host={hostname}&site={SITE}"
        )

        msg = (
            f"[{emoji} {state}] Servizio → {service}\n"
            f"Host: {hostname} ({real_ip})\n"
            f"Output: {output}"
        )
        button = (
            '{"inline_keyboard":[[{"text":" Servizio","url":"' + service_link + '"},'
            '{"text":" Host","url":"' + host_link + '"}]]}'
        )
    else:
        state = os.environ.get("NOTIFY_HOSTSTATE", "UNKNOWN")
        output = os.environ.get("NOTIFY_HOSTOUTPUT", "N/A")
        emoji = get_emoji(state)

        host_link = (
            f"{CMK_URL}/check_mk/view.py?view_name=host"
            f"&host={hostname}&site={SITE}"
        )

        msg = (
            f"[{emoji} {state}] Host → {hostname}\n"
            f"IP: {real_ip}\n"
            f"Output: {output}"
        )
        button = (
            '{"inline_keyboard":[[{"text":" Host","url":"' + host_link + '"}]]}'
        )

    msg = f" [TMATE] {msg}"
    send_telegram(token, chat_id, msg, button)
    return 0


if __name__ == "__main__":
    sys.exit(main())
