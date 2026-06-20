# Telegram-20

Telegram-20 is a beta Checkmk Telegram notification handler with an audit-only
fail2ban-style transition rate limiter and adaptive learning for
**HOST STATE** and **SERVICE STATE PING** notifications.

Derived from the production `telegram` notification method on `srv-monitoring-us`.

## Architecture

```
Checkmk notification event
        │
        ▼
  evaluate_rate_limit()
        │
        ├── BYPASS ──────► send Telegram (non-PING, disabled)
        │
        ├── SEND ────────► send Telegram
        │
        ├── WOULD_SUPPRESS ──► send Telegram (audit mode)
        │
        ├── SUPPRESS ────► log + return (enforce mode, NOT default)
        │
        └── FAIL_OPEN ───► send Telegram (error path)
                │
                ▼
        Adaptive learning
        (recommendation only, never auto-applied)
```

## Modes

### audit (default)
Every notification is always sent. The rate-limit decision is calculated
and logged but never enforced.

### enforce
Once the transition threshold is reached, further notifications for that
host/category are suppressed until the suppression window expires.

## Static rate-limiter

### HOST STATE
Tracks only real changes between `UP ↔ DOWN`. Repeated identical states
not counted. Persistent DOWN does not trigger suppression.

### SERVICE STATE PING
Tracks only `PING` and only `OK ↔ CRIT` (or `CRITICAL`). `WARN`/`UNKNOWN`
logged but not counted. Non-PING services bypass.

**Threshold:** `transitions >= trigger_transitions` (inclusive)

| Category | Window | Trigger | Suppression |
|---|---|---|---|
| HOST STATE | 30 min | 4 | 60 min |
| SERVICE STATE PING | 30 min | 6 | 60 min |

## Adaptive learning

```json
{
    "adaptive": {
        "enabled": true,
        "mode": "learning",
        "minimum_learning_days": 14,
        "minimum_transition_samples": 20,
        "recalculate_every_hours": 24,
        "percentile": 95,
        "safety_margin": 2,
        "auto_apply": false
    }
}
```

Only `mode=learning` and `auto_apply=false` are supported.

### Formula
```
raw = ceil(percentile_95(window_counts_30m)) + safety_margin
clamped = max(hard_min, min(hard_max, raw))
```

### Limits

| Category | Min | Max |
|---|---|---|
| HOST STATE | 4 | 10 |
| SERVICE STATE PING | 6 | 20 |

## Fail-open

Any limiter/learning error → `FAIL_OPEN` → Telegram sent. Telegram API
errors retain their own error behaviour.

## Runtime paths

| Resource | Path |
|---|---|
| State file | `$OMD_ROOT/var/check_mk/Telegram-20/state.json` |
| Lock file | `$OMD_ROOT/var/check_mk/Telegram-20/state.lock` |
| Log file | `$OMD_ROOT/var/log/notifications/telegram-20.log` |

## Logging format

All lifecycle records use JSON Lines format with the `NOTIFY_EVENT ` prefix:

```
NOTIFY_EVENT {"level":"INFO","execution_id":"...","status":"INVOKED",...}
```

Each physical line is exactly one JSON object, parseable with `json.loads()` after
stripping the `NOTIFY_EVENT ` prefix.  The log is also grep-compatible:

```bash
grep "NOTIFY_EVENT" $OMD_ROOT/var/log/notifications/telegram-20.log
```

## Debug logging

Set the environment variable `TELEGRAM20_DEBUG=1` before invoking the script to enable
additional diagnostic output in the log:

```bash
TELEGRAM20_DEBUG=1 /opt/checkmk-tools/script-notify-checkmk/beta/Telegram-20
```

## State retention

The state file is bounded by the following defaults (configurable via
`state_retention` in the JSON configuration):

| Setting | Default | Description |
|---|---|---|
| `stale_host_days` | 30 | Remove hosts with no activity after this many days |
| `max_transitions_per_category` | 500 | Cap transition lists after age-based pruning |
| `cleanup_interval_seconds` | 3600 | Minimum seconds between full stale-host scans |

Cleanup runs under the state lock; expired records are removed, active
suppression and recent adaptive-learning data are preserved.

If the state file exceeds 10 MB, a warning is logged but the file is still
loaded.  Corrupted files are replaced with an empty state.  Writes use an
atomic temporary-file + `os.replace()` pattern.  If a write fails, the
original state file remains intact and temporary files are cleaned up.

## Configuration

Environment variables (same as production `telegram`):

| Variable | Purpose |
|---|---|
| `TELEGRAM_TOKEN` | Bot token |
| `TELEGRAM_CHAT_ID` | Target chat ID |
| `TELEGRAM_CUSTOMER_NAME` | Optional prefix label |
| `CMK_URL` | Checkmk URL for inline buttons |

## CLI

```bash
python3 -B Telegram-20 --learning-report
python3 -B Telegram-20 --version
```
