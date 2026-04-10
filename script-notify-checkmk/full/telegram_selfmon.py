#!/usr/bin/python3
"""
telegram_selfmon - Generic Telegram Self-Monitoring Notification
Bulk: no

CheckMK notification script - sends self-monitoring alerts to a Telegram channel.
Configured via OMD environment variables.

Version: 1.4.0
"""
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

import os
import sys
import json
import re
import socket
import urllib.request
import urllib.parse

VERSION = "1.4.0"

# === CONFIG ===
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_SELFMON_CHAT_ID", "")
CUSTOMER_NAME = os.environ.get("TELEGRAM_CUSTOMER_NAME", "")
CMK_URL = os.environ.get("CMK_URL", "")
SITE = "monitoring"
# ==============

## Utils

_ISP_PTR = re.compile(
    r'\d{1,3}[.\-]\d{1,3}[.\-]\d{1,3}[.\-]\d{1,3}'
    r'|\.ppp\.'
    r'|\.dsl\.'
    r'|\.cable\.'
    r'|\.pool\.'
    r'|\.dynamic\.'
    r'|\.adsl\.'
    r'|\.broadband\.'
    r'|^(res|host|static|ip|ptr|dsl|cable|broadband|dynamic|pool|user|client|customer)[.\-_]',
    re.IGNORECASE
)


def _cmk_url_valid(url):
    return bool(url) and url.startswith(("http://", "https://")) and "<" not in url


def get_reverse_dns_url():
    try:
        req = urllib.request.Request("https://api.ipify.org")
        req.add_header("User-Agent", "CheckMK-Telegram-Notifier")
        with urllib.request.urlopen(req, timeout=5) as resp:
            public_ip = resp.read().decode().strip()
        hostname = socket.gethostbyaddr(public_ip)[0]
        if hostname and not _ISP_PTR.search(hostname):
            return f"https://{hostname}/monitoring"
    except Exception:
        pass
    return None


def get_status_prefix(state):
    s = state.upper()
    if s in ("OK", "UP"):
        return "🟢 [OK]"
    elif s in ("WARN", "WARNING"):
        return "🟡 [WARN]"
    elif s in ("CRIT", "CRITICAL", "DOWN"):
        return "🔴 [CRIT]"
    elif s == "UNKNOWN":
        return "🟡 [UNKNOWN]"
    return "[?]"


def send_telegram(token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup is not None:
        params["reply_markup"] = reply_markup
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    if '"ok":true' not in body and '"ok": true' not in body:
        sys.stderr.write(f"telegram_selfmon v{VERSION}: Telegram API error: {body[:200]}\n")
        raise RuntimeError(f"Telegram API error: {body[:200]}")
    sys.stdout.write("Telegram OK: message sent\n")

## Check

def check():
    if not TOKEN or not CHAT_ID:
        sys.stderr.write(f"telegram_selfmon v{VERSION}: TOKEN o CHAT_ID mancanti. Verifica /omd/sites/monitoring/etc/environment\n")
        return

    global CMK_URL
    if not CMK_URL:
        CMK_URL = get_reverse_dns_url() or "__NOT_EXPOSED__"

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
            service_enc = urllib.parse.quote(service, safe='')
            service_link = f"{CMK_URL}/check_mk/view.py?view_name=service&host={hostname}&service={service_enc}&site={SITE}"
            host_link = f"{CMK_URL}/check_mk/view.py?view_name=host&host={hostname}&site={SITE}"
            button = json.dumps({"inline_keyboard": [[
                {"text": "Servizio", "url": service_link},
                {"text": "Host", "url": host_link},
            ]]})
        elif CMK_URL == "__NOT_EXPOSED__":
            button = json.dumps({"inline_keyboard": [[
                {"text": "🔒 Panel unreachable (server not exposed)", "callback_data": "not_exposed"}
            ]]})
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
            button = json.dumps({"inline_keyboard": [[{"text": "Host", "url": host_link}]]})
        elif CMK_URL == "__NOT_EXPOSED__":
            button = json.dumps({"inline_keyboard": [[
                {"text": "🔒 Panel unreachable (server not exposed)", "callback_data": "not_exposed"}
            ]]})
        else:
            button = None

    prefix_label = f"[{CUSTOMER_NAME} SELF-MONITOR] " if CUSTOMER_NAME else "[SELF-MONITOR] "
    msg = f"{prefix_label}{msg}"
    send_telegram(TOKEN, CHAT_ID, msg, button)

check()
