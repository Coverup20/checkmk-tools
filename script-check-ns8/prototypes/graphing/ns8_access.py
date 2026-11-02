#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# CheckMK graphing definitions (metrics, combined graphs and Perf-O-Meters)
# for the four NS8 access and service-health checks:
#   - check_ns8_user_activity_api.py    (NS8.User.<account>)
#   - check_ns8_login_audit_api.py      (NS8.Login.SSH / .UI / .Failed / .Coverage)
#   - check_ns8_samba_audit_api.py      (NS8.Samba.Audit.Coverage / .Sessions / .Access.<share>)
#   - check_ns8_module_services_api.py  (NS8.Services / NS8.Services.<module>)
#
# Why this file is needed:
# CheckMK has no built-in definitions for custom metric names emitted by local
# checks. Without this plugin:
#   1. the "perfometer" column in every view and dashboard widget is blank,
#      because CheckMK does not know which metric to draw in the bar;
#   2. the graph view draws a separate single-line graph for every metric
#      (nine graphs per user × 17 users = 153 separate graphs), instead of one
#      combined graph per service showing logins by channel, logouts and
#      failures together.
#
# Deployment on the CheckMK site (installed automatically by
# script-tools/full/installation/install-ns8-access-dashboard.py):
#   ~/local/lib/python3/cmk_addons/plugins/ns8_checks/graphing/ns8_access.py
#   omd reload apache

from cmk.graphing.v1 import Title
from cmk.graphing.v1.graphs import Bidirectional as BiGraph
from cmk.graphing.v1.graphs import Graph, MinimalRange
from cmk.graphing.v1.metrics import Color, DecimalNotation, Metric, StrictPrecision, Unit
from cmk.graphing.v1.perfometers import Bidirectional as BiPerfometer
from cmk.graphing.v1.perfometers import Closed, FocusRange, Open, Perfometer, Stacked

UNIT_COUNT = Unit(DecimalNotation(""), StrictPrecision(0))

# --- Metrics: per-user and login channels -----------------------------------

metric_logins = Metric(
    name="logins",
    title=Title("Total logins (24h)"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_logouts = Metric(
    name="logouts",
    title=Title("Shell logouts (24h)"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_ssh_logins = Metric(
    name="ssh_logins",
    title=Title("Shell logins (SSH)"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_root_logins = Metric(
    name="root_logins",
    title=Title("Root shell logins"),
    unit=UNIT_COUNT,
    color=Color.ORANGE,
)
metric_ui_logins = Metric(
    name="ui_logins",
    title=Title("Cluster UI logins"),
    unit=UNIT_COUNT,
    color=Color.CYAN,
)
metric_human_logins = Metric(
    name="human_logins",
    title=Title("Human UI logins"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_service_logins = Metric(
    name="service_logins",
    title=Title("Service-account UI logins"),
    unit=UNIT_COUNT,
    color=Color.GRAY,
)
metric_without_mfa = Metric(
    name="without_mfa",
    title=Title("Logins without second factor"),
    unit=UNIT_COUNT,
    color=Color.ORANGE,
)
metric_folder_logins = Metric(
    name="folder_logins",
    title=Title("Samba folder logins"),
    unit=UNIT_COUNT,
    color=Color.PURPLE,
)
metric_folder_logouts = Metric(
    name="folder_logouts",
    title=Title("Samba folder logouts"),
    unit=UNIT_COUNT,
    color=Color.DARK_PURPLE,
)
metric_app_logins = Metric(
    name="app_logins",
    title=Title("Application logins (Mattermost)"),
    unit=UNIT_COUNT,
    color=Color.LIGHT_BLUE,
)
metric_failures = Metric(
    name="failures",
    title=Title("Rejected attempts (wrong credentials)"),
    unit=UNIT_COUNT,
    color=Color.RED,
)
metric_ssh_failures = Metric(
    name="ssh_failures",
    title=Title("Rejected SSH attempts"),
    unit=UNIT_COUNT,
    color=Color.RED,
)
metric_ui_failures = Metric(
    name="ui_failures",
    title=Title("Rejected UI attempts"),
    unit=UNIT_COUNT,
    color=Color.DARK_RED,
)
metric_platform_faults = Metric(
    name="platform_faults",
    title=Title("Platform auth faults (not bad credentials)"),
    unit=UNIT_COUNT,
    color=Color.YELLOW,
)
metric_distinct_users = Metric(
    name="distinct_users",
    title=Title("Distinct accounts"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_distinct_sources = Metric(
    name="distinct_sources",
    title=Title("Distinct source IPs"),
    unit=UNIT_COUNT,
    color=Color.DARK_CYAN,
)

# --- Metrics: audit coverage ------------------------------------------------

metric_recognised_events = Metric(
    name="recognised_events",
    title=Title("Recognised auth records"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_parsed_lines = Metric(
    name="parsed_lines",
    title=Title("Parsed journal records"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_history_days = Metric(
    name="history_days",
    title=Title("Queryable history (days, floor)"),
    unit=UNIT_COUNT,
    color=Color.CYAN,
)

# --- Metrics: Samba folder audit --------------------------------------------

metric_shares = Metric(
    name="shares",
    title=Title("Defined file shares"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_audited = Metric(
    name="audited",
    title=Title("Audited file shares"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_unaudited = Metric(
    name="unaudited",
    title=Title("Unaudited file shares (blind)"),
    unit=UNIT_COUNT,
    color=Color.ORANGE,
)
metric_without_session_tracking = Metric(
    name="without_session_tracking",
    title=Title("Shares without connect/disconnect"),
    unit=UNIT_COUNT,
    color=Color.YELLOW,
)
metric_audited_shares = Metric(
    name="audited_shares",
    title=Title("Audited shares"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_connects = Metric(
    name="connects",
    title=Title("Folder logins (connect)"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_disconnects = Metric(
    name="disconnects",
    title=Title("Folder logouts (disconnect)"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_events = Metric(
    name="events",
    title=Title("Recorded folder operations (24h)"),
    unit=UNIT_COUNT,
    color=Color.PURPLE,
)

# --- Metrics: NS8 module services -------------------------------------------

metric_modules = Metric(
    name="modules",
    title=Title("Installed NS8 modules"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_modules_failed = Metric(
    name="modules_failed",
    title=Title("Modules with failed services"),
    unit=UNIT_COUNT,
    color=Color.RED,
)
metric_modules_warning = Metric(
    name="modules_warning",
    title=Title("Modules with warnings"),
    unit=UNIT_COUNT,
    color=Color.ORANGE,
)
metric_modules_unknown = Metric(
    name="modules_unknown",
    title=Title("Unreadable modules"),
    unit=UNIT_COUNT,
    color=Color.GRAY,
)
metric_services = Metric(
    name="services",
    title=Title("Total systemd services"),
    unit=UNIT_COUNT,
    color=Color.BLUE,
)
metric_running = Metric(
    name="running",
    title=Title("Running services"),
    unit=UNIT_COUNT,
    color=Color.GREEN,
)
metric_services_idle = Metric(
    name="services_idle",
    title=Title("Idle units (oneshot/timer/socket)"),
    unit=UNIT_COUNT,
    color=Color.CYAN,
)
metric_failed = Metric(
    name="failed",
    title=Title("Failed services"),
    unit=UNIT_COUNT,
    color=Color.RED,
)

# --- Perf-O-Meters (most specific first so they never shadow each other) ----

# NS8.User.<account>: logins by channel on the right, logouts on the left.
perfometer_ns8_user = BiPerfometer(
    name="ns8_user_activity",
    left=Perfometer(
        name="ns8_user_logouts",
        focus_range=FocusRange(Closed(0), Open(10)),
        segments=["logouts", "folder_logouts"],
    ),
    right=Perfometer(
        name="ns8_user_logins",
        focus_range=FocusRange(Closed(0), Open(10)),
        segments=["ssh_logins", "ui_logins", "folder_logins", "app_logins", "failures"],
    ),
)

# NS8.Login.UI: human logins vs service-account polling.
perfometer_ns8_login_ui = Stacked(
    name="ns8_login_ui",
    upper=Perfometer(
        name="ns8_login_ui_human",
        focus_range=FocusRange(Closed(0), Open(10)),
        segments=["human_logins"],
    ),
    lower=Perfometer(
        name="ns8_login_ui_service",
        focus_range=FocusRange(Closed(0), Open(4000)),
        segments=["service_logins"],
    ),
)

# NS8.Login.SSH: shell logins vs logouts.
perfometer_ns8_login_ssh = BiPerfometer(
    name="ns8_login_ssh",
    left=Perfometer(
        name="ns8_login_ssh_out",
        focus_range=FocusRange(Closed(0), Open(20)),
        segments=["logouts"],
    ),
    right=Perfometer(
        name="ns8_login_ssh_in",
        focus_range=FocusRange(Closed(0), Open(20)),
        segments=["root_logins"],
    ),
)

# NS8.Login.Failed: rejected attempts by channel.
perfometer_ns8_login_failed = Perfometer(
    name="ns8_login_failed",
    focus_range=FocusRange(Closed(0), Open(10)),
    segments=["ssh_failures", "ui_failures", "platform_faults"],
)

# NS8.Login.Coverage: recognised records out of parsed records.
perfometer_ns8_login_coverage = Perfometer(
    name="ns8_login_coverage",
    focus_range=FocusRange(Closed(0), Closed("parsed_lines")),
    segments=["recognised_events"],
)

# NS8.Samba.Audit.Coverage: audited vs unaudited shares out of total shares.
perfometer_ns8_samba_coverage = Perfometer(
    name="ns8_samba_coverage",
    focus_range=FocusRange(Closed(0), Closed("shares")),
    segments=["audited", "unaudited"],
)

# NS8.Samba.Access.<share>: operations and connects/disconnects.
perfometer_ns8_samba_share = Stacked(
    name="ns8_samba_share",
    upper=Perfometer(
        name="ns8_samba_share_sessions",
        focus_range=FocusRange(Closed(0), Open(20)),
        segments=["connects", "disconnects"],
    ),
    lower=Perfometer(
        name="ns8_samba_share_ops",
        focus_range=FocusRange(Closed(0), Open(50)),
        segments=["events", "failures"],
    ),
)

# NS8.Samba.Sessions: folder connects vs disconnects.
perfometer_ns8_samba_sessions = BiPerfometer(
    name="ns8_samba_sessions",
    left=Perfometer(
        name="ns8_samba_disconnects",
        focus_range=FocusRange(Closed(0), Open(20)),
        segments=["disconnects"],
    ),
    right=Perfometer(
        name="ns8_samba_connects",
        focus_range=FocusRange(Closed(0), Open(20)),
        segments=["connects"],
    ),
)

# NS8.Services.<module>: running + idle + failed out of total services.
perfometer_ns8_module_services = Perfometer(
    name="ns8_module_services",
    focus_range=FocusRange(Closed(0), Closed("services")),
    segments=["running", "services_idle", "failed"],
)

# NS8.Services (roll-up): failed/warning/unknown modules out of total modules.
perfometer_ns8_services_rollup = Perfometer(
    name="ns8_services_rollup",
    focus_range=FocusRange(Closed(0), Closed("modules")),
    segments=["modules_failed", "modules_warning", "modules_unknown"],
)

# --- Combined Graphs (one readable chart per service instead of nine) -------

# NS8.User.<account>: logins stacked above, logouts mirrored below, failures as a line.
graph_ns8_user_sessions = BiGraph(
    name="ns8_user_sessions",
    title=Title("User logins (by channel) and logouts"),
    upper=Graph(
        name="ns8_user_in",
        title=Title("Logins"),
        minimal_range=MinimalRange(0, 5),
        compound_lines=["ssh_logins", "ui_logins", "folder_logins", "app_logins"],
        simple_lines=["logins", "failures", "platform_faults"],
        optional=["platform_faults"],
    ),
    lower=Graph(
        name="ns8_user_out",
        title=Title("Logouts"),
        minimal_range=MinimalRange(0, 5),
        compound_lines=["logouts", "folder_logouts"],
    ),
)

# NS8.Login.SSH
graph_ns8_login_ssh = Graph(
    name="ns8_login_ssh",
    title=Title("SSH shell logins and logouts (24h)"),
    minimal_range=MinimalRange(0, 10),
    compound_lines=["logins"],
    simple_lines=["logouts", "root_logins", "distinct_users", "distinct_sources"],
)

# NS8.Login.UI
graph_ns8_login_ui = Graph(
    name="ns8_login_ui",
    title=Title("Cluster UI logins: human vs service accounts"),
    minimal_range=MinimalRange(0, 10),
    compound_lines=["human_logins", "service_logins"],
    simple_lines=["logins", "without_mfa", "distinct_users"],
)

# NS8.Login.Failed
graph_ns8_login_failed = Graph(
    name="ns8_login_failed",
    title=Title("Rejected authentication attempts vs platform faults"),
    minimal_range=MinimalRange(0, 5),
    compound_lines=["ssh_failures", "ui_failures"],
    simple_lines=["failures", "platform_faults", "distinct_sources"],
    optional=["platform_faults"],
)

# NS8.Login.Coverage
graph_ns8_login_coverage = Graph(
    name="ns8_login_coverage",
    title=Title("Loki security stream coverage"),
    minimal_range=MinimalRange(0, 100),
    compound_lines=["recognised_events"],
    simple_lines=["parsed_lines", "history_days"],
)

# NS8.Samba.Audit.Coverage
graph_ns8_samba_coverage = Graph(
    name="ns8_samba_coverage",
    title=Title("Samba file-share audit coverage"),
    minimal_range=MinimalRange(0, 5),
    compound_lines=["audited", "unaudited"],
    simple_lines=["shares", "without_session_tracking"],
)

# NS8.Samba.Sessions
graph_ns8_samba_sessions = Graph(
    name="ns8_samba_sessions",
    title=Title("Samba folder logins and logouts (24h)"),
    minimal_range=MinimalRange(0, 10),
    compound_lines=["connects"],
    simple_lines=["disconnects", "distinct_users", "audited_shares"],
)

# NS8.Samba.Access.<share>
graph_ns8_samba_share = Graph(
    name="ns8_samba_share",
    title=Title("Samba share activity (24h)"),
    minimal_range=MinimalRange(0, 10),
    compound_lines=["connects", "disconnects"],
    simple_lines=["events", "failures", "distinct_users"],
)

# NS8.Services.<module>
graph_ns8_module_services = Graph(
    name="ns8_module_services",
    title=Title("Module systemd services"),
    minimal_range=MinimalRange(0, 10),
    compound_lines=["running", "services_idle", "failed"],
    simple_lines=["services"],
)

# NS8.Services (roll-up)
graph_ns8_services_rollup = Graph(
    name="ns8_services_rollup",
    title=Title("NS8 modules health roll-up"),
    minimal_range=MinimalRange(0, 12),
    compound_lines=["modules_failed", "modules_warning", "modules_unknown"],
    simple_lines=["modules"],
)
