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
| State | `$OMD_ROOT/var/check_mk/Telegram-20/state.json` |
| Log | `$OMD_ROOT/var/log/Telegram-20.log` |

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
