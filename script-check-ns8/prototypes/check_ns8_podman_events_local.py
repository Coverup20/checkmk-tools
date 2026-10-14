#!/usr/bin/env python3
"""check_ns8_podman_events_local.py - CheckMK local check for the podman-events daemon (PROTOTYPE)

Companion of monitor_podman_events_api.py (the actual daemon, runs as its own
systemd service, see ns8-podman-events.service). This script does only one
thing, fast: read the STATE_FILE the daemon writes every HEARTBEAT_SECONDS
(default 30s) and report whether it is alive and recent. It makes no network
call, no podman call, and never blocks - safe to run as a CheckMK local check
every minute.

State:
  CRIT   STATE_FILE missing (daemon never ran here, or was removed)
  CRIT   STATE_FILE older than STALE_SECONDS (daemon stuck or dead: the
         heartbeat thread writes it every 30s regardless of events, so a gap
         this large means the process itself is not running or is wedged)
  OK     otherwise, with the event count of the last hour and a reminder of
         which modules are currently being followed

Version: 0.1.0"""

import json
import os
import sys
import time

VERSION = "0.1.0"
STATE_FILE = os.environ.get("NS8_EVENTS_STATE_FILE", "/var/lib/ns8-podman-events/state.json")
STALE_SECONDS = 180  # 6x the daemon's 30s heartbeat: one slow cycle is normal, six is not


def main() -> int:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        print(f"2 NS8.PodmanEvents.Daemon - CRITICAL: state file not found ({STATE_FILE}); "
              f"is ns8-podman-events.service running?")
        return 0
    except (OSError, ValueError) as exc:
        print(f"2 NS8.PodmanEvents.Daemon - CRITICAL: cannot read state file: {exc}")
        return 0

    age = time.time() - float(state.get("updated_at", 0))
    modules = state.get("modules_followed") or []
    events = int(state.get("events_in_window") or 0)
    window_h = int(state.get("event_window_seconds") or 3600) // 3600

    if age > STALE_SECONDS:
        print(f"2 NS8.PodmanEvents.Daemon age=%.0f;%d;;0; CRITICAL: state is %.0f s old (pid %s), "
              "daemon looks stuck or dead" % (age, STALE_SECONDS, age, state.get("pid", "?")))
        return 0

    print(f"0 NS8.PodmanEvents.Daemon age=%.0f;%d;;0;|events_%dh=%d;;;0; "
          "OK: alive (pid %s), following %d module(s): %s, %d event(s) in the last %dh"
          % (age, STALE_SECONDS, window_h, events, state.get("pid", "?"), len(modules),
             ", ".join(modules) or "-", events, window_h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
