#!/usr/bin/env python3
"""
telegram_cl00 - Telegram notification script for customer CL00.

Version: 1.7.0
"""

import json
import os
import sys
import urllib.parse
import urllib.request

VERSION = "1.7.1"

# === CONFIG ===
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_NOTIFY_CHAT_ID", "")
CUSTOMER_NAME = os.environ.get("TELEGRAM_CL00_NAME", "CL00")

CMK_URL = os.environ.get("CMK_URL", "")
SITE = "monitoring"
# ==============


def _cmk_url_valid(url):
    return bool(url) and url.startswith(("http://", "https://")) and "<" not in url


def get_status_prefix(state: str) -> str:
    state = state.upper()
    if state in ("OK", "UP"):
        return "🟢 [OK]"
    elif state in ("WARN", "WARNING"):
        return "🟡 [WARN]"
    elif state in ("CRIT", "CRITICAL", "DOWN"):
        return "🔴 [CRIT]"
    elif state == "UNKNOWN":
        return "🟡 [UNKNOWN]"
    return "[?]"


def urlencode(value: str) -> str:
    return urllib.parse.quote(value, safe='')


def send_telegram(token: str, chat_id: str, text: str, reply_markup=None) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    data = urllib.parse.urlencode(params).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if '"ok":true' not in body and '"ok": true' not in body:
            sys.stderr.write(f"telegram_cl00 v{VERSION}: Telegram API error: {body[:200]}\n")
            raise RuntimeError(f"Telegram API error: {body[:200]}")
        sys.stdout.write("Telegram OK: message sent\n")
    except Exception as e:
        sys.stderr.write(f"telegram_cl00 v{VERSION}: send failed: {e}\n")
        raise


def main() -> int:
    if not TOKEN or not CHAT_ID:
        sys.stderr.write(f"telegram_cl00 v{VERSION}: TOKEN o CHAT_ID mancanti. Verifica /omd/sites/monitoring/etc/environment\n")
        return 1

    notify_what = os.environ.get("NOTIFY_WHAT", "SERVICE")
    hostname = os.environ.get("NOTIFY_HOSTNAME", "unknown")
    host_address = os.environ.get("NOTIFY_HOSTADDRESS", "")
    real_ip = os.environ.get("NOTIFY_HOSTLABEL_real_ip", host_address)

    if notify_what == "SERVICE":
        state = os.environ.get("NOTIFY_SERVICESTATE", "UNKNOWN")
        service = os.environ.get("NOTIFY_SERVICEDESC", "SERVICE")
        output = os.environ.get("NOTIFY_SERVICEOUTPUT", "N/A")
        prefix = get_status_prefix(state)

        msg = (
            f"{prefix} Servizio: {service}\n"
            f"Host: {hostname} ({real_ip})\n"
            f"Output: {output}"
        )
        if _cmk_url_valid(CMK_URL):
            service_enc = urlencode(service)
            service_link = f"{CMK_URL}/check_mk/view.py?view_name=service&host={hostname}&service={service_enc}&site={SITE}"
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = json.dumps({
                "inline_keyboard": [[
                    {"text": "Servizio", "url": service_link},
                    {"text": "Host", "url": host_link},
                ]]
            })
        else:
            button = None
    else:
        state = os.environ.get("NOTIFY_HOSTSTATE", "UNKNOWN")
        output = os.environ.get("NOTIFY_HOSTOUTPUT", "N/A")
        prefix = get_status_prefix(state)

        msg = (
            f"{prefix} Host: {hostname}\n"
            f"IP: {real_ip}\n"
            f"Output: {output}"
        )
        if _cmk_url_valid(CMK_URL):
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = json.dumps({
                "inline_keyboard": [[{"text": "Host", "url": host_link}]]
            })
        else:
            button = None

    # Customer prefix
    msg = f"[{CUSTOMER_NAME}] {msg}"

    send_telegram(TOKEN, CHAT_ID, msg, button)
    return 0


if __name__ == "__main__":
    sys.exit(main())
