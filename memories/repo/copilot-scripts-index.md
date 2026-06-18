# copilot-scripts-index

Index of reusable scripts created or maintained in this repository.

---

## script-tools/full/monitoring_diagnostics/marcatempo-log-analyzer.py

| Field | Value |
|-------|-------|
| **Purpose** | Deep 90-day log analysis for marcatempo-* hosts. Parses Nagios archive logs, classifies events (HOST/SERVICE ALERT, FLAPPING, NOTIFICATION), computes before/after comparisons, PING-vs-host correlation, and per-host detailed assessment. |
| **Language** | Python 3 |
| **CLI** | None (standalone, edit `HOSTS` and `FLAP_CHANGE_TS` constants at the top) |
| **Execution** | `ssh srv-monitoring-us "python3 -B < script.py"` (or run directly on OMD server) |
| **Safety** | Read-only — parses logs, no writes, no config changes, no Nagios pipe writes |
| **Outputs** | Structured tables printed to stdout |
| **Dependencies** | Python 3 stdlib only (os, re, sys, gzip, collections, datetime) |
| **Config** | `HOSTS` list, `FLAP_CHANGE_TS` boundary timestamp, `ARCHIVE_DIR` and `CURRENT_LOG` paths |

### Example

```bash
# On srv-monitoring-us
b64=$(base64 -w0 script-tools/full/monitoring_diagnostics/marcatempo-log-analyzer.py)
ssh srv-monitoring-us "echo $b64 | base64 -d | python3 -B"
```

### Notes

- Handles both plain and .gz compressed Nagios archive files
- Detects `STARTED`/`STOPPED` (Nagios log format), not `START`/`STOP`
- Estimates DOWN durations by pairing HARD DOWN → HARD UP events
- No external dependencies beyond Python 3 stdlib

---

## script-tools/full/misc/python-cache-cleanup.py

| Field | Value |
|-------|-------|
| **Purpose** | Scan Git repositories for Python cache artifacts (`__pycache__/`, `.pyc`, `.pyo`), report inventory, remove them, and verify `.gitignore` coverage |
| **Language** | Python 3 |
| **CLI** | `--repos PATH1 PATH2`, `--dry-run`, `--inventory-only`, `--skip-gitignore`, `--baseline`, `--version` |
| **Execution** | `python3 -B script-tools/full/misc/python-cache-cleanup.py [options]` |
| **Safety** | `--dry-run` shows what would be removed without deleting; `--inventory-only` is read-only |
| **Outputs** | Per-repo status, artifact counts, cleanup results, optional baseline report in `/tmp/` |
| **Dependencies** | Python 3 stdlib only (os, subprocess, sys, argparse, datetime) |

### Examples

```bash
# Dry-run on all default repos
python3 -B script-tools/full/misc/python-cache-cleanup.py --dry-run

# Full cleanup + baseline report on specific repos
python3 -B script-tools/full/misc/python-cache-cleanup.py --baseline --repos /path/to/repo1 /path/to/repo2

# Inventory only
python3 -B script-tools/full/misc/python-cache-cleanup.py --inventory-only
```

### Notes

- Default repo list is hardcoded for the WSL Kali environment (`/mnt/c/Users/Marzio/...`)
- Skips `.git/`, `.venv/`, `venv/`, `env/`, `.tox/`, `.nox/`, `node_modules/` during traversal
- Validates `.gitignore` has `__pycache__/`, `*.py[cod]`, `*$py.class` patterns
