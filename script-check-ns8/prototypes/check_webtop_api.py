#!/usr/bin/env python3
"""check_webtop_api.py - CheckMK local check for WebTop (webtop1), runs ON the NS8 node

Converted from the former CheckMK special agent agent_webtop_api.py (ran on the
CheckMK server, over the public network with certificate pinning) into a local check
that runs here, on the node, and reaches webtop1 over the loopback interface through
Traefik (SNI webtop.nethlab.it, connection never leaves the host). No certificate
pinning needed any more: there is no network path for a machine-in-the-middle to sit
on. See memory "ns8_rl98 local check reorganisation", 2026-10-12.

Reads the module's own unauthenticated health endpoint: GET /webtop/healthcheck ->
{"status": "READY"|..., "maintenance": bool}.

Checks (identical to the former special agent):
- WebTop.Status      healthcheck status + maintenance flag
- WebTop.ApiTime     response time of the healthcheck call

NOTE: this REPLACES check_ns8_webtop_api.py's "Webtop5" check, which only tested
whether `GET /webtop/` returned HTTP 200 - weaker than this (no maintenance-mode
detection, no response-time threshold). Old script moved aside, not deleted.

Piggybacked to NS8-RL98-WEBTOP (this check belongs to that module, not the node).

Version: 1.0.0"""

import http.client
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional

VERSION = "1.0.0"
HOSTNAME = "webtop.nethlab.it"
NODE_IP = "127.0.0.1"
RESPONSE_SECONDS = (1.0, 3.0)

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


class _LocalHTTPSConnection(http.client.HTTPSConnection):
    """Connects to NODE_IP over loopback but keeps TLS SNI / Host header as self.host
    (same trick as `curl --resolve`): Traefik still routes by the vhost name."""

    def connect(self) -> None:
        sock = socket.create_connection((NODE_IP, self.port or 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


def _opener(ctx: ssl.SSLContext) -> urllib.request.OpenerDirector:
    class LocalHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001 - matches urllib's own (untyped) signature
            return self.do_open(lambda host, **kw: _LocalHTTPSConnection(host, context=ctx, **kw), req)

    return urllib.request.build_opener(LocalHandler())


def main() -> int:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request("https://%s/webtop/healthcheck" % HOSTNAME, headers={"Accept": "application/json"})

    t0 = time.monotonic()
    try:
        with _opener(ctx).open(req, timeout=15) as resp:
            body = json.load(resp)
        secs = time.monotonic() - t0
    except urllib.error.HTTPError as exc:
        emit(2, "WebTop.Status", "healthcheck http-%d (module not ready or restarting)" % exc.code)
        return 0
    except (urllib.error.URLError, OSError, ValueError) as exc:
        emit(2, "WebTop.Status", "healthcheck unreachable: %s" % exc.__class__.__name__)
        return 0

    status = body.get("status") if isinstance(body, dict) else None
    maintenance = bool(body.get("maintenance")) if isinstance(body, dict) else False
    state = 0 if status == "READY" and not maintenance else (1 if maintenance else 2)
    emit(state, "WebTop.Status", "status=%s maintenance=%s" % (status, maintenance))

    rt_state = 2 if secs >= RESPONSE_SECONDS[1] else 1 if secs >= RESPONSE_SECONDS[0] else 0
    emit(rt_state, "WebTop.ApiTime", "healthcheck answered in %.2f s" % secs,
         ["response_seconds=%.3f;%g;%g;0;" % (secs, RESPONSE_SECONDS[0], RESPONSE_SECONDS[1])])
    return 0


if __name__ == "__main__":
    # Piggyback to NS8-RL98-WEBTOP: this check belongs to that module, not the node itself
    # (see memory ns8_rl98 local check reorganisation, 2026-10-12)
    print("<<<<NS8-RL98-WEBTOP>>>>")
    print("<<<local:sep(0)>>>")
    _rc = main()
    print("\n".join(_OUT))
    print("<<<<>>>>")
    sys.exit(_rc)
