#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Install the NIS compliance views and dashboard into a CheckMK site.
#
# The compliance checks (OS.Lifecycle, Patch.Posture, NS8.Modules.*) are
# scattered among hundreds of ordinary services on every host, so reading them
# as a compliance posture means filtering them out by hand every time. This
# script installs one dashboard and three supporting views that select those
# services by name across every monitored host, with no host list to maintain:
# a new host appears as soon as it reports one of these services.
#
# Run this ON the CheckMK server, as the site user:
#   omd su <site>
#   python3 install-compliance-dashboard.py
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

# Service name prefixes that make up the compliance posture. Kept as a regex
# alternation because CheckMK filters services by regex, not by tag.
SERVICE_REGEX = "^(OS\\.Lifecycle|Patch\\.Posture|NS8\\.Modules\\.)"
LIFECYCLE_REGEX = "^(OS\\.Lifecycle|NS8\\.Modules\\.Lifecycle)"
UPDATES_REGEX = "^(Patch\\.Posture|NS8\\.Modules\\.Updates)"

# The problems panel lists what somebody has to act on, so it leaves out the
# NS8.Modules.Lifecycle roll-up: that service only restates what its
# per-component services already say, and showing both made the same
# end-of-life component appear twice. The roll-up stays in the lifecycle
# panel, where a single per-host verdict is what you want.
PROBLEMS_REGEX = (
    "^(OS\\.Lifecycle|Patch\\.Posture|NS8\\.Modules\\.Updates|NS8\\.Modules\\.Lifecycle\\.)"
)

VIEW_ALL = "nis_compliance_all"
VIEW_PROBLEMS = "nis_compliance_problems"
VIEW_LIFECYCLE = "nis_compliance_lifecycle"
VIEW_UPDATES = "nis_compliance_updates"
DASHBOARD_ID = "nis_compliance"

OWNED_VIEWS = (VIEW_ALL, VIEW_PROBLEMS, VIEW_LIFECYCLE, VIEW_UPDATES)


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
        user, VIEW_PROBLEMS,
        "NIS compliance problems",
        "Compliance services not OK, every host: lifecycle, patch posture and "
        "NS8 module services in WARNING, CRITICAL or UNKNOWN. The "
        "NS8.Modules.Lifecycle roll-up is left out so a component is not "
        "listed twice alongside its own service.",
        PROBLEMS_REGEX,
        states=[1, 2, 3],
    ))
    views.update(service_view(
        user, VIEW_ALL,
        "NIS compliance - all services",
        "Every compliance service on every host, whatever its state.",
        SERVICE_REGEX,
    ))
    views.update(service_view(
        user, VIEW_LIFECYCLE,
        "NIS compliance - lifecycle (PR.PS-02.1)",
        "Operating system and inner container component lifecycle: what is "
        "still receiving security updates and what is not.",
        LIFECYCLE_REGEX,
    ))
    views.update(service_view(
        user, VIEW_UPDATES,
        "NIS compliance - patch posture (PR.PS-02.2)",
        "Pending security updates and NS8 module updates, with how long they "
        "have been waiting.",
        UPDATES_REGEX,
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
         "Compliance problems - every host",
         PROBLEMS_REGEX, [1, 2, 3], 1, 1, 0, 34),
        ("widget_lifecycle", "dashlet_1", VIEW_LIFECYCLE,
         "Lifecycle - PR.PS-02.1",
         LIFECYCLE_REGEX, None, 1, 35, 50, 0),
        ("widget_updates", "dashlet_2", VIEW_UPDATES,
         "Patch posture - PR.PS-02.2",
         UPDATES_REGEX, None, 51, 35, 0, 0),
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
            "title": "NIS compliance",
            "description": "Continuous compliance posture across every monitored "
                           "host: OS lifecycle, patch posture, and NS8 module and "
                           "container component lifecycle. Problems first, then the "
                           "two control families side by side.",
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
    failures = 0

    def expect(name, cond, detail=""):
        nonlocal failures
        if not cond:
            failures += 1
        print("%s  %s" % ("PASS" if cond else "FAIL", name))
        if not cond and detail:
            print("      %s" % detail)

    views = build_views("tester")
    expect("builds one view per compliance angle", len(views) == 4, str(sorted(views)))
    expect("every view is owned by the requested user",
           all(v["owner"] == "tester" for v in views.values()), str(sorted(views)))

    # CheckMK overwrites each visual's "name" with its dictionary key, then
    # sorts visuals by name. A tuple key lands a tuple in that field and every
    # view page dies with "'<' not supported between instances of 'str' and
    # 'tuple'" - the whole GUI, not only these views.
    expect("views are keyed by a bare string name, not an (owner, name) tuple",
           all(isinstance(k, str) for k in views), str([type(k).__name__ for k in views]))
    expect("each view's key matches its own name field",
           all(k == v["name"] for k, v in views.items()),
           str([(k, v["name"]) for k, v in views.items()]))

    problems = views[VIEW_PROBLEMS]
    expect("the problems view excludes OK services",
           problems["context"]["svcstate"]["st0"] == ""
           and problems["context"]["svcstate"]["st2"] == "on",
           str(problems["context"]["svcstate"]))

    all_view = views[VIEW_ALL]
    expect("the all-services view does not filter by state",
           "svcstate" not in all_view["context"], str(all_view["context"]))

    expect("views select services by regex, with no host list to maintain",
           all("host" not in v["context"] for v in views.values()),
           str([v["context"] for v in views.values()]))

    import re as _re
    rx = _re.compile(SERVICE_REGEX)
    for svc in ("OS.Lifecycle", "Patch.Posture", "NS8.Modules.Updates",
                "NS8.Modules.Lifecycle", "NS8.Modules.Lifecycle.nethvoice1.redis"):
        expect("regex matches %s" % svc, bool(rx.match(svc)), svc)
    for svc in ("NS8.Containers", "CPU load", "Filesystem /"):
        expect("regex leaves %s alone" % svc, not rx.match(svc), svc)

    lrx = _re.compile(LIFECYCLE_REGEX)
    expect("lifecycle view takes OS.Lifecycle and the component services",
           lrx.match("OS.Lifecycle") and lrx.match("NS8.Modules.Lifecycle.mail1.dovecot")
           and not lrx.match("Patch.Posture"), LIFECYCLE_REGEX)

    urx = _re.compile(UPDATES_REGEX)
    expect("patch view takes Patch.Posture and NS8.Modules.Updates",
           urx.match("Patch.Posture") and urx.match("NS8.Modules.Updates")
           and not urx.match("OS.Lifecycle"), UPDATES_REGEX)

    # The roll-up restates its own per-component services, so listing both in
    # the problems panel showed the same end-of-life component twice.
    prx = _re.compile(PROBLEMS_REGEX)
    expect("problems panel skips the NS8.Modules.Lifecycle roll-up",
           not prx.match("NS8.Modules.Lifecycle"), PROBLEMS_REGEX)
    expect("problems panel still takes the per-component services",
           bool(prx.match("NS8.Modules.Lifecycle.nethvoice1.redis"))
           and bool(prx.match("NS8.Modules.Lifecycle.mattermost1.mattermost-team-edition")),
           PROBLEMS_REGEX)
    expect("problems panel keeps the other compliance services",
           all(prx.match(s) for s in ("OS.Lifecycle", "Patch.Posture", "NS8.Modules.Updates")),
           PROBLEMS_REGEX)
    expect("the lifecycle panel still shows the roll-up",
           bool(lrx.match("NS8.Modules.Lifecycle")), LIFECYCLE_REGEX)

    expect("views store painters as dicts, the 2.5 schema",
           all(isinstance(p, dict) and "name" in p
               for v in views.values() for p in v["painters"]),
           str(all_view["painters"][:1]))

    # A SorterSpec takes at most three positional values. A four-element tuple
    # or a dict makes every page using the view raise an internal error, which
    # is what happened the first time this was installed.
    all_sorters = [s for v in views.values() for s in v["sorters"]]
    expect("sorters are 3-tuples, what SorterSpec accepts",
           all_sorters and all(isinstance(s, tuple) and len(s) == 3 for s in all_sorters),
           str(all_sorters[:2]))
    expect("sorters carry a plain name, a bool and a join key",
           all(isinstance(s[0], str) and isinstance(s[1], bool) and s[2] is None
               for s in all_sorters),
           str(all_sorters[:2]))

    dash = build_dashboard("tester")
    expect("dashboard is keyed by a plain name, like the site's own dashboards",
           list(dash) == [DASHBOARD_ID], str(list(dash)))
    board = dash[DASHBOARD_ID]
    expect("dashboard uses the 2.5 widgets schema, not dashlets",
           "widgets" in board and "dashlets" not in board, str(sorted(board)))
    expect("dashboard embeds three widgets", len(board["widgets"]) == 3,
           str(sorted(board["widgets"])))
    expect("every widget resolves to an embedded view",
           all(w["name"] in board["embedded_views"] for w in board["widgets"].values()),
           str([w["name"] for w in board["widgets"].values()]))
    expect("the two lower widgets sit side by side",
           board["widgets"]["widget_lifecycle"]["position"][0] == 1
           and board["widgets"]["widget_updates"]["position"][0] == 51,
           str([(k, w["position"]) for k, w in board["widgets"].items()]))

    # The filters belong on the widget. With an empty widget context the
    # dashboard showed every service on the site, not just the compliance ones.
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
    expect("each widget filters on the regex of its own control family",
           board["widgets"]["widget_lifecycle"]["context"]["serviceregex"]["service_regex"]
           == LIFECYCLE_REGEX
           and board["widgets"]["widget_updates"]["context"]["serviceregex"]["service_regex"]
           == UPDATES_REGEX,
           str([(k, w["context"]["serviceregex"]["service_regex"])
                for k, w in board["widgets"].items()]))
    expect("the problems widget uses the roll-up-free regex",
           board["widgets"]["widget_problems"]["context"]["serviceregex"]["service_regex"]
           == PROBLEMS_REGEX,
           board["widgets"]["widget_problems"]["context"]["serviceregex"]["service_regex"])

    total = 36
    print("\n%d/%d passed" % (total - failures, total))
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
    print("Open it from Monitor -> Applications -> NIS compliance.")
    print("If the GUI does not show it yet, the site caches the profile: "
          "log out and back in, or restart apache with 'omd restart apache'.")
    return 0


parser = argparse.ArgumentParser(
    description="Install the NIS compliance views and dashboard into a CheckMK site."
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
