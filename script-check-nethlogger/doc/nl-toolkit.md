# nl-toolkit.py

Query tool for a NethLogger appliance, sibling of `ydea-toolkit.py` and
`freshdesk-toolkit.py`: one file in `/opt`, an `.env` beside it, subcommands,
output readable as a table or pipeable as JSON.

It exists because the appliance has no search API. Volumes come from the
API key, messages and sessions from a UI session, and both transports live in
`nl_common.py` together with the analysis the CheckMK check uses. The check and
the toolkit therefore cannot drift apart.

## Installation

```bash
install -d -m 755 /opt/nethlogger-toolkit
install -m 755 nl_common.py nl-toolkit.py check_nethlogger_logflood.py \
    /opt/nethlogger-toolkit/
install -m 600 .env /opt/nethlogger-toolkit/.env
ln -s /opt/nethlogger-toolkit/nl-toolkit.py /usr/local/bin/nl_query
```

Standard library only: it runs on a host where `pip install` is not an option,
including a CheckMK site.

## Commands

| Command | Answers |
| --- | --- |
| `guard` | is the URL set, the key accepted, the login working, the location token present |
| `list [--hours 24] [--min N]` | which assets log the most |
| `why <asset>` | why one asset logs that much: volumes, programs, pattern, remedy |
| `search <text> [--host H] [--program P] [--level L] [--since 24h]` | free text in the logs |
| `sessions --host H [--since 7d]` | login, deduced logout and failed attempts, per user |
| `silent [--hours 24] [--last-seen]` | which assets stopped sending logs |
| `api <endpoint>` | raw call to one of the six `noauth_` endpoints |
| `version` | versions of the tool and of the shared core |

`--json` switches any command to raw objects for `jq`. Exit code 2 means the
command could not run (bad arguments, unreachable appliance); `guard` exits 1
when the credentials are refused.

```bash
nl_query why nb-angelo
nl_query search "ambiguous column" --host nb-angelo --since 2h
nl_query search "authentication failure" --since 24h --json \
  | jq -r '.[].host' | sort -u
nl_query sessions --host nb-angelo --since 7d
nl_query silent --hours 24 --last-seen
```

## The search contract

The UI search is undocumented and its form has three traps, all handled here:

- `program` is mandatory. Without it the server switches to the Login/Logout
  module, which on this appliance contains only `sudo` events.
- An empty `priority` is not "all levels": the server matches it literally and
  returns nothing. For a full search the field must be left out.
- `host[]` is optional, so a search can span the whole tenant.

The `msg` field does filter, as a substring. `d.params`, the opaque blob that
the results endpoint consumes, is extracted from the `reports/` response.

## Sessions

Real user sessions are in the free search, filtered by program:
`gdm-password` (`session opened for user X`, `authentication failure`) and
`gdm3` (`on_display_removed` at logout, `unexpectedly disconnected from boot
status daemon` at boot). The "Login/Logout" module of the UI is not used: it
contains only `sudo` events.

The appliance rarely writes `session closed` at shutdown, so the end of a
session is deduced from `on_display_removed`, and an absence of either is
reported as such.

## Cost

| Command | Measured |
| --- | --- |
| `guard` | 7 s |
| `search` | 1 to 3 s |
| `sessions` (7 days, 4 programs) | 8 s |
| `silent` | 5 s |
| `silent --last-seen` | 8 s for two assets |
| `why` | 43 s: four `getstats` calls carry the whole tenant |

## Self-test

```bash
python3 nl_common.py            # assertions over the shared core
```

Offline: windows, normalization, ranking, remediation, session classification
and asset flattening. No network, no credentials.
