# check_nethlogger_logflood.py

## Description

Ranks the assets monitored by a NethLogger appliance by log volume in a time
window and, for the busiest ones, names the program and the message pattern
behind the flood. A short remediation hint is attached when the pattern matches
a known failure mode.

The check answers three questions in one line: which host logs the most, why it
logs that much, and what to do about it.

## Data sources

Two transports are used, with different scopes:

| Transport | Authentication | Provides |
| --- | --- | --- |
| API | API key | log counters per asset for the window |
| UI session | user and password | the individual messages, to name the cause |

The API transport is mandatory. The UI transport is optional: without it the
check still reports every volume, it only omits the reason.

Counters come from `noauth_getstats` and are window-scoped, not cumulative.
Only `stats` and `cyber` accept a date range on the API; patches, software,
hardware and vulnerabilities are snapshots and cannot be queried by time.

## States

| State | Condition |
| --- | --- |
| 0 OK | total below the warning threshold |
| 1 WARNING | total at or above the warning threshold |
| 2 CRITICAL | total at or above the critical threshold |
| 3 UNKNOWN | configuration missing, API unreachable, login rejected |

Thresholds are on the total per window. Their defaults (1,000,000 and
10,000,000 logs per 24 hours) suit a small tenant; large tenants need them
raised, or the split described in the notes below.

## Output

One service per reported asset, plus a summary service:

```text
2 NethLogger.nb-angelo - 13383035 logs/24h (err=13376981 warning=5981 info=37);
  top: tracker-miner-fs-3 100% "Tracker-WARNING **: N Failed to update ignored file
  <value>: ambiguous column name:" | solution: GNOME Tracker indexer loop: ...
0 NethLogger.Summary - 1 hosts above WARNING, 1 above CRITICAL; worst nb-angelo ...
```

The share next to the program is the program share, not the exact-message
share: one faulty service usually emits several wording variants of the same
error, and counting exact messages would split the flood across duplicates.

Only the assets above the warning threshold trigger the message lookup, which
costs two extra requests per asset. The others cost nothing beyond the API key
call.

## Configuration

All settings are environment variables, read from `NETHLOGGER_ENV` first
(default `/opt/nethlogger-toolkit/.env`) and then from the process environment.

| Variable | Default | Meaning |
| --- | --- | --- |
| `NETHLOGGER_ENV` | `/opt/nethlogger-toolkit/.env` | env file to load |
| `NETHLOGGER_URL` | none | appliance base URL |
| `NETHLOGGER_APIKEY` | none | API key |
| `NETHLOGGER_APIKEY_FILE` | `/root/.netlogger-apikey` | file holding the API key |
| `NETHLOGGER_UI_USER` | none | UI user, enables the reason lookup |
| `NETHLOGGER_UI_PASS` | none | UI password |
| `NETHLOGGER_UI_PASS_FILE` | `/root/.netlogger-uipass` | file holding the UI password |
| `NETHLOGGER_UI_PASS_KEY` | `NETHLOGGER_PASS` | key to extract from a KEY=VALUE password file |
| `NETHLOGGER_LOCATION` | none | opaque location token used by the search form |
| `NETHLOGGER_WINDOW_HOURS` | `24` | look-back window |
| `NETHLOGGER_WARN_LOGS` | `1000000` | warning threshold per window |
| `NETHLOGGER_CRIT_LOGS` | `10000000` | critical threshold per window |
| `NETHLOGGER_TOP_HOSTS` | `5` | how many assets to report |
| `NETHLOGGER_SAMPLE_ROWS` | `500` | messages sampled per asset to find the pattern |
| `NETHLOGGER_INSECURE` | unset | set to `1` to skip TLS verification |

The location token is not derivable: it is an opaque per-tenant value emitted
by the search page and must be copied from a logged-in session.

## Deployment

The check shares its transport and analysis with `nl-toolkit.py`, in
`nl_common.py`. The two files must stay together: the check imports
`nl_common` from its own directory (or from `/opt/nethlogger-toolkit`).

```bash
install -d -m 755 /opt/nethlogger-toolkit
install -m 755 nl_common.py check_nethlogger_logflood.py /opt/nethlogger-toolkit/
install -m 600 .env /opt/nethlogger-toolkit/.env
/opt/nethlogger-toolkit/check_nethlogger_logflood.py
```

The file is a CheckMK local check: copy it without the extension into the local
checks directory of the site, for example
`/omd/sites/<site>/local/lib/check_mk/base/plugins/agent_based/` for an agent
plugin, or the local checks directory for the classic local check protocol.
A symlink is enough, and safer than a copy: it keeps `nl_common.py` reachable.

For interactive queries over the same appliance see `nl-toolkit.md` in this
directory.

## Notes and limitations

- A host with a huge volume but below the threshold stays green. Warning-heavy
  hosts (for example a machine emitting 500,000 warnings a day and little
  else) deserve a second service on the `warning` and `err` counters alone,
  rather than only on the total.
- The remediation hints cover four known patterns (indexer loops, systemd
  restart loops, retries on vanished temporary files, printing subsystems) and
  fall back to a generic recommendation. They are hints, not conclusions.
- The message lookup depends on the UI search contract, which is undocumented:
  a form post to `reports/` produces an encrypted `params` blob that the
  results endpoint consumes. A NethLogger upgrade that changes that contract
  breaks the reason, not the volumes.
- **Do not ship comments or logs from customer hosts to third parties.** The
  sample rows may contain absolute paths and user names.

## Self-test

```bash
python3 check_nethlogger_logflood.py --self-test
```

Offline assertions over normalization, aggregation, ranking, thresholds and
line formatting. No network access is used.
