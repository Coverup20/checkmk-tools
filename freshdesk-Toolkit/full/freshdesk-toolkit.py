#!/usr/bin/python3
"""
freshdesk-toolkit - read-only Freshdesk CLI for ticket research and statistics

Built for looking at a helpdesk, not for running it: list, read and search
tickets, inspect the field catalogue, count matches server-side, pull a bulk
dataset and aggregate it offline. `find` searches the exported dataset by free
text, because the search endpoint only accepts structured filters. `guard`
checks the env file, the credentials and the dataset before a session starts.

Read-only by construction. There is no create, comment, update, close or
delete command, and the generic api command refuses any method other than GET,
so this tool cannot change a ticket even by accident.

Credentials come from an env file (default /opt/freshdesk-toolkit/.env), which
must define FRESHDESK_DOMAIN and FRESHDESK_API_KEY.

Version: 1.1.0
"""
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "1.1.0"

ENV_FILE = os.environ.get("FRESHDESK_ENV", "/opt/freshdesk-toolkit/.env")
HTTP_TIMEOUT = int(os.environ.get("FRESHDESK_TIMEOUT", "30"))

# Where 'export' writes its dataset and where 'stats' reads it back from.
CACHE_FILE = os.environ.get("FRESHDESK_CACHE_FILE",
                            "/opt/freshdesk-toolkit/cache/tickets.jsonl")

# Set by --json: print raw objects so the output can be piped to jq.
JSON_OUT = False

# Freshdesk code tables, needed to make a listing readable.
STATUS_NAMES = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
PRIORITY_NAMES = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}

## Useful


def fail(message, code=2):
    """Print an error and stop."""
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(code)


def load_env(path):
    """Load KEY=VALUE lines from an env file into the process environment.

    Accepts the 'export KEY=value' form and quoted values. Values already
    present in the environment win, so a caller can override the file without
    editing it.
    """
    if not os.path.exists(path):
        return
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                line = line.replace("export ", "", 1).strip()
                key, value = line.split("=", 1)
                key = key.strip()
                if key not in os.environ:
                    os.environ[key] = value.strip().strip('"').strip("'")
    except Exception as e:
        print(f"WARNING: could not read {path}: {e}", file=sys.stderr)


def take_option(argv, name, default=None):
    """Remove '--name value' from argv, returning the value or a default."""
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            fail(f"{name} needs a value")
        value = argv[i + 1]
        del argv[i:i + 2]
        return value
    return default


def api_get(path):
    """Perform a GET against the Freshdesk API and return the decoded body."""
    domain = os.environ.get("FRESHDESK_DOMAIN", "")
    api_key = os.environ.get("FRESHDESK_API_KEY", "")
    if not domain or not api_key:
        fail("FRESHDESK_DOMAIN and FRESHDESK_API_KEY must be set "
             f"(env file: {ENV_FILE})")

    url = f"https://{domain}/api/v2{path}"
    token = base64.b64encode(f"{api_key}:X".encode("utf-8")).decode("ascii")

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("User-Agent", "freshdesk-toolkit")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        fail(f"HTTP {e.code} on {path}: {raw[:400]}", code=1)
    except Exception as e:
        fail(f"request to {path} failed: {e}", code=1)


def group_names():
    """Return {group_id: name}, read from the ticket field catalogue.

    The groups endpoint needs administrator rights, but ticket_fields exposes
    the same name-to-id mapping to any agent account.
    """
    for field in api_get("/ticket_fields") or []:
        if field.get("name") == "group":
            return {v: k for k, v in (field.get("choices") or {}).items()}
    return {}


def format_ticket_line(ticket, groups):
    """Render one ticket as a single readable line."""
    status = STATUS_NAMES.get(ticket.get("status"), ticket.get("status"))
    priority = PRIORITY_NAMES.get(ticket.get("priority"), ticket.get("priority"))
    group = groups.get(ticket.get("group_id"), ticket.get("group_id") or "-")
    deleted = " [DELETED]" if ticket.get("deleted") else ""
    spam = " [SPAM]" if ticket.get("spam") else ""
    return (f"#{ticket.get('id')}  {status:<9} {priority:<7} {str(group):<14} "
            f"{ticket.get('subject', '')[:70]}{deleted}{spam}")


## Read commands


def cmd_list(args):
    """List recent tickets, most recent first."""
    limit = int(args[0]) if args else 30
    query = urllib.parse.urlencode({
        "per_page": min(limit, 100),
        "order_by": "created_at",
        "order_type": "desc",
    })
    tickets = (api_get(f"/tickets?{query}") or [])[:limit]
    if JSON_OUT:
        print(json.dumps(tickets, indent=2, ensure_ascii=False))
        return
    groups = group_names()
    for ticket in tickets:
        print(format_ticket_line(ticket, groups))
    print(f"\n{len(tickets)} ticket(s)")


def cmd_get(args):
    """Show one ticket in full, with its conversations."""
    if not args:
        fail("usage: freshdesk-toolkit.py get <ticket_id>")
    ticket_id = args[0]
    ticket = api_get(f"/tickets/{ticket_id}")
    conversations = api_get(f"/tickets/{ticket_id}/conversations") or []
    if JSON_OUT:
        print(json.dumps({"ticket": ticket, "conversations": conversations},
                         indent=2, ensure_ascii=False))
        return
    groups = group_names()

    print(f"#{ticket.get('id')}  {ticket.get('subject', '')}")
    print(f"  status      {STATUS_NAMES.get(ticket.get('status'), ticket.get('status'))}")
    print(f"  priority    {PRIORITY_NAMES.get(ticket.get('priority'), ticket.get('priority'))}")
    print(f"  group       {groups.get(ticket.get('group_id'), ticket.get('group_id'))}")
    print(f"  type        {ticket.get('type')}")
    print(f"  deleted     {bool(ticket.get('deleted'))}")
    print(f"  spam        {bool(ticket.get('spam'))}")
    print(f"  created     {ticket.get('created_at')}")
    print(f"  updated     {ticket.get('updated_at')}")
    for key, value in (ticket.get("custom_fields") or {}).items():
        if value is not None:
            print(f"  cf.{key:<9} {value}")
    print(f"\n{ticket.get('description_text', '').strip()}")

    for conv in conversations:
        kind = "private note" if conv.get("private") else "public reply"
        print(f"\n--- {kind}, {conv.get('created_at')}")
        print(conv.get("body_text", "").strip())


def cmd_search(args):
    """Find tickets, either by subject locally or with a server-side query.

    Without --query the term is matched client-side against the subjects of the
    most recent pages: predictable, but it only sees those pages. With --query
    the filter goes to the search endpoint in its native keyword:value syntax,
    so it reaches the whole history:  search --query "subject:'SIP'"
    """
    server_query = take_option(args, "--query", None)
    if server_query is not None:
        if ":" not in server_query:
            fail("--query needs the server syntax keyword:value, for example:\n"
                 "  search --query \"status:2 AND group_id:73604\"\n"
                 "  search --query \"cf_tipo_intervento:'remoto'\"\n"
                 "For free text over the whole history use 'find' instead:\n"
                 "  export --since 2026-01-01   then   find \"SIP\"")
        query = urllib.parse.urlencode({"query": f'"{server_query}"'})
        result = api_get(f"/search/tickets?{query}") or {}
        tickets = result.get("results") or []
        if JSON_OUT:
            print(json.dumps(tickets, indent=2, ensure_ascii=False))
            return
        groups = group_names()
        for ticket in tickets:
            print(format_ticket_line(ticket, groups))
        print(f"\n{len(tickets)} shown, {result.get('total', len(tickets))} match(es) on the server")
        return

    if not args:
        fail("usage: freshdesk-toolkit.py search <term> [pages]\n"
             "       freshdesk-toolkit.py search --query \"subject:'SIP'\"")
    term = args[0]
    pages = int(args[1]) if len(args) > 1 else 3

    matches = []
    lowered = term.lower()
    for page in range(1, pages + 1):
        query = urllib.parse.urlencode({
            "per_page": 100,
            "page": page,
            "order_by": "created_at",
            "order_type": "desc",
        })
        tickets = api_get(f"/tickets?{query}") or []
        if not tickets:
            break
        for ticket in tickets:
            if lowered in (ticket.get("subject", "") or "").lower():
                matches.append(ticket)
    if JSON_OUT:
        print(json.dumps(matches, indent=2, ensure_ascii=False))
        return
    groups = group_names()
    for ticket in matches:
        print(format_ticket_line(ticket, groups))
    print(f"\n{len(matches)} match(es) over {pages} page(s)")


def cmd_find(args):
    """Free-text search in the exported dataset: the whole history, offline.

    The search endpoint only accepts structured filters (keyword:value), so free
    text is matched here over subject, structured description, tags and custom
    fields of the dataset 'export' writes. Groups show as ids on purpose: this
    command does not touch the network.
    """
    if not args:
        fail("usage: freshdesk-toolkit.py find <term> [--file <path>] [--limit <n>]")
    term = args[0]
    path = take_option(args, "--file", CACHE_FILE)
    limit = int(take_option(args, "--limit", "50"))

    tickets = read_export(path)
    lowered = term.lower()
    hits = []
    for ticket in tickets:
        fields = [str(ticket.get("subject") or ""), str(ticket.get("structured_description") or "")]
        fields += [str(value) for value in (ticket.get("tags") or [])]
        fields += [str(value) for value in (ticket.get("custom_fields") or {}).values() if value]
        if lowered in " ".join(fields).lower():
            hits.append(ticket)

    if JSON_OUT:
        print(json.dumps(hits[:limit], indent=2, ensure_ascii=False))
        return
    newest = max((ticket.get("updated_at") or "" for ticket in tickets), default="")
    stale = ""
    if newest:
        try:
            refreshed = datetime.strptime(newest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - refreshed).days
            if age > 7:
                stale = "  WARNING: %d days old, run 'export --since <date>' to refresh" % age
        except ValueError:
            pass
    print("%d of %d ticket(s) contain %r (dataset %s, newest %s)%s"
          % (len(hits), len(tickets), term, path, newest or "-", stale))
    for ticket in hits[:limit]:
        print(format_ticket_line(ticket, {}))
    if len(hits) > limit:
        print("... %d more, raise --limit" % (len(hits) - limit))


def cmd_groups(_args):
    """Show the group name to id mapping."""
    for group_id, name in sorted(group_names().items(), key=lambda kv: kv[1]):
        print(f"{group_id:<14} {name}")


def cmd_fields(_args):
    """Show every ticket field and, where present, its allowed values."""
    for field in api_get("/ticket_fields") or []:
        required = " (required for agents)" if field.get("required_for_agents") else ""
        print(f"{field.get('name')}{required}")
        choices = field.get("choices")
        if isinstance(choices, (dict, list)):
            for key in choices:
                print(f"    {key}")


def cmd_whoami(_args):
    """Show the agent the API key belongs to."""
    me = api_get("/agents/me") or {}
    contact = me.get("contact", {})
    print(f"agent id    {me.get('id')}")
    print(f"name        {contact.get('name')}")
    print(f"email       {contact.get('email')}")
    print(f"group ids   {me.get('group_ids')}")


def cmd_api(args):
    """Call any read endpoint directly, for what the commands above do not cover.

    GET only: this tool does not write, so any other method is refused here
    rather than passed through.
    """
    if not args:
        fail("usage: freshdesk-toolkit.py api <path>   (GET only)")

    path = args[0]
    # Tolerate an explicit leading GET, so a copied example still works.
    if path.upper() == "GET" and len(args) > 1:
        path = args[1]
    elif path.upper() in ("POST", "PUT", "DELETE", "PATCH"):
        fail(f"{path.upper()} is not available: this toolkit is read-only")

    if not path.startswith("/"):
        path = "/" + path
    print(json.dumps(api_get(path), indent=2, ensure_ascii=False))


## Statistics


def cmd_count(args):
    """Count tickets matching a server-side search query.

    The search endpoint only returns 30 results per page, but it reports the
    full total, which is all a count needs. Examples:
      count "group_id:123"
      count "created_at:>'2026-10-01'"
      count "status:2 AND priority:4"
    """
    if not args:
        fail("usage: freshdesk-toolkit.py count '<query>'\n"
             "  examples: \"group_id:123\", \"created_at:>'2026-10-01'\", "
             "\"status:2 AND priority:4\"")
    query = urllib.parse.urlencode({"query": f'"{args[0]}"'})
    result = api_get(f"/search/tickets?{query}") or {}
    if JSON_OUT:
        print(json.dumps({"query": args[0], "total": result.get("total", 0)}, indent=2))
        return
    print(f"{result.get('total', 0)} ticket(s) match {args[0]}")


def cmd_export(args):
    """Pull tickets in bulk to a local file, for offline statistics.

    Uses updated_since pagination rather than the search endpoint: it returns
    100 tickets per page instead of 30 and keeps paging far further, which is
    what makes a historical dataset practical to build. One JSON object per
    line, so a partial export is still usable.
    """
    since = take_option(args, "--since", "2026-01-01")
    out = take_option(args, "--out", CACHE_FILE)
    max_pages = int(take_option(args, "--max-pages", "200"))

    if "T" not in since:
        since = f"{since}T00:00:00Z"

    # The dataset holds real customer ticket text, so it must not be
    # world-readable: restrict both the directory and the file.
    out_dir = os.path.dirname(out) or "."
    os.makedirs(out_dir, exist_ok=True)
    os.chmod(out_dir, 0o700)

    total = 0
    with open(out, "w", encoding="utf-8") as f:
        os.chmod(out, 0o600)
        for page in range(1, max_pages + 1):
            query = urllib.parse.urlencode({
                "updated_since": since,
                "per_page": 100,
                "page": page,
            })
            tickets = api_get(f"/tickets?{query}") or []
            if not tickets:
                break
            for ticket in tickets:
                f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
            total += len(tickets)
            print(f"  page {page:<4} {len(tickets):>3} ticket(s), {total} so far",
                  file=sys.stderr)
            if len(tickets) < 100:
                break

    print(f"{total} ticket(s) written to {out}")


def read_export(path):
    """Load an exported dataset, one JSON object per line."""
    if not os.path.exists(path):
        fail(f"no dataset at {path} - run 'export' first, or pass --file")
    tickets = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    tickets.append(json.loads(line))
                except ValueError:
                    continue
    return tickets


def ticket_dimension(ticket, by, groups):
    """Return the value of one grouping dimension for a ticket."""
    if by == "group":
        return groups.get(ticket.get("group_id"), ticket.get("group_id") or "-")
    if by == "status":
        return STATUS_NAMES.get(ticket.get("status"), ticket.get("status"))
    if by == "priority":
        return PRIORITY_NAMES.get(ticket.get("priority"), ticket.get("priority"))
    if by == "type":
        return ticket.get("type") or "-"
    if by == "month":
        return (ticket.get("created_at") or "")[:7] or "-"
    if by == "day":
        return (ticket.get("created_at") or "")[:10] or "-"
    if by.startswith("cf."):
        return (ticket.get("custom_fields") or {}).get(by[3:]) or "-"
    fail(f"unknown dimension {by}")


def cmd_stats(args):
    """Aggregate an exported dataset along one or more dimensions.

    Examples:
      stats --by group
      stats --by month --since 2026-06-01
      stats --by cf.tipo_intervento --group-id 123
    """
    path = take_option(args, "--file", CACHE_FILE)
    dimensions = take_option(args, "--by", "group").split(",")
    since = take_option(args, "--since", "")
    until = take_option(args, "--until", "")
    group_id = take_option(args, "--group-id", "")
    top = int(take_option(args, "--top", "0"))

    tickets = read_export(path)
    selected = []
    for ticket in tickets:
        created = (ticket.get("created_at") or "")[:10]
        if since and created < since:
            continue
        if until and created > until:
            continue
        if group_id and str(ticket.get("group_id")) != str(group_id):
            continue
        selected.append(ticket)

    window = []
    if since:
        window.append(f"from {since}")
    if until:
        window.append(f"to {until}")
    if group_id:
        window.append(f"group {group_id}")
    scope = f" ({', '.join(window)})" if window else ""
    print(f"{len(selected)} of {len(tickets)} ticket(s){scope}, dataset {path}")

    groups = group_names()
    for by in dimensions:
        by = by.strip()
        counts = {}
        for ticket in selected:
            key = ticket_dimension(ticket, by, groups)
            counts[key] = counts.get(key, 0) + 1

        print(f"\nby {by}")
        # Chronological dimensions read better in order; everything else is
        # more useful ranked by size.
        if by in ("month", "day"):
            rows = sorted(counts.items())
        else:
            rows = sorted(counts.items(), key=lambda kv: -kv[1])
        if top:
            rows = rows[:top]
        width = max((len(str(k)) for k, _ in rows), default=10)
        for key, count in rows:
            share = 100.0 * count / len(selected) if selected else 0
            bar = "#" * int(share / 2)
            print(f"  {str(key):<{width}}  {count:>5}  {share:5.1f}%  {bar}")


## Health


def cmd_guard(_args):
    """Validate configuration, credentials and the local dataset."""
    present = os.path.exists(ENV_FILE)
    report = {
        "env_file": ENV_FILE,
        "env_present": present,
        "env_mode": oct(os.stat(ENV_FILE).st_mode & 0o777) if present else "",
        "domain": os.environ.get("FRESHDESK_DOMAIN", ""),
        "api_key": bool(os.environ.get("FRESHDESK_API_KEY")),
        "whoami": "",
        "groups": 0,
        "dataset": "",
        "dataset_tickets": 0,
        "error": "",
    }
    ok = False
    if report["domain"] and report["api_key"]:
        try:
            me = api_get("/agents/me") or {}
            report["whoami"] = (me.get("contact") or {}).get("email") or ""
            report["groups"] = len(group_names())
            ok = True
        except SystemExit:
            # api_get already printed the HTTP error; keep the report together.
            report["error"] = "credentials rejected, see the ERROR line above"
    else:
        report["error"] = "FRESHDESK_DOMAIN or FRESHDESK_API_KEY missing"

    if os.path.exists(CACHE_FILE):
        report["dataset"] = CACHE_FILE
        try:
            report["dataset_tickets"] = len(read_export(CACHE_FILE))
        except SystemExit:
            report["dataset_tickets"] = -1

    if JSON_OUT:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if ok else 1

    rows = [
        ("env file", "%s%s" % (report["env_file"],
                               " (%s)" % report["env_mode"] if report["env_mode"] else " (missing)")),
        ("domain", report["domain"] or "-"),
        ("api key", "set" if report["api_key"] else "MISSING"),
        ("authenticated as", report["whoami"] or "-"),
        ("groups", str(report["groups"])),
        ("dataset", "%s (%d tickets)" % (report["dataset"], report["dataset_tickets"])
         if report["dataset"] else "not exported"),
    ]
    if report["error"]:
        rows.append(("error", report["error"]))
    width = max(len(str(key)) for key, _ in rows)
    for key, value in rows:
        print("%-*s  %s" % (width, key, value))
    return 0 if ok else 1


def self_test():
    """Offline assertions. No network, no credentials."""
    failures = []
    checks = []

    def expect(name, got, want):
        checks.append(name)
        if got != want:
            failures.append("%s: got %r, want %r" % (name, got, want))

    ticket = {"id": 4321, "status": 2, "priority": 4, "group_id": 77,
              "subject": "Server irraggiungibile", "deleted": False, "spam": False}
    line = format_ticket_line(ticket, {77: "Infrastruttura"})
    expect("line has id", "#4321" in line, True)
    expect("line maps status", "Open" in line, True)
    expect("line maps priority", "Urgent" in line, True)
    expect("line maps group", "Infrastruttura" in line, True)

    deleted = dict(ticket, deleted=True)
    expect("line marks deleted", "[DELETED]" in format_ticket_line(deleted, {}), True)

    expect("dimension group", ticket_dimension(ticket, "group", {77: "Infra"}), "Infra")
    expect("dimension status", ticket_dimension(ticket, "status", {}), "Open")
    expect("dimension priority", ticket_dimension(ticket, "priority", {}), "Urgent")
    expect("dimension month", ticket_dimension(dict(ticket, created_at="2026-11-26T10:00:00Z"),
                                               "month", {}), "2026-11")
    expect("dimension cf", ticket_dimension({"custom_fields": {"tipo_intervento": "remoto"}},
                                            "cf.tipo_intervento", {}), "remoto")
    expect("dimension fallback", ticket_dimension({}, "type", {}), "-")

    options = ["--since", "2026-01-01", "--out", "/tmp/x"]
    expect("take_option value", take_option(options, "--since"), "2026-01-01")
    expect("take_option removes pair", options, ["--out", "/tmp/x"])
    expect("take_option default", take_option(options, "--top", "0"), "0")

    expect("status table", STATUS_NAMES[5], "Closed")
    expect("priority table", PRIORITY_NAMES[1], "Low")

    print("Self-test: %d/%d passed" % (len(checks) - len(failures), len(checks)))
    for failure in failures:
        print("  FAIL %s" % failure)
    return 0 if not failures else 1


COMMANDS = {
    "list": cmd_list,
    "get": cmd_get,
    "search": cmd_search,
    "groups": cmd_groups,
    "fields": cmd_fields,
    "whoami": cmd_whoami,
    "api": cmd_api,
    "count": cmd_count,
    "export": cmd_export,
    "stats": cmd_stats,
    "find": cmd_find,
    "guard": cmd_guard,
}


def usage():
    """Print the command list."""
    print(f"freshdesk-toolkit {VERSION} - read-only Freshdesk CLI\n")
    print("usage: freshdesk-toolkit.py <command> [args]\n")
    print("read:")
    print("  list [n]                    recent tickets, newest first (default 30)")
    print("  get <id>                    one ticket in full, with its conversations")
    print("  search <term> [pages]       filter by subject over the recent pages")
    print("  search --query \"status:2 AND group_id:73604\"")
    print("                              server-side filters, whole history")
    print("  find <term> [--limit n]     free text in the exported dataset, offline")
    print("  groups                      group name to id mapping")
    print("  fields                      ticket fields and their allowed values")
    print("  whoami                      the agent the API key belongs to")
    print("  api <path>                  any read endpoint, GET only")
    print("\nstatistics:")
    print("  count '<query>'             server-side match count, e.g. \"group_id:123\"")
    print("  export [--since YYYY-MM-DD] [--out <file>] [--max-pages <n>]")
    print("                              bulk pull to a local dataset for offline work")
    print("  stats [--by <dims>] [--since <d>] [--until <d>] [--group-id <id>] [--top <n>]")
    print("                              aggregate the dataset; dims: group, status,")
    print("                              priority, type, month, day, cf.<field>")
    print(f"\nenv file:  {ENV_FILE}")
    print(f"dataset:   {CACHE_FILE}")
    print("\noptions:")
    print("  --json                      print raw objects, for jq")
    print("  --self-test                 offline assertions, no network")
    print("\nHealth:")
    print("  guard                       check env file, credentials and dataset")
    print("\nThis toolkit is read-only: it has no command that can change a ticket.")


load_env(ENV_FILE)

if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
    sys.exit(self_test())

if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
    usage()
elif sys.argv[1] not in COMMANDS:
    print(f"unknown command: {sys.argv[1]}\n", file=sys.stderr)
    usage()
    sys.exit(2)
else:
    # --json is accepted anywhere after the command, so it can trail a path.
    arguments = sys.argv[2:]
    if "--json" in arguments:
        JSON_OUT = True
        arguments = [item for item in arguments if item != "--json"]
    sys.exit(COMMANDS[sys.argv[1]](arguments) or 0)
