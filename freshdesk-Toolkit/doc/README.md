# freshdesk-Toolkit

Read-only CLI for ticket research and statistics against a Freshdesk helpdesk.

The tool exists to answer questions about tickets, not to manage them. It has
no command that can create, comment on, update, close or delete anything, and
the generic `api` command refuses every method except GET.

## Layout

| Path | Purpose |
| --- | --- |
| `full/freshdesk-toolkit.py` | the CLI |
| `doc/README.md` | this file |

## Setup on a host

Install the CLI and create the credentials file next to it:

```sh
install -o root -g root -m 0755 full/freshdesk-toolkit.py /opt/freshdesk-toolkit/freshdesk-toolkit.py
```

`/opt/freshdesk-toolkit/.env`, mode 0600, must define:

```sh
FRESHDESK_DOMAIN=<your-helpdesk>.freshdesk.com
FRESHDESK_API_KEY=YOUR_API_KEY_HERE
```

The API key is used as the basic-auth username; the password is ignored. A
plain agent account is enough for everything here.

Optional overrides, by environment variable: `FRESHDESK_ENV` (path of the
credentials file), `FRESHDESK_CACHE_FILE` (dataset path), `FRESHDESK_TIMEOUT`.

## Commands

### Reading

| Command | Result |
| --- | --- |
| `list [n]` | recent tickets, newest first |
| `get <id>` | one ticket in full, with its conversations |
| `search <term> [pages]` | recent tickets whose subject contains a term |
| `groups` | group name to id mapping |
| `fields` | ticket fields and their allowed values |
| `whoami` | the agent the API key belongs to |
| `api <path>` | any read endpoint, GET only |

### Statistics

| Command | Result |
| --- | --- |
| `count '<query>'` | how many tickets match, counted server-side |
| `export [--since <date>] [--out <file>] [--max-pages <n>]` | bulk pull to a local dataset |
| `stats [--by <dims>] [--since <d>] [--until <d>] [--group-id <id>] [--top <n>]` | aggregate that dataset |

`stats` groups by `group`, `status`, `priority`, `type`, `month`, `day`, or any
custom field as `cf.<name>`. Several dimensions can be combined with commas.
Chronological dimensions print in date order; the others are ranked by size.

```sh
freshdesk-toolkit.py count "created_at:>'2026-10-01'"
freshdesk-toolkit.py export --since 2026-01-01
freshdesk-toolkit.py stats --by group,month
freshdesk-toolkit.py stats --by cf.tipo_intervento --group-id <group id> --top 10
```

## Why counting and exporting use different endpoints

The search endpoint filters server-side and reports a total, but returns only
30 results per page, so it is the right tool for a count and the wrong one for
a dataset. The ticket listing with `updated_since` returns 100 per page and
keeps paging much further, which is what makes a historical extraction
practical. `count` therefore uses the first, `export` the second.

## Handling of the exported dataset

The dataset holds real ticket text. `export` forces it to mode 0600 inside a
0700 directory, and the repository ignores `cache/` and `*.jsonl` so an
extraction can never be committed by accident.
