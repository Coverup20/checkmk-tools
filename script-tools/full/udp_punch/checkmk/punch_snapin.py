#!/usr/bin/env python3
# Sidebar snapin for the UDP punch tunnel status (CheckMK site local plugin).
#
# Reads the status snapshot written by punch_dashboard.py and shows one line
# per tunnel instance in the navigation sidebar. The snapshot is the only data
# source because the site user cannot read the system journal.

import json

from cmk.gui.htmllib.html import html
from cmk.gui.i18n import _
from cmk.gui.sidebar._snapin import CustomizableSidebarSnapin, snapin_registry

VERSION = "1.0.0"

STATUS_FILE = "/var/lib/cmk-punch-dashboard/status.json"
SERVICES_VIEW = "view.py?view_name=allservices&host=punch-tunnels"

STATE_CLASS = {
    "up": "up",
    "down": "down",
    "restarting": "warn",
    "unknown": "warn",
}


def _rows():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return list(data.get("instances", []))


def _age(seconds):
    if not isinstance(seconds, int):
        return "no session"
    if seconds < 90:
        return "%ds" % seconds
    if seconds < 5400:
        return "%dm" % (seconds // 60)
    return "%dh" % (seconds // 3600)


class PunchStatusSnapin(CustomizableSidebarSnapin):
    @staticmethod
    def type_name():
        return "punch_status"

    @classmethod
    def title(cls):
        return _("UDP punch")

    @classmethod
    def description(cls):
        return _("State of the UDP punch tunnel instances")

    @classmethod
    def vs_parameters(cls):
        return []

    @classmethod
    def parameters(cls):
        return {}

    def styles(self):
        return (
            ".punch-table{border-collapse:collapse;width:100%}"
            ".punch-table td{padding:1px 3px;font-size:12px}"
            ".punch-dot{width:10px;text-align:center}"
            ".punch-up .punch-dot{color:#2e7d32}"
            ".punch-down .punch-dot{color:#cf222e}"
            ".punch-warn .punch-dot{color:#9a6700}"
            ".punch-summary{font-weight:600;margin-bottom:4px}"
        )

    def show(self, config):
        rows = _rows()
        html.open_div(class_="punchsnapin")
        if rows is None:
            html.div(_("status snapshot missing"), class_="punch-down")
            html.close_div()
            return
        up = sum(1 for row in rows if row.get("status") == "up")
        html.open_a(href=SERVICES_VIEW)
        html.div("%d / %d up" % (up, len(rows)), class_="punch-summary")
        html.close_a()
        html.open_table(class_="punch-table")
        for row in rows:
            status = row.get("status") or "unknown"
            html.open_tr(class_="punch-%s" % STATE_CLASS.get(status, "warn"))
            html.open_td(class_="punch-dot")
            html.write_text_permissive(chr(0x25CF))
            html.close_td()
            html.open_td()
            html.write_text(str(row.get("instance") or "?"))
            html.close_td()
            html.open_td()
            html.write_text(_age(row.get("handshake_ago")))
            html.close_td()
            html.close_tr()
        html.close_table()
        html.close_div()


snapin_registry.register(PunchStatusSnapin)
