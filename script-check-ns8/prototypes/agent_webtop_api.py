#!/usr/bin/env python3
"""agent_webtop_api.py - CheckMK special agent (datasource program) for WebTop (Sonicle), no credentials (PROTOTYPE)

Runs on the CheckMK server and reads the module's own unauthenticated health
endpoint: GET /webtop/healthcheck -> {"status": "READY"|..., "maintenance": bool}.
Nothing installed on the WebTop host. Prints CheckMK local-check lines.

Checks:
- WebTop.Status      healthcheck status + maintenance flag
- WebTop.ApiTime     response time of the healthcheck call

Certificate pinning (--pin-sha256): the lab certificate is self-signed, so normal
CA validation is off (--insecure) and by itself that means ANY certificate is
accepted - a machine-in-the-middle on the same network could present its own
certificate unnoticed. --pin-sha256 closes that: give the SHA-256 fingerprint
(hex) of the real certificate and every connection then fails closed unless the
server presents exactly that certificate. Not a secret, so a plain CLI argument.

Usage (datasource program):
  agent_webtop_api.py --url https://webtop.example.org --insecure --pin-sha256 <fingerprint>

Version: 0.2.0"""

import argparse
import hashlib
import http.client
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

VERSION = "0.2.0"
RESPONSE_SECONDS = (1.0, 3.0)

_OUT: List[str] = []


def emit(state: int, name: str, text: str, metrics: Optional[List[str]] = None) -> None:
    name = re.sub(r"\s+", "_", name)
    _OUT.append("%d %s %s %s" % (state, name, "|".join(metrics) if metrics else "-", text.replace("\n", " ")))


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Like HTTPSConnection, but after the TLS handshake refuses to proceed unless the
    peer certificate's SHA-256 fingerprint matches exactly."""

    pinned_sha256 = ""

    def connect(self) -> None:
        super().connect()
        der = self.sock.getpeercert(binary_form=True)  # type: ignore[union-attr]
        if not der:
            raise ssl.SSLError("certificate pinning: no peer certificate available to check")
        actual = hashlib.sha256(der).hexdigest()
        if actual != self.pinned_sha256:
            raise ssl.SSLCertVerificationError(
                "certificate pin mismatch: expected %s, got %s (server certificate changed or a different host answered)"
                % (self.pinned_sha256, actual)
            )


def _opener(ctx: ssl.SSLContext, pin_sha256: str) -> urllib.request.OpenerDirector:
    if not pin_sha256:
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    class PinnedHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):  # noqa: ANN001 - matches urllib's own (untyped) signature
            def factory(host, **kwargs):
                conn = _PinnedHTTPSConnection(host, context=ctx, **kwargs)
                conn.pinned_sha256 = pin_sha256
                return conn

            return self.do_open(factory, req)

    return urllib.request.build_opener(PinnedHandler())


def main() -> int:
    ap = argparse.ArgumentParser(description="CheckMK special agent for WebTop (unauthenticated healthcheck)")
    ap.add_argument("--url", required=True, help="WebTop base URL, e.g. https://webtop.example.org")
    ap.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate against a CA (needed for a self-signed lab certificate)")
    ap.add_argument("--pin-sha256", default="", help="SHA-256 fingerprint (hex) of the expected certificate; with --insecure this is what actually stops a machine-in-the-middle, not a secret")
    args = ap.parse_args()
    url = args.url.rstrip("/") + "/webtop/healthcheck"
    pin = args.pin_sha256.strip().lower().replace(":", "")

    print("<<<check_mk>>>")
    print("Version: webtop-api-special-agent-%s" % VERSION)
    print("AgentOS: webtop-api")
    print("<<<local:sep(0)>>>")

    ctx = ssl.create_default_context()
    if args.insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    t0 = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with _opener(ctx, pin).open(req, timeout=15) as resp:
            body = json.load(resp)
        secs = time.monotonic() - t0
    except urllib.error.HTTPError as exc:
        emit(2, "WebTop.Status", "healthcheck http-%d (module not ready or restarting)" % exc.code)
        print("\n".join(_OUT))
        return 0
    except (urllib.error.URLError, OSError, ValueError) as exc:
        cause = getattr(exc, "reason", exc)
        if isinstance(cause, ssl.SSLCertVerificationError):
            emit(2, "WebTop.Status", "PIN MISMATCH (possible machine-in-the-middle): %s" % cause)
        else:
            emit(2, "WebTop.Status", "healthcheck unreachable: %s" % exc.__class__.__name__)
        print("\n".join(_OUT))
        return 0

    status = body.get("status") if isinstance(body, dict) else None
    maintenance = bool(body.get("maintenance")) if isinstance(body, dict) else False
    state = 0 if status == "READY" and not maintenance else (1 if maintenance else 2)
    text = "status=%s maintenance=%s" % (status, maintenance)
    emit(state, "WebTop.Status", text)

    rt_state = 2 if secs >= RESPONSE_SECONDS[1] else 1 if secs >= RESPONSE_SECONDS[0] else 0
    emit(rt_state, "WebTop.ApiTime", "healthcheck answered in %.2f s" % secs,
         ["response_seconds=%.3f;%g;%g;0;" % (secs, RESPONSE_SECONDS[0], RESPONSE_SECONDS[1])])

    print("\n".join(_OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
