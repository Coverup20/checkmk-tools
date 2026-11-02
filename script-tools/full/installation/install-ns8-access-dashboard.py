#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Install the "NS8 access and services" views and dashboard into a CheckMK
# site: who logged in and out, on which NS8 channel, and whether every
# module's services are healthy.
#
# It is a sibling of install-compliance-dashboard.py and deliberately repeats
# its schema decisions rather than importing them, because each installer must
# stay a single file that can be copied to a site and run.
#
# The four schema traps this shape avoids, each of which cost a failed attempt
# when the NIS compliance dashboard was first written:
#   1. a sorter is a 3-tuple (name, negate, join_key). A dict or a longer
#      tuple makes SorterSpec raise on every page using the view.
#   2. CheckMK 2.5 stores "widgets" plus "embedded_views", not "dashlets".
#   3. filters belong on the WIDGET. An embedded view is created with an empty
#      context that wins, so filtering the embedded view instead shows every
#      service on the site.
#   4. visuals are keyed by the bare name. Keying by an (owner, name) tuple
#      puts a tuple into the "name" field, and the GUI later sorts visuals by
#      name, raising "'<' not supported between instances of 'str' and
#      'tuple'" on every view page on the site, not just these.
#
# And the trap that is not about schema at all: the GUI serves a compiled copy
# from tmp/check_mk/visuals_cache and will happily ignore a correct .mk file
# until that cache is invalidated. Reading the file back proves nothing.

import argparse
import ast
import datetime
import os
import pprint
import shutil
import sys

VERSION = "1.0.0"

# The services produced by the NS8 access checks.
USERS_REGEX = "^NS8\\.User\\."
SESSIONS_REGEX = "^NS8\\.(Login|Samba)\\."
SERVICES_REGEX = "^NS8\\.Services"
ALL_REGEX = "^NS8\\.(User|Login|Samba|Services)"

# The problems panel lists what somebody has to act on. It leaves out the
# NS8.Services roll-up, which only restates what its per-module services
# already say, so a broken module is not listed twice.
PROBLEMS_REGEX = "^NS8\\.(User|Login|Samba)\\.|^NS8\\.Services\\."

VIEW_ALL = "ns8_access_all"
VIEW_PROBLEMS = "ns8_access_problems"
VIEW_USERS = "ns8_access_users"
VIEW_SESSIONS = "ns8_access_sessions"
VIEW_SERVICES = "ns8_access_services"
VIEW_USERS_GRAPHS = "ns8_access_users_graphs"
VIEW_SESSIONS_GRAPHS = "ns8_access_sessions_graphs"

DASHBOARD_ID = "ns8_access"
DASHBOARD_USERS_ID = "ns8_user_access"
DASHBOARD_SESSIONS_ID = "ns8_session_access"

OWNED_VIEWS = (
    VIEW_ALL,
    VIEW_PROBLEMS,
    VIEW_USERS,
    VIEW_SESSIONS,
    VIEW_SERVICES,
    VIEW_USERS_GRAPHS,
    VIEW_SESSIONS_GRAPHS,
)
OWNED_DASHBOARDS = (
    DASHBOARD_ID,
    DASHBOARD_USERS_ID,
    DASHBOARD_SESSIONS_ID,
)

# Validated against cmk_time_graph_params() on CheckMK 2.5.0p17:
#   - 90000s (25h) is a built-in graph_timeranges value (86400s is rejected!)
#   - all 13 keys of graph_render_options are required by the Dictionary
#     ValueSpec, and "size" is NOT an allowed key.
#   - disabling show_time_range_previews and show_legend keeps each row to a
#     single inline chart instead of appending four range thumbnails + legend.
COMPACT_GRAPH_PARAMS = {
    "set_default_time_range": 90000,
    "graph_render_options": {
        "font_size": 8.0,
        "show_title": "inline",
        "title_format": ["plain"],
        "show_graph_time": False,
        "show_margin": False,
        "show_legend": False,
        "show_vertical_axis": True,
        "vertical_axis_width": "fixed",
        "show_time_axis": True,
        "show_controls": False,
        "show_pin": False,
        "show_time_range_previews": False,
        "fixed_timerange": False,
    },
}


## Useful

def site_root():
    """Return the site home directory, or exit when not run as a site user."""
    root = os.environ.get("OMD_ROOT", "")
    if not root or not os.path.isdir(root):
        sys.exit(
            "This script must run as the CheckMK site user (OMD_ROOT is not set).\n"
            "Try:  omd su <site>  then run it again."
        )
    return root


def config_path(root, filename):
    return os.path.join(
        root, "var", "check_mk", "web", os.environ.get("CMK_USER", ""), filename
    )


def load_mk(path):
    """Read a CheckMK .mk config file into a dict, tolerating an absent file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError as exc:
        sys.exit("Cannot read %s: %s" % (path, exc))
    if not text:
        return {}
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        sys.exit("Cannot parse %s: %s" % (path, exc))


def invalidate_visuals_cache(root):
    """Drop CheckMK's compiled cache of views and dashboards.

    The GUI does not reread user_views.mk and user_dashboards.mk on every
    request: it serves a compiled copy from tmp/check_mk/visuals_cache and
    refreshes it only when the marker there is older than the source. Writing
    the .mk files behind the GUI's back leaves that marker untouched, so the
    old definition keeps being served - which looks exactly like a filter that
    is present in the file but ignored on screen."""
    cache_dir = os.path.join(root, "tmp", "check_mk", "visuals_cache")
    removed = []
    for what in ("views", "dashboards"):
        for name in ("last_update_%s" % what, "cached_%s" % what):
            target = os.path.join(cache_dir, name)
            if os.path.exists(target):
                try:
                    os.unlink(target)
                    removed.append(name)
                except OSError:
                    pass
    return removed


def save_mk(path, data):
    """Write a CheckMK .mk config file, keeping a timestamped backup."""
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent, mode=0o770, exist_ok=True)
    if os.path.exists(path):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, "%s.bak-%s" % (path, stamp))
    tmp = "%s.tmp" % path
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(pprint.pformat(data))
        handle.write("\n")
    os.replace(tmp, path)


## Shape

def painter(name, link_view=None, parameters=None):
    """One column of a view. CheckMK 2.5 stores painters as dicts, not tuples."""
    return {
        "name": name,
        "column_title": None,
        "column_type": "column",
        "join_value": None,
        "link_spec": ("views", link_view) if link_view else None,
        "parameters": dict(parameters) if parameters else {},
        "tooltip": None,
    }


def sorter(name, negate=False):
    """One sort key. SorterSpec takes at most (sorter, negate, join_key)."""
    return (name, negate, None)


def filter_context(service_regex, states=None):
    """The filters that decide which services a view or widget shows."""
    context = {
        "serviceregex": {"service_regex": service_regex, "neg_service_regex": ""},
    }
    if states is not None:
        context["svcstate"] = {
            "st0": "on" if 0 in states else "",
            "st1": "on" if 1 in states else "",
            "st2": "on" if 2 in states else "",
            "st3": "on" if 3 in states else "",
        }
    return context


def render_body(with_log=False, sort_by_name=False, with_graph=True):
    """How a view draws its rows.

    with_log adds the event log in the long output.
    with_graph adds the inline time-series graph (svc_pnpgraph) with compact
    parameters, so each row renders its combined time-series chart directly in
    the table instead of requiring a separate click.
    perfometer is always included because custom metrics for all four checks
    are registered in ns8_access.py.

    sort_by_name keeps the per-user list in a stable alphabetical order."""
    painters = [
        painter("service_state"),
        painter("host", "host"),
        painter("service_description", "service"),
        painter("perfometer"),
    ]
    if with_graph:
        painters.append(painter("svc_pnpgraph", parameters=COMPACT_GRAPH_PARAMS))
    painters.append(painter("svc_plugin_output"))
    if with_log:
        painters.append(painter("svc_long_plugin_output"))
    painters.append(painter("svc_state_age"))

    if sort_by_name:
        sorters = [sorter("svcdescr"), sorter("site_host")]
    else:
        # Worst state first, so a CRITICAL component is never below an OK one.
        sorters = [sorter("svcstate", negate=True), sorter("site_host"),
                   sorter("svcdescr")]

    return {
        "datasource": "services",
        "single_infos": [],
        "browser_reload": 60,
        "column_headers": "pergroup",
        "num_columns": 1,
        "play_sounds": False,
        "force_checkboxes": False,
        "user_sortable": True,
        "layout": "table",
        "painters": painters,
        "group_painters": [painter("host", "host")],
        "sorters": sorters,
    }


def view_body(title, description, service_regex, states=None, with_log=False,
              sort_by_name=False, with_graph=True):
    """A standalone view: the rendering keys plus its own filters."""
    body = render_body(with_log=with_log, sort_by_name=sort_by_name, with_graph=with_graph)
    body.update({
        "title": title,
        "description": description,
        "context": filter_context(service_regex, states=states),
        "mobile": False,
        "mustsearch": False,
    })
    return body


def service_view(user, name, title, description, service_regex, states=None,
                 with_log=False, sort_by_name=False, with_graph=True):
    """Build one standalone CheckMK view selecting services by name regex.

    Keyed by the bare view name: user_views.mk already lives in the owner's
    directory, so CheckMK takes the owner from the path and overwrites each
    visual's "name" with the dictionary key."""
    body = view_body(title, description, service_regex, states=states,
                     with_log=with_log, sort_by_name=sort_by_name, with_graph=with_graph)
    body.update({
        "owner": user,
        "name": name,
        "topic": "applications",
        "sort_index": 20,
        "icon": "services",
        "hidden": False,
        "hidebutton": False,
        "public": True,
        "add_context_to_title": True,
        "is_show_more": False,
        "packaged": False,
        "main_menu_search_terms": [],
        "link_from": {},
        "public_token_id": None,
    })
    return {name: body}


def build_views(user):
    views = {}
    views.update(service_view(
        user, VIEW_ALL,
        "NS8 access and services",
        "Every NS8 access and service-health check on every host: per-user "
        "access, shell and interface logins, Samba folder access, and the "
        "systemd services of each installed module.",
        ALL_REGEX, with_graph=False,
    ))
    views.update(service_view(
        user, VIEW_PROBLEMS,
        "NS8 access problems",
        "Access and service checks not OK: rejected logins, unaudited shares, "
        "unreadable audit sources and failed module services. The NS8.Services "
        "roll-up is left out so a broken module is not listed twice alongside "
        "its own service.",
        PROBLEMS_REGEX, states=[1, 2, 3], with_graph=False,
    ))
    views.update(service_view(
        user, VIEW_USERS,
        "NS8 access per user",
        "One row per account, with its counters and event log: shell, interface, "
        "Samba folder and Mattermost logins and logouts, plus rejected attempts. "
        "Accounts with no recorded access are shown too, because 'nobody used "
        "this account' is itself evidence.",
        USERS_REGEX, with_log=True, sort_by_name=True, with_graph=False,
    ))
    views.update(service_view(
        user, VIEW_SESSIONS,
        "NS8 logins and folder access",
        "Node-wide session evidence: shell logins and logouts, NS8 interface "
        "logins, rejected attempts, Samba folder sessions, and whether the "
        "audit sources behind them can be trusted.",
        SESSIONS_REGEX, with_log=True, with_graph=False,
    ))
    views.update(service_view(
        user, VIEW_SERVICES,
        "NS8 module services",
        "The systemd services of every installed NS8 module. Units that are "
        "loaded but idle (oneshot, timer, socket-activated) are reported as "
        "idle, not as faults.",
        SERVICES_REGEX, with_graph=False,
    ))

    # Two boxed_graph views: one chart per service, full size. These feed the
    # two dedicated graph dashboards (kept separate from the table dashboard).
    views.update(_boxed_graph_view(user, VIEW_USERS_GRAPHS,
        "NS8 access per user - graphs",
        "One time-series graph per account: logins by channel, logouts and failures.",
        USERS_REGEX))
    views.update(_boxed_graph_view(user, VIEW_SESSIONS_GRAPHS,
        "NS8 logins and folder access - graphs",
        "One time-series graph per session audit service: SSH, UI, failures, "
        "Samba folder sessions and audit coverage.",
        SESSIONS_REGEX))
    return views


def _boxed_graph_view(user, name, title, description, service_regex):
    """A standalone boxed_graph view listing one full-size chart per service.

    boxed_graph is the CheckMK layout purpose-built for graph collections (the
    built-in "Service graphs" view uses it), unlike a table row, whose inline
    chart makes every row tall enough to make the table unusable."""
    return {
        name: {
            "owner": user,
            "name": name,
            "title": title,
            "description": description,
            "topic": "applications",
            "sort_index": 21,
            "icon": "service_graph",
            "hidden": False,
            "hidebutton": False,
            "public": True,
            "add_context_to_title": True,
            "is_show_more": False,
            "packaged": False,
            "main_menu_search_terms": [],
            "link_from": {},
            "public_token_id": None,
            "layout": "boxed_graph",
            "num_columns": 2,
            "column_headers": "off",
            "datasource": "services",
            "context": filter_context(service_regex),
            "single_infos": ["service", "host"],
            "browser_reload": 60,
            "painters": [painter("service_graphs")],
            "group_painters": [painter("host", "host"), painter("service_description", "service")],
            "sorters": [sorter("site_host"), sorter("svcdescr")],
        }
    }


def widget(widget_id, view_key, title, link_view, context, x, y, width, height):
    """One dashboard widget rendering an embedded view.

    The widget carries the filters, matching how the dashboards already on the
    site are built."""
    return (widget_id, {
        "type": "embedded_view",
        "name": view_key,
        "title": title,
        "title_url": "view.py?view_name=%s" % link_view,
        "position": (x, y),
        "size": (width, height),
        "show_title": True,
        "background": True,
        "reload_on_resize": False,
        "context": context,
        "single_infos": [],
        "datasource": "services",
    })


def _dashboard_def(owner, name, title, description, topic, sort_index, icon,
                   layout, widgets, embedded):
    """The common body of a CheckMK 2.5 dashboard definition."""
    return {
        name: {
            "owner": owner,
            "name": name,
            "title": title,
            "description": description,
            "topic": topic,
            "sort_index": sort_index,
            "icon": icon,
            "layout": layout,
            "widgets": widgets,
            "embedded_views": embedded,
            "mtime": int(datetime.datetime.now().timestamp()),
            "show_title": True,
            "hidden": False,
            "hidebutton": False,
            "public": True,
            "public_token_id": None,
            "single_infos": [],
            "context": {},
            "add_context_to_title": True,
            "is_show_more": False,
            "packaged": False,
            "main_menu_search_terms": [],
            "link_from": {},
            "mandatory_context_filters": [],
        }
    }


def build_dashboard(user):
    """The table dashboard (no inline graphs), matching the approved layout."""
    layout = (
        ("widget_problems", "dashlet_0", VIEW_PROBLEMS,
         "Needs attention - access and services",
         PROBLEMS_REGEX, [1, 2, 3], False, False, False, 1, 1, 0, 28),
        ("widget_users", "dashlet_1", VIEW_USERS,
         "Access per user - logins, logouts and event log",
         USERS_REGEX, None, True, True, False, 1, 29, 55, 0),
        ("widget_sessions", "dashlet_2", VIEW_SESSIONS,
         "Logins, logouts and folder access",
         SESSIONS_REGEX, None, True, False, False, 56,29, 0, 36),
        ("widget_services", "dashlet_3", VIEW_SERVICES,
         "Services of the installed modules",
         SERVICES_REGEX, None, False, False, False, 56, 66, 0, 0),
    )

    widgets, embedded = _build_widgets(layout)
    return _dashboard_def(
        user, DASHBOARD_ID, "NS8 access and services",
        "Who logged in and out on every NS8 channel, account by account, and "
        "whether the services of each installed module are healthy. Problems "
        "first, then per-user access with its event log beside the node-wide "
        "session evidence and the module services.",
        "overview", 16, "dashboard_main", {"type": "relative_grid"},
        widgets, embedded,
    )


def build_users_dashboard(user):
    """Dedicated per-user dashboard: table with inline graphs + event log."""
    layout = (
        ("widget_users", "dashlet_0", VIEW_USERS,
         "Access per user - logins, logouts, graph and event log",
         USERS_REGEX, None, True, True, True, 1, 1, 0, 0),
    )
    widgets, embedded = _build_widgets(layout)
    return _dashboard_def(
        user, DASHBOARD_USERS_ID, "NS8 access per user",
        "One row per account with the inline time-series graph and the event "
        "log: shell, interface, Samba folder and Mattermost logins and logouts, "
        "plus rejected attempts.",
        "overview", 17, "dashboard_main", {"type": "relative_grid"},
        widgets, embedded,
    )


def build_sessions_dashboard(user):
    """Dedicated session/folder dashboard: table with inline graphs + log."""
    layout = (
        ("widget_sessions", "dashlet_0", VIEW_SESSIONS,
         "Logins, logouts and folder access",
         SESSIONS_REGEX, None, True, False, True, 1, 1, 0, 0),
    )
    widgets, embedded = _build_widgets(layout)
    return _dashboard_def(
        user, DASHBOARD_SESSIONS_ID, "NS8 logins and folder access",
        "Node-wide session evidence with the inline time-series graph and event "
        "log: shell logins and logouts, NS8 interface logins, rejected "
        "attempts, Samba folder sessions, and audit-source coverage.",
        "overview", 18, "dashboard_main", {"type": "relative_grid"},
        widgets, embedded,
    )


def _build_widgets(layout):
    """Turn a widget layout into (widgets, embedded_views) maps."""
    widgets = {}
    embedded = {}
    for (wid, view_key, link_view, title, regex, states, with_log, by_name, with_graph,
         x, y, w, h) in layout:
        context = filter_context(regex, states=states)
        key, body = widget(wid, view_key, title, link_view, context, x, y, w, h)
        widgets[key] = body
        embedded[view_key] = render_body(with_log=with_log, sort_by_name=by_name,
                                         with_graph=with_graph)
    return widgets, embedded


## Self-test

def self_test():
    failures = 0
    ran = 0

    def expect(name, cond, detail=""):
        nonlocal failures, ran
        ran += 1
        if not cond:
            failures += 1
        print("%s  %s" % ("PASS" if cond else "FAIL", name))
        if not cond and detail:
            print("      %s" % detail)

    views = build_views("cmkadmin")
    board = build_dashboard("cmkadmin")
    users_board = build_users_dashboard("cmkadmin")
    sessions_board = build_sessions_dashboard("cmkadmin")

    # --- view keys ---
    expect("all seven views are built", set(views) == set(OWNED_VIEWS), str(sorted(views)))
    expect("views are keyed by a plain string, never an (owner, name) tuple",
           all(isinstance(k, str) for k in views), str(sorted(views)))
    expect("each view's name matches its key",
           all(v["name"] == k for k, v in views.items()), "")
    expect("each view records its owner",
           all(v["owner"] == "cmkadmin" for v in views.values()), "")

    # --- painters and sorters ---
    expect("views store painters as dicts, the 2.5 schema",
           all(isinstance(p, dict) and "name" in p
               for v in views.values() for p in v["painters"]), "")
    all_sorters = [s for v in views.values() for s in v["sorters"]]
    expect("sorters are 3-tuples, what SorterSpec accepts",
           all_sorters and all(isinstance(s, tuple) and len(s) == 3 for s in all_sorters),
           str(all_sorters[:2]))
    expect("sorters carry a plain name, a bool and a join key",
           all(isinstance(s[0], str) and isinstance(s[1], bool) and s[2] is None
               for s in all_sorters), str(all_sorters[:2]))

    # --- what the per-user view must show (table view, no inline graph) ---
    user_painters = [p["name"] for p in views[VIEW_USERS]["painters"]]
    expect("the per-user view shows the metric bar, so counters are visible",
           "perfometer" in user_painters, str(user_painters))
    expect("the per-user view shows the long output, which is the event log",
           "svc_long_plugin_output" in user_painters, str(user_painters))
    expect("the per-user table view has no inline graph (graphs live elsewhere)",
           "svc_pnpgraph" not in user_painters, str(user_painters))
    expect("the per-user view is sorted by name, so a person stays in one place",
           views[VIEW_USERS]["sorters"][0][0] == "svcdescr",
           str(views[VIEW_USERS]["sorters"]))
    expect("the problems view is sorted worst-first",
           views[VIEW_PROBLEMS]["sorters"][0] == ("svcstate", True, None),
           str(views[VIEW_PROBLEMS]["sorters"]))
    expect("the dedicated per-user boxed_graph view is built",
           views[VIEW_USERS_GRAPHS]["layout"] == "boxed_graph", "")
    expect("the dedicated sessions boxed_graph view is built",
           views[VIEW_SESSIONS_GRAPHS]["layout"] == "boxed_graph", "")

    # --- filters ---
    expect("the per-user view selects only NS8.User services",
           views[VIEW_USERS]["context"]["serviceregex"]["service_regex"] == USERS_REGEX,
           "")
    problems_states = views[VIEW_PROBLEMS]["context"]["svcstate"]
    expect("the problems view hides OK and keeps the other three states",
           problems_states["st0"] == "" and problems_states["st1"] == "on"
           and problems_states["st2"] == "on" and problems_states["st3"] == "on",
           str(problems_states))
    expect("the problems view leaves out the NS8.Services roll-up",
           "NS8\\.Services\\." in PROBLEMS_REGEX
           and not PROBLEMS_REGEX.endswith("NS8\\.Services"), PROBLEMS_REGEX)

    # --- dashboard shape ---
    body = board[DASHBOARD_ID]
    expect("dashboard uses the 2.5 widgets schema, not dashlets",
           "widgets" in body and "dashlets" not in body, str(sorted(body)))
    expect("the main dashboard embeds four widgets", len(body["widgets"]) == 4,
           str(sorted(body["widgets"])))
    expect("every widget has a matching embedded view",
           all(w["name"] in body["embedded_views"] for w in body["widgets"].values()),
           str(sorted(body["embedded_views"])))
    expect("every widget carries its own filters",
           all(w["context"].get("serviceregex", {}).get("service_regex")
               for w in body["widgets"].values()), "")
    expect("embedded views carry no context of their own, so the widget wins",
           all("context" not in v for v in body["embedded_views"].values()),
           str([sorted(v) for v in body["embedded_views"].values()][:1]))
    expect("the main dashboard has no inline graphs in any widget",
           all("svc_pnpgraph" not in [p["name"] for p in v["painters"]]
               for v in body["embedded_views"].values()), "")
    expect("the per-user widget keeps the event log",
           any("svc_long_plugin_output" in [p["name"] for p in v["painters"]]
               for v in body["embedded_views"].values()), "")
    expect("widget positions and sizes are tuples",
           all(isinstance(w["position"], tuple) and isinstance(w["size"], tuple)
               for w in body["widgets"].values()), "")
    expect("the dashboard is keyed by a plain string",
           all(isinstance(k, str) for k in board), str(sorted(board)))

    # --- the two dedicated graph dashboards ---
    for label, b in (("users", users_board[DASHBOARD_USERS_ID]),
                     ("sessions", sessions_board[DASHBOARD_SESSIONS_ID])):
        evs = list(b["embedded_views"].values())
        expect("%s dashboard has one widget" % label, len(b["widgets"]) == 1,
                str(sorted(b["widgets"])))
        expect("%s dashboard shows the inline graph" % label,
               all("svc_pnpgraph" in [p["name"] for p in v["painters"]] for v in evs),
               str([[p["name"] for p in v["painters"]] for v in evs]))
        expect("%s dashboard keeps the event log" % label,
               all("svc_long_plugin_output" in [p["name"] for p in v["painters"]] for v in evs),
               str([[p["name"] for p in v["painters"]] for v in evs]))
    expect("the three dashboards are distinct and all owned",
           set(OWNED_DASHBOARDS) == set(board) | set(users_board) | set(sessions_board)
           and len({board[DASHBOARD_ID]["title"],
                    users_board[DASHBOARD_USERS_ID]["title"],
                    sessions_board[DASHBOARD_SESSIONS_ID]["title"]}) == 3, "")

    # --- regexes actually match the services the checks emit ---
    import re
    emitted = [
        "NS8.User.nistest03", "NS8.User.root", "NS8.Login.SSH", "NS8.Login.UI",
        "NS8.Login.Failed", "NS8.Login.Coverage", "NS8.Samba.Sessions",
        "NS8.Samba.Audit.Coverage", "NS8.Samba.Access.nis-audited",
        "NS8.Services", "NS8.Services.samba1",
    ]
    expect("the catch-all regex matches every emitted service",
           all(re.search(ALL_REGEX, s) for s in emitted),
           str([s for s in emitted if not re.search(ALL_REGEX, s)]))
    expect("the per-user regex matches only user services",
           [s for s in emitted if re.search(USERS_REGEX, s)]
           == ["NS8.User.nistest03", "NS8.User.root"], "")
    expect("the services regex matches the roll-up and the per-module services",
           sorted(s for s in emitted if re.search(SERVICES_REGEX, s))
           == ["NS8.Services", "NS8.Services.samba1"], "")
    expect("the problems regex excludes the NS8.Services roll-up",
           not re.search(PROBLEMS_REGEX, "NS8.Services")
           and bool(re.search(PROBLEMS_REGEX, "NS8.Services.samba1")), "")
    expect("an unrelated service is never matched",
           not re.search(ALL_REGEX, "NS8.Modules.Updates")
           and not re.search(ALL_REGEX, "Patch.Posture"), "")

    print("")
    print("%d/%d checks passed" % (ran - failures, ran))
    sys.exit(1 if failures else 0)


## Install

def install(user, dry_run):
    root = site_root()
    os.environ["CMK_USER"] = user

    views_path = config_path(root, "user_views.mk")
    dash_path = config_path(root, "user_dashboards.mk")

    views = load_mk(views_path)
    dashboards = load_mk(dash_path)

    new_views = build_views(user)
    new_dash = {}
    new_dash.update(build_dashboard(user))
    new_dash.update(build_users_dashboard(user))
    new_dash.update(build_sessions_dashboard(user))

    replaced = [k for k in new_views if k in views]
    kept = [k for k in views if k not in new_views]
    kept_dash = [k for k in dashboards if k not in new_dash]

    if dry_run:
        print("DRY RUN - nothing written")
        print("  views file     : %s" % views_path)
        print("  dashboards file: %s" % dash_path)
        print("  would add/replace %d views: %s"
              % (len(new_views), ", ".join(sorted(new_views))))
        print("  would leave %d existing views untouched" % len(kept))
        print("  would add/replace %d dashboards: %s"
              % (len(new_dash), ", ".join(sorted(new_dash))))
        print("  would leave %d existing dashboards untouched: %s"
              % (len(kept_dash), ", ".join(str(k) for k in kept_dash) or "none"))
        return 0

    views.update(new_views)
    dashboards.update(new_dash)
    save_mk(views_path, views)
    save_mk(dash_path, dashboards)
    dropped = invalidate_visuals_cache(root)

    print("Installed for user %s:" % user)
    for key in sorted(new_views):
        print("  view      %s%s" % (key, "  (replaced)" if key in replaced else ""))
    for key in sorted(new_dash):
        print("  dashboard %s" % key)
    print("\n%d pre-existing views and %d pre-existing dashboards were left untouched."
          % (len(kept), len(kept_dash)))
    print("Visuals cache invalidated (%s), so the GUI rereads these definitions."
          % (", ".join(dropped) if dropped else "nothing to drop"))
    print("Open from Monitor -> Overview -> NS8 access and services, "
          "NS8 access per user, or NS8 logins and folder access.")
    return 0


parser = argparse.ArgumentParser(
    description="Install the NS8 access and services views and dashboard into a CheckMK site."
)
parser.add_argument("--user", default="cmkadmin",
                    help="GUI user that will own the views and dashboard (default: cmkadmin)")
parser.add_argument("--dry-run", action="store_true",
                    help="show what would be written, change nothing")
parser.add_argument("--self-test", action="store_true",
                    help="run the built-in checks and exit")

args = parser.parse_args()

if args.self_test:
    self_test()
else:
    sys.exit(install(args.user, args.dry_run))
