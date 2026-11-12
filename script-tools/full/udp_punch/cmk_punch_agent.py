#!/usr/bin/python3
"""CheckMK datasource program: print the agent output carried by cmk-punch.

Used by the rule "Individual program call instead of agent access". The
tunnel server listens on a UNIX socket, so the kernel reports the peer uid
with SO_PEERCRED and ESET cannot interpose on the loopback TCP path.
"""

import socket
import sys

DEFAULT_PATH = "/run/cmk-punch/agent.sock"


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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
