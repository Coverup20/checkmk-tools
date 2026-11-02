#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Install the network exposure views and dashboard into a CheckMK site.
#
# The network exposure checks (Network.Exposure, Network.Listeners,
# Network.Firewall from check_network_exposure.py, and Twingate.Client plus one
# Twingate.Resource.<name> per resource from check_twingate_client.py) sit among
# hundreds of ordinary services on every host. This script installs one
# dashboard and four supporting views that select those services by name across
# every monitored host, with no host list to maintain: a new host appears as
# soon as it reports one of these services.
#
# Control reference: DE.CM-01 (the network and its services are monitored to
# detect potentially adverse events).
#
# Run this ON the CheckMK server, as the site user:
#   omd su <site>
#   python3 install-network-exposure-dashboard.py
#
# It writes to the site user's own GUI configuration, so nothing is shared or
# overwritten for other users unless --user says so. Re-running replaces the
# entries it owns and leaves every other view and dashboard untouched.

import argparse
import ast
import datetime
import os
import pprint
import shutil
import sys

VERSION = "1.0.0"

# Service name regexes. CheckMK filters services by regex, not by tag.
# Twingate.Resource.<name> is matched by the Twingate. prefix alone, so new
# resources appear without any change here.
NETWORK_REGEX = "^(Network\\.|Twingate\\.)"
FIREWALL_REGEX = "^Network\\.Firewall$"
LISTENERS_REGEX = "^Network\\.(Exposure|Listeners)$"

VIEW_ALL = "net_exposure_all"
VIEW_PROBLEMS = "net_exposure_problems"
VIEW_FIREWALL = "net_exposure_firewall"
VIEW_LISTENERS = "net_exposure_listeners"
DASHBOARD_ID = "network_exposure"

OWNED_VIEWS = (VIEW_ALL, VIEW_PROBLEMS, VIEW_FIREWALL, VIEW_LISTENERS)


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
    return os.path.join(root, "var", "check_mk", "web", os.environ.get("CMK_USER", ""), filename)


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
    request: it keeps a compiled copy under tmp/check_mk/visuals_cache and
    only refreshes it when the marker file there is older than the source.
    Writing the .mk files behind the GUI's back leaves that marker untouched,
    so the old definition keeps being served - which looks exactly like a
    filter that is present in the file but ignored on screen. Removing the
    markers forces a rebuild on the next request.

    Returns the list of markers actually removed."""
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


def painter(name, link_view=None):
    """One column of a view. CheckMK 2.5 stores painters as dicts, not tuples."""
    return {
        "name": name,
        "column_title": None,
        "column_type": "column",
        "join_value": None,
        "link_spec": ("views", link_view) if link_view else None,
        "parameters": {},
        "tooltip": None,
    }


def sorter(name, negate=False):
    """One sort key of a view.

    CheckMK builds a SorterSpec from this, and that constructor takes at most
    three positional values: (sorter, negate, join_key). Passing a dict, or a
    longer tuple, makes every page using the view raise an internal error."""
    return (name, negate, None)


def filter_context(service_regex, states=None):
    """The filters that decide which services a view or widget shows."""
    context = {
        "serviceregex": {"service_regex": service_regex, "neg_service_regex": ""},
    }
    if states is not None:
        # Service state filters are additive: only the wanted states are "on".
        context["svcstate"] = {
            "st0": "on" if 0 in states else "",
            "st1": "on" if 1 in states else "",
            "st2": "on" if 2 in states else "",
            "st3": "on" if 3 in states else "",
        }
    return context


def render_body():
    """How a view draws its rows.

    An embedded view inside a dashboard holds only these rendering keys: its
    filters live on the widget instead. Putting a context here and leaving the
    widget's context empty makes the widget show every service on the site,
    because the empty widget context is the one that wins."""
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
        "painters": [
            painter("service_state"),
            painter("host", "host"),
            painter("service_description", "service"),
            painter("svc_plugin_output"),
            painter("svc_state_age"),
        ],
        "group_painters": [painter("host", "host")],
        # Worst state first, so a CRITICAL component is never below an OK one.
        "sorters": [sorter("svcstate", negate=True), sorter("site_host"), sorter("svcdescr")],
    }


def view_body(title, description, service_regex, states=None):
    """A standalone view: the rendering keys plus its own filters."""
    body = render_body()
    body.update({
        "title": title,
        "description": description,
        "context": filter_context(service_regex, states=states),
        "mobile": False,
        "mustsearch": False,
    })
    return body


def service_view(user, name, title, description, service_regex, states=None):
    """Build one standalone CheckMK view selecting services by name regex.

    The returned mapping is keyed by the bare view name. user_views.mk already
    lives in the owner's own directory, so CheckMK takes the owner from the
    path and overwrites each visual's "name" with the dictionary key. Keying
    this by an (owner, name) tuple puts a tuple into that field, and the GUI
    later sorts visuals by name - which raises
    "'<' not supported between instances of 'str' and 'tuple'" on every view
    page, not just these."""
    body = view_body(title, description, service_regex, states=states)
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
        "Network exposure - all services",
        "Every network exposure, listener, firewall and Twingate service on "
        "every host, whatever its state.",
        NETWORK_REGEX,
    ))
    views.update(service_view(
        user, VIEW_PROBLEMS,
        "Network exposure problems",
        "Network exposure, listener, firewall and Twingate services not OK, "
        "every host: WARNING, CRITICAL or UNKNOWN.",
        NETWORK_REGEX,
        states=[1, 2, 3],
    ))
    views.update(service_view(
        user, VIEW_FIREWALL,
        "Network exposure - firewall (DE.CM-01)",
        "The inbound firewall state of every host: default INPUT policy and "
        "whether a firewall is active.",
        FIREWALL_REGEX,
    ))
    views.update(service_view(
        user, VIEW_LISTENERS,
        "Network exposure - listeners (DE.CM-01)",
        "Listening sockets that can be reached from outside each host, and the "
        "listener set compared with its baseline.",
        LISTENERS_REGEX,
    ))
    return views


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


def build_dashboard(user):
    """Dashboard in the CheckMK 2.5 shape: widgets plus their embedded views.

    A height of 0 means "stretch to the bottom", matching how the existing
    dashboards on the site are laid out."""
    layout = (
        ("widget_problems", "dashlet_0", VIEW_PROBLEMS,
         "Network exposure problems - every host",
         NETWORK_REGEX, [1, 2, 3], 1, 1, 0, 34),
        ("widget_listeners", "dashlet_1", VIEW_LISTENERS,
         "Listeners and exposure - DE.CM-01",
         LISTENERS_REGEX, None, 1, 35, 50, 0),
        ("widget_firewall", "dashlet_2", VIEW_FIREWALL,
         "Firewall - DE.CM-01",
         FIREWALL_REGEX, None, 51, 35, 0, 0),
    )

    widgets = {}
    embedded = {}
    for wid, view_key, link_view, title, regex, states, x, y, w, h in layout:
        context = filter_context(regex, states=states)
        key, body = widget(wid, view_key, title, link_view, context, x, y, w, h)
        widgets[key] = body
        embedded[view_key] = render_body()

    return {
        DASHBOARD_ID: {
            "owner": user,
            "name": DASHBOARD_ID,
            "title": "Network exposure (DE.CM-01)",
            "description": "Network exposure across every monitored host: which "
                           "listeners can be reached from outside, the state of "
                           "each firewall, and the Twingate client and its "
                           "resources. Problems first, then the listeners beside "
                           "the firewall state.",
            "topic": "overview",
            "sort_index": 15,
            "icon": "dashboard_main",
            "layout": {"type": "relative_grid"},
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


## Self-test

def self_test():
    import re as _re

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

    # Service names exactly as the two check scripts emit them
    # (check_network_exposure.py and check_twingate_client.py).
    emitted_network = ["Network.Exposure", "Network.Listeners", "Network.Firewall"]
    emitted_twingate = ["Twingate.Client", "Twingate.Resource.NS",
                        "Twingate.Resource.Office_VPC"]
    emitted = emitted_network + emitted_twingate
    unrelated = ["NS8.Containers", "Patch.Posture", "OS.Lifecycle", "CPU load",
                 "Filesystem /"]

    views = build_views("tester")
    expect("builds one view per network exposure angle", len(views) == 4, str(sorted(views)))
    expect("every view is owned by the requested user",
           all(v["owner"] == "tester" for v in views.values()), str(sorted(views)))

    # CheckMK overwrites each visual's "name" with its dictionary key, then
    # sorts visuals by name. A tuple key lands a tuple in that field.
    expect("views are keyed by a bare string name, not an (owner, name) tuple",
           all(isinstance(k, str) for k in views), str([type(k).__name__ for k in views]))
    expect("each view's key matches its own name field",
           all(k == v["name"] for k, v in views.items()),
           str([(k, v["name"]) for k, v in views.items()]))
    expect("the built views are exactly the owned views",
           set(views) == set(OWNED_VIEWS), str(sorted(views)))

    problems = views[VIEW_PROBLEMS]
    expect("the problems view excludes OK services",
           problems["context"]["svcstate"]["st0"] == ""
           and problems["context"]["svcstate"]["st2"] == "on",
           str(problems["context"].get("svcstate")))
    expect("the problems view keeps WARNING, CRITICAL and UNKNOWN",
           all(problems["context"]["svcstate"]["st%d" % s] == "on" for s in (1, 2, 3)),
           str(problems["context"].get("svcstate")))

    expect("the all-services view does not filter by state",
           "svcstate" not in views[VIEW_ALL]["context"], str(views[VIEW_ALL]["context"]))
    expect("the firewall view does not filter by state",
           "svcstate" not in views[VIEW_FIREWALL]["context"],
           str(views[VIEW_FIREWALL]["context"]))
    expect("views select services by regex, with no host list to maintain",
           all("host" not in v["context"] for v in views.values()),
           str([v["context"] for v in views.values()]))

    expect("views store painters as dicts, the 2.5 schema",
           all(isinstance(p, dict) and "name" in p
               for v in views.values() for p in v["painters"]),
           str(views[VIEW_ALL]["painters"][:1]))

    # A SorterSpec takes at most three positional values.
    all_sorters = [s for v in views.values() for s in v["sorters"]]
    expect("sorters are 3-tuples, what SorterSpec accepts",
           all_sorters and all(isinstance(s, tuple) and len(s) == 3 for s in all_sorters),
           str(all_sorters[:2]))
    expect("sorters carry a plain name, a bool and a join key",
           all(isinstance(s[0], str) and isinstance(s[1], bool) and s[2] is None
               for s in all_sorters),
           str(all_sorters[:2]))

    # Regex validity: a bad pattern would silently select nothing.
    regex_ok = True
    for pattern in (NETWORK_REGEX, FIREWALL_REGEX, LISTENERS_REGEX):
        try:
            _re.compile(pattern)
        except _re.error:
            regex_ok = False
    expect("every service regex compiles", regex_ok,
           str((NETWORK_REGEX, FIREWALL_REGEX, LISTENERS_REGEX)))

    rx_network = _re.compile(NETWORK_REGEX)
    rx_firewall = _re.compile(FIREWALL_REGEX)
    rx_listeners = _re.compile(LISTENERS_REGEX)

    expect("the network regex matches every emitted service",
           all(rx_network.match(s) for s in emitted),
           str([s for s in emitted if not rx_network.match(s)]))
    expect("the network regex matches each Twingate resource service",
           bool(rx_network.match("Twingate.Resource.NS"))
           and bool(rx_network.match("Twingate.Resource.Office_VPC")),
           "")
    expect("the network regex leaves unrelated services alone",
           not any(rx_network.match(s) for s in unrelated),
           str([s for s in unrelated if rx_network.match(s)]))
    expect("the firewall regex matches Network.Firewall only",
           rx_firewall.match("Network.Firewall")
           and not rx_firewall.match("Network.Exposure")
           and not rx_firewall.match("Network.Listeners"),
           FIREWALL_REGEX)
    expect("the firewall regex rejects a longer name",
           not rx_firewall.match("Network.FirewallX"), FIREWALL_REGEX)
    expect("the listeners regex matches Network.Exposure and Network.Listeners",
           rx_listeners.match("Network.Exposure") and rx_listeners.match("Network.Listeners"),
           LISTENERS_REGEX)
    expect("the listeners regex excludes the firewall and Twingate services",
           not rx_listeners.match("Network.Firewall")
           and not rx_listeners.match("Twingate.Client")
           and not rx_listeners.match("Twingate.Resource.NS"),
           LISTENERS_REGEX)
    expect("the listeners regex is anchored, so a longer name is not matched",
           not rx_listeners.match("Network.ExposureX"), LISTENERS_REGEX)

    expect("the all-services view matches every emitted service",
           all(rx_network.match(s) for s in emitted), NETWORK_REGEX)

    dash = build_dashboard("tester")
    expect("dashboard is keyed by a plain name, like the site's own dashboards",
           list(dash) == [DASHBOARD_ID], str(list(dash)))
    board = dash[DASHBOARD_ID]
    expect("dashboard id is network_exposure",
           DASHBOARD_ID == "network_exposure", DASHBOARD_ID)
    expect("dashboard title is Network exposure (DE.CM-01)",
           board["title"] == "Network exposure (DE.CM-01)", board["title"])
    expect("dashboard uses the 2.5 widgets schema, not dashlets",
           "widgets" in board and "dashlets" not in board, str(sorted(board)))
    expect("dashboard embeds three widgets", len(board["widgets"]) == 3,
           str(sorted(board["widgets"])))
    expect("every widget resolves to an embedded view",
           all(w["name"] in board["embedded_views"] for w in board["widgets"].values()),
           str([w["name"] for w in board["widgets"].values()]))
    expect("embedded view keys are strings, never tuples",
           all(isinstance(k, str) for k in board["embedded_views"]),
           str(sorted(board["embedded_views"])))
    expect("the two lower widgets sit side by side",
           board["widgets"]["widget_listeners"]["position"][0] == 1
           and board["widgets"]["widget_firewall"]["position"][0] == 51,
           str([(k, w["position"]) for k, w in board["widgets"].items()]))
    expect("widget positions and sizes are tuples",
           all(isinstance(w["position"], tuple) and isinstance(w["size"], tuple)
               for w in board["widgets"].values()), "")

    # The filters belong on the widget. An empty widget context shows every
    # service on the site.
    expect("every widget carries its own service filter",
           all(w["context"].get("serviceregex", {}).get("service_regex")
               for w in board["widgets"].values()),
           str([(k, w["context"]) for k, w in board["widgets"].items()]))
    expect("no widget is left with an empty context",
           all(w["context"] for w in board["widgets"].values()),
           str([(k, bool(w["context"])) for k, w in board["widgets"].items()]))
    expect("embedded views hold only rendering keys, no filters",
           all("context" not in v for v in board["embedded_views"].values()),
           str([sorted(v) for v in board["embedded_views"].values()][:1]))
    expect("the problems widget filters out OK services",
           board["widgets"]["widget_problems"]["context"]["svcstate"]["st0"] == "",
           str(board["widgets"]["widget_problems"]["context"].get("svcstate")))
    expect("the problems widget uses the network regex",
           board["widgets"]["widget_problems"]["context"]["serviceregex"]["service_regex"]
           == NETWORK_REGEX,
           str(board["widgets"]["widget_problems"]["context"]["serviceregex"]))
    expect("the listeners widget uses the listeners regex",
           board["widgets"]["widget_listeners"]["context"]["serviceregex"]["service_regex"]
           == LISTENERS_REGEX,
           str(board["widgets"]["widget_listeners"]["context"]["serviceregex"]))
    expect("the firewall widget uses the firewall regex",
           board["widgets"]["widget_firewall"]["context"]["serviceregex"]["service_regex"]
           == FIREWALL_REGEX,
           str(board["widgets"]["widget_firewall"]["context"]["serviceregex"]))

    print("\n%d/%d passed" % (ran - failures, ran))
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
    new_dash = build_dashboard(user)

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
        print("  would add/replace dashboard: %s" % DASHBOARD_ID)
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
    print("  dashboard %s" % DASHBOARD_ID)
    print("\n%d pre-existing views and %d pre-existing dashboards were left untouched."
          % (len(kept), len(kept_dash)))
    print("Visuals cache invalidated (%s), so the GUI rereads these definitions."
          % (", ".join(dropped) if dropped else "nothing to drop"))
    print("Open it from the dashboard list: Network exposure (DE.CM-01).")
    print("If the GUI does not show it yet, the site caches the profile: "
          "log out and back in, or restart apache with 'omd restart apache'.")
    return 0


parser = argparse.ArgumentParser(
    description="Install the network exposure views and dashboard into a CheckMK site."
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
