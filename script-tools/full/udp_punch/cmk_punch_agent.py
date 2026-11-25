#!/usr/bin/python3
"""CheckMK datasource program: print the agent output carried by cmk-punch.

Used by the rule "Individual program call instead of agent access". The
tunnel server listens on a UNIX socket, so the kernel reports the peer uid
with SO_PEERCRED and ESET cannot interpose on the loopback TCP path.
"""

import json
import os
import socket
import sys
import time

DEFAULT_PATH = "/run/cmk-punch/agent.sock"


def state_dir_for(path):
    """The state directory that belongs to a socket path, by convention."""
    name = os.path.basename(path)
    if name == "agent.sock":
        return "/var/lib/cmk-punch"
    if name.endswith(".sock"):
        return "/var/lib/cmk-punch-" + name[:-len(".sock")]
    return None


def emit_liveness(path):
    """Print the peer's own reachability test as a local check.

    The peer that proxies an appliance pings it (or opens a TCP connection)
    independently of the agent. Emitting it as a separate service keeps the
    host reachable signal distinct from the agent fetch.
    """
    state_dir = state_dir_for(path)
    if not state_dir:
        return
    status_path = os.path.join(state_dir, "peer_status.json")
    try:
        with open(status_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    alive = data.get("target_alive")
    if not isinstance(alive, bool):
        return
    try:
        age = int(time.time() - os.path.getmtime(status_path))
    except OSError:
        age = None
    target = data.get("target") or "target"
    state = 0 if alive else 2
    text = "reachable" if alive else "not reachable"
    when = (", checked %ds ago" % age) if age is not None else ""
    sys.stdout.write("<<<local:sep(0)>>>\n")
    sys.stdout.write("%d PUNCH.Liveness - %s %s%s\n" % (state, target, text, when))
    sys.stdout.flush()


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_PATH
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(60)
    try:
        sock.connect(path)
    except OSError as exc:
        print("cmk_punch_agent: cannot connect to %s: %s" % (path, exc),
              file=sys.stderr)
        return 2
    total = 0
    try:
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            sys.stdout.buffer.write(chunk)
            total += len(chunk)
    except OSError as exc:
        print("cmk_punch_agent: read error after %d bytes: %s" % (total, exc),
              file=sys.stderr)
        return 3
    finally:
        sock.close()
        sys.stdout.buffer.flush()
    if not total:
        print("cmk_punch_agent: empty output from the tunnel", file=sys.stderr)
        return 4
    emit_liveness(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
