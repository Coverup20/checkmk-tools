#!/usr/bin/env python3
"""sync_punch_hosts.py - put each punch peer's declared address in its host

For every tunnel instance listed in the mapping file, reads the address the
peer declared during the handshake (peer_real_ip.txt in the instance state
directory) and writes it as the host's IPv4 address in CheckMK, removing the
real_ip label that held the same value. Hosts whose address has not been
learned yet are left untouched.

The host check must not use ICMP for these hosts: the monitoring server
cannot reach their LAN addresses. A host_check_commands rule with value "ok"
is expected to exist for them; this script does not create it.

Usage:
    sync_punch_hosts.py --dry-run
    sync_punch_hosts.py
    sync_punch_hosts.py --no-activate

Environment: CMK_API_USER (automation user, default "automation"), CMK_SITE
(site that runs cmk -O, default "monitoring").

Exit codes: 0 success, 1 configuration error.
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

VERSION = "1.4.0"

CONFIG_DIR = "/etc/cmk-punch"
MAPPING = os.path.join(CONFIG_DIR, "hosts.json")
DEFAULT_URL = "https://127.0.0.1/monitoring/check_mk/api/1.0"
DEFAULT_USER = os.environ.get("CMK_API_USER", "automation")
DEFAULT_SITE = os.environ.get("CMK_SITE", "monitoring")
SECRET_TEMPLATE = "/omd/sites/%s/var/check_mk/web/%s/automation.secret"


def log(msg):
    print("[INFO] %s" % msg)


def fail(msg):
    print("[ERROR] %s" % msg, file=sys.stderr)
    raise SystemExit(1)


def read_mapping(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        fail("cannot read %s: %s" % (path, exc))
    except ValueError as exc:
        fail("%s is not valid JSON: %s" % (path, exc))
    if not isinstance(data, dict) or not data:
        fail("%s must be a JSON object of instance -> host" % path)
    return data


def instance_config(instance):
    if instance == "server":
        return os.path.join(CONFIG_DIR, "server.json")
    return os.path.join(CONFIG_DIR, "server-%s.json" % instance)


def valid_address(value):
    parts = value.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    if value in ("0.0.0.0", "127.0.0.1"):
        return None
    return value


def state_of(instance):
    path = instance_config(instance)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    return cfg.get("state_dir") or None


def peer_status(state_dir):
    if not state_dir:
        return {}
    try:
        with open(os.path.join(state_dir, "peer_status.json"), "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def reported_target(state_dir):
    """The address the peer forwards to, when it reports an IP:port target.

    A peer that proxies an appliance (its target is the appliance) reports the
    appliance address here, which is the address the host should show.
    """
    target = peer_status(state_dir).get("target")
    if not isinstance(target, str) or ":" not in target:
        return None
    return valid_address(target.rsplit(":", 1)[0])


def declared_address(instance):
    """The address the instance declares for its monitored host, or None.

    Order: the target the peer forwards to, then the address the peer declared
    for itself in the handshake. The installer can record a managed_host_ip
    for an appliance; it is used first when present.
    """
    state_dir = state_of(instance)
    if not state_dir:
        return None
    managed = peer_status(state_dir).get("managed_host_ip")
    if isinstance(managed, str) and valid_address(managed):
        return managed
    for candidate in (reported_target(state_dir),):
        if candidate:
            return candidate
    try:
        with open(os.path.join(state_dir, "peer_real_ip.txt"), "r",
                  encoding="ascii") as fh:
            return valid_address(fh.read().strip())
    except OSError:
        return None


class Api:
    def __init__(self, url, user, secret):
        self.url = url.rstrip("/")
        self.auth = "Bearer %s %s" % (user, secret)
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def call(self, method, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", self.auth)
        req.add_header("Accept", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=15) as fh:
                return fh.status, json.loads(fh.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            return exc.code, detail
        except (urllib.error.URLError, OSError) as exc:
            fail("cannot reach %s: %s" % (self.url, exc))

    def host(self, name):
        code, body = self.call("GET", "/objects/host_config/%s" % name)
        if code != 200:
            fail("GET host %s failed: %s %s" % (name, code, body))
        return body.get("extensions", {}).get("attributes", {})

    def update(self, name, attributes):
        return self.call("PUT", "/objects/host_config/%s" % name,
                         {"update_attributes": attributes},
                         {"If-Match": "*"})


def activate(site):
    cmd = ["su", "-", "monitoring", "-c", "cmk -O"]
    log("activating changes: %s" % " ".join(cmd))
    result = subprocess.run(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        fail("activation failed: %s" % (result.stdout or "").strip())


def parse_entry(instance, value):
    """A mapping entry is either a host name or {"host": ..., "manual": true}.

    manual: the address comes from the real_ip label set by hand at install
    time; the sync writes it into ipaddress and removes the label.
    """
    if isinstance(value, str):
        return value, False
    if isinstance(value, dict) and isinstance(value.get("host"), str):
        return value["host"], bool(value.get("manual"))
    fail("mapping entry for %s must be a host name or {host, manual}" % instance)


def label_address(value):
    if not isinstance(value, str):
        return None
    for token in value.replace(",", " ").split():
        if valid_address(token):
            return token
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync punch peer addresses")
    parser.add_argument("--mapping", default=MAPPING)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--site", default=DEFAULT_SITE)
    parser.add_argument("--secret-file", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-activate", action="store_true")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)

    secret_file = args.secret_file or (SECRET_TEMPLATE % (args.site, args.user))
    try:
        with open(secret_file, "r", encoding="ascii") as fh:
            secret = fh.read().strip()
    except OSError as exc:
        fail("cannot read %s: %s" % (secret_file, exc))

    mapping = read_mapping(args.mapping)
    api = Api(args.url, args.user, secret)
    changed = 0
    for instance, raw in sorted(mapping.items()):
        host_name, manual = parse_entry(instance, raw)
        attributes = api.host(host_name)
        current = attributes.get("ipaddress")
        labels = dict(attributes.get("labels") or {})
        if manual:
            address = label_address(labels.get("real_ip"))
            if not address:
                log("%-9s %-20s manual, no real_ip label, skipped"
                    % (instance, host_name))
                continue
            source = "label"
        else:
            address = declared_address(instance)
            if not address:
                log("%-9s %-20s no declared address yet, skipped"
                    % (instance, host_name))
                continue
            source = "peer"
        if current == address and "real_ip" not in labels:
            log("%-9s %-20s %s (already set)" % (instance, host_name, address))
            continue
        new_labels = {k: v for k, v in labels.items() if k != "real_ip"}
        log("%-9s %-20s %s -> %s from %s%s"
            % (instance, host_name, current, address, source,
               " (dry run)" if args.dry_run else ""))
        if args.dry_run:
            changed += 1
            continue
        code, body = api.update(host_name,
                                {"ipaddress": address, "labels": new_labels})
        if code != 200:
            fail("update of %s failed: %s %s" % (host_name, code, body))
        changed += 1
    log("%d host(s) %s" % (changed, "to change" if args.dry_run else "updated"))
    if changed and not args.dry_run and not args.no_activate:
        activate(args.site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
