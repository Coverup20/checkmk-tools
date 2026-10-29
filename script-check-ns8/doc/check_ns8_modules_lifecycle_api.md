# check_ns8_modules_lifecycle_api

Monitors the software lifecycle and update posture of an NS8 node **above** the
host operating system — the two layers that `dnf` and host-level OS checks
cannot see:

- **Layer 2 (`NS8.Modules.Updates`, NIS `PR.PS-02.2`)** — whether all installed
  NS8 core and application modules are on the latest stable release from the
  Software Center, and how long any pending stable update has been waiting.
- **Layer 3 (`NS8.Modules.Lifecycle`, NIS `PR.PS-02.1`)** — whether the inner
  rootless Podman container images shipped *inside* those modules run supported
  engines and base distributions (Redis, MariaDB, PostgreSQL, Mattermost,
  Nginx, Traefik, Ubuntu, Debian, Alpine) or contain end-of-life / ancient
  builds.

The script is 100% REST-only: it queries the local NS8 cluster HTTP API
(`http://127.0.0.1:9311/api`) with the least-privilege reader account and each
module's rootless Podman Unix socket (`/run/user/<uid>/podman/podman.sock`).
No subprocesses are spawned.

## Why two separate services

The two layers have different owners when an alert fires:

| Service | NIS measure | Who acts when it alerts |
| --- | --- | --- |
| `NS8.Modules.Updates` | `PR.PS-02.2` | **System administrator**: apply the pending module update in the NS8 Software Center within the remediation window. |
| `NS8.Modules.Lifecycle` | `PR.PS-02.1` | **Module vendor / supply-chain governance**: the NS8 module itself is already at the latest version, so the operator cannot fix an inner EOL engine from the UI; it requires an upstream module rebuild (CRA) or a documented risk acceptance (`GV.SC-07` / `ID.RA-08.2`). |

## Guard against silent false negatives

1. **Unreachable Software Center repositories**: in NS8's `cluster.modules`, a
   failed fetch of `repodata.json` logs a warning and returns an empty module
   list, which makes `list-updates` return `[]` (zero pending updates). This
   check verifies that remote repository metadata is actually loaded and that
   `repository_updated` is no older than `CHECK_NS8_REPO_STALE_DAYS` (default
   `7`); otherwise it reports `3 UNKNOWN` instead of a misleading `0 OK`.
2. **Pre-release noise**: `list-modules` populates `testing_update` for `-dev`
   and `-testing` tags alongside stable `update` tags. Only stable updates
   trigger ageing and alerts; testing tags are counted in perfdata and ignored.
3. **First-run honesty**: when pending stable updates are seen for the first
   time and no state file exists yet, `NS8.Modules.Updates` emits `1 WARNING`
   rather than `0 OK` and starts ageing from that day.
4. **Embedded lifecycle table staleness**: `DATA_AS_OF` + `STALE_AFTER_DAYS`
   (`180`) downgrades a clean `0 OK` on `NS8.Modules.Lifecycle` to `3 UNKNOWN`
   if the check is not refreshed within six months, while leaving `WARNING` and
   `CRITICAL` verdicts intact.

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `NS8_API` | `http://127.0.0.1:9311/api` | Local NS8 API URL. |
| `NS8_USER` | `claude-ro` | Read-only cluster user for login fallback. |
| `NS8_PASSWORD_FILE` | `/root/.ns8-ro-pass` | Password file for login fallback. |
| `NS8_TOKEN_FILE` | `/root/.ns8-token-ro` | Cached JWT file tried first. |
| `CHECK_NS8_MOD_GRACE_DAYS` | `7` | Days before a pending module update turns `WARNING`. |
| `CHECK_NS8_MOD_SLA_DAYS` | `14` | Days before a pending module update turns `CRITICAL`. |
| `CHECK_NS8_REPO_STALE_DAYS` | `7` | Maximum age in days for Software Center metadata. |
| `CHECK_NS8_EOL_WARN_DAYS` | `180` | Days before component EOL to start warning. |
| `CHECK_NS8_IMAGE_WARN_DAYS` | `365` | Image build age in days that triggers `WARNING`. |
| `CHECK_NS8_IMAGE_CRIT_DAYS` | `730` | Image build age in days that triggers `CRITICAL`. |

## Usage

```bash
# Normal invocation (CheckMK local check)
python3 check_ns8_modules_lifecycle_api.py

# Self-test (11 unit test cases, exits non-zero on failure)
python3 check_ns8_modules_lifecycle_api.py --self-test
```

## Compatibility

Compatible with **Python 3.9+** (tested on Rocky Linux 9.8 with Python 3.9.25).
