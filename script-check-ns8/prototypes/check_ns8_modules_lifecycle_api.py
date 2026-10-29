#!/usr/bin/python3
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check NS8 module updates (Layer 2) and inner container component lifecycle
# (Layer 3), 100% REST-only (NS8 cluster HTTP API + Podman Unix socket HTTP).
#
# Why this check exists alongside check_os_lifecycle and check_patch_posture:
# on an NS8 node, dnf only sees Layer 1 (the Rocky Linux host). A node can
# report "Rocky 9 supported until 2032, 0 rpm updates pending" while:
#   - Layer 2 (NS8 modules from Software Center) has pending module updates, or
#     cannot reach its repositories at all (NS8's list-updates silently returns
#     an empty list when repositories are unreachable);
#   - Layer 3 (the rootless Podman containers inside up-to-date NS8 modules)
#     runs end-of-life engines or base distributions (for example Redis 7.0,
#     MariaDB 10.6 past community EOL, Mattermost 10.11 past EOL, or an
#     Ubuntu 20.04 base image).
#
# The two layers have different owners, so this script emits two services:
#   - NS8.Modules.Updates   [PR.PS-02.2] -> sysadmin / operator action
#   - NS8.Modules.Lifecycle [PR.PS-02.1] -> vendor / supply-chain / CRA / risk
#
# Compatible with Python 3.9+ (Rocky Linux 9). No subprocess, no classes.

import datetime
import email.utils
import http.client
import json
import os
try:
    import pwd
except ImportError:
    pwd = None
import re
import socket
import sys
import time
import urllib.error
import urllib.request

VERSION = "1.0.0"

SVC_UPDATES = "NS8.Modules.Updates"
SVC_LIFECYCLE = "NS8.Modules.Lifecycle"
CTRL_UPDATES = "PR.PS-02.2"
CTRL_LIFECYCLE = "PR.PS-02.1"

NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-ro")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-ro-pass")
NS8_TOKEN_FILE = os.environ.get("NS8_TOKEN_FILE", "/root/.ns8-token-ro")
NODE_AGENT_ENV = "/var/lib/nethserver/node/state/agent.env"

# Layer 2 thresholds (days since a pending stable module update was first seen)
GRACE_DAYS = int(os.environ.get("CHECK_NS8_MOD_GRACE_DAYS", "7"))
SLA_DAYS = int(os.environ.get("CHECK_NS8_MOD_SLA_DAYS", "14"))
REPO_STALE_DAYS = int(os.environ.get("CHECK_NS8_REPO_STALE_DAYS", "7"))
API_CACHE_FILE = os.environ.get("NS8_MODULES_LIFECYCLE_CACHE", "/var/lib/ns8-modules-lifecycle-cache.json")
API_CACHE_TTL = int(os.environ.get("NS8_MODULES_LIFECYCLE_TTL", "1800"))

# Layer 3 thresholds
DATA_AS_OF = "2026-10-29"
STALE_AFTER_DAYS = 180
WARN_BEFORE_DAYS = int(os.environ.get("CHECK_NS8_EOL_WARN_DAYS", "180"))
IMAGE_WARN_AGE_DAYS = int(os.environ.get("CHECK_NS8_IMAGE_WARN_DAYS", "365"))
IMAGE_CRIT_AGE_DAYS = int(os.environ.get("CHECK_NS8_IMAGE_CRIT_DAYS", "730"))

STATE_CANDIDATES = (
    "/var/lib/check_mk_agent/ns8_modules_updates_state.json",
    "/var/tmp/ns8_modules_updates_state.json",
)

# Embedded lifecycle table for container engines, apps, and base OSes.
# Tuple: (end of standard/free security support, end of extended support or None).
# Dates verified against endoflife.date on DATA_AS_OF. Use "2099-12-31" for
# actively maintained current streams whose EOL date is not yet scheduled by
# the upstream project (e.g. current mainline nginx 1.30/1.31 or traefik 3.7).
COMPONENT_LIFECYCLE = {
    # Base OSes
    ("ubuntu", "18.04"): ("2023-05-31", "2028-04-26"),
    ("ubuntu", "20.04"): ("2025-05-31", "2030-04-23"),
    ("ubuntu", "22.04"): ("2027-06-01", "2032-04-21"),
    ("ubuntu", "24.04"): ("2029-05-31", "2034-04-25"),
    ("ubuntu", "26.04"): ("2031-05-29", "2036-04-23"),
    ("debian", "10"): ("2024-06-30", "2029-06-30"),
    ("debian", "11"): ("2026-08-31", "2031-06-30"),
    ("debian", "12"): ("2028-06-30", "2033-06-30"),
    ("debian", "13"): ("2030-06-30", "2035-06-30"),
    ("alpine", "3.18"): ("2025-05-09", None),
    ("alpine", "3.19"): ("2025-11-01", None),
    ("alpine", "3.20"): ("2026-04-01", None),
    ("alpine", "3.21"): ("2026-11-01", None),
    ("alpine", "3.22"): ("2027-05-01", None),
    ("alpine", "3.23"): ("2027-11-01", None),
    ("alpine", "3.24"): ("2028-06-01", None),
    # Databases & caches
    ("redis", "6.0"): ("2022-05-31", None),
    ("redis", "6.2"): ("2027-04-01", None),
    ("redis", "7.0"): ("2024-07-29", None),
    ("redis", "7.2"): ("2029-12-01", None),
    ("redis", "7.4"): ("2029-12-01", None),
    ("redis", "8.0"): ("2026-12-01", None),
    ("redis", "8.2"): ("2030-09-01", None),
    ("mariadb", "10.3"): ("2023-05-25", None),
    ("mariadb", "10.4"): ("2024-06-18", None),
    ("mariadb", "10.5"): ("2025-06-24", None),
    ("mariadb", "10.6"): ("2026-07-06", "2029-08-23"),
    ("mariadb", "10.11"): ("2028-02-16", None),
    ("mariadb", "11.4"): ("2029-05-29", "2033-01-16"),
    ("mariadb", "11.8"): ("2028-06-04", "2033-10-22"),
    ("postgresql", "12"): ("2024-11-21", None),
    ("postgresql", "13"): ("2025-11-13", None),
    ("postgresql", "14"): ("2026-11-12", None),
    ("postgresql", "15"): ("2027-11-11", None),
    ("postgresql", "16"): ("2028-11-09", None),
    ("postgresql", "17"): ("2029-11-08", None),
    ("postgresql", "18"): ("2030-11-14", None),
    # Web / proxy / collaboration engines
    ("mattermost", "10.5"): ("2025-11-15", None),
    ("mattermost", "10.11"): ("2026-08-15", None),
    ("mattermost", "10.12"): ("2025-12-15", None),
    ("mattermost", "11.0"): ("2026-01-15", None),
    ("mattermost", "11.7"): ("2027-05-15", None),
    ("mattermost", "11.10"): ("2026-11-15", None),
    ("mattermost", "11.11"): ("2026-12-15", None),
    ("mattermost", "12.0"): ("2027-01-15", None),
    ("nginx", "1.24"): ("2024-04-23", None),
    ("nginx", "1.26"): ("2025-04-23", None),
    ("nginx", "1.28"): ("2026-04-14", None),
    ("nginx", "1.29"): ("2026-05-13", None),
    ("nginx", "1.30"): ("2099-12-31", None),
    ("nginx", "1.31"): ("2099-12-31", None),
    ("traefik", "2.10"): ("2024-02-12", None),
    ("traefik", "2.11"): ("2026-09-07", None),
    ("traefik", "3.0"): ("2024-07-15", None),
    ("traefik", "3.5"): ("2025-11-07", None),
    ("traefik", "3.6"): ("2026-08-16", None),
    ("traefik", "3.7"): ("2099-12-31", None),
}

UBUNTU_CODENAMES = {
    "bionic": "18.04",
    "focal": "20.04",
    "jammy": "22.04",
    "noble": "24.04",
    "resolute": "26.04",
}

DEBIAN_CODENAMES = {
    "buster": "10",
    "bullseye": "11",
    "bookworm": "12",
    "trixie": "13",
}


## Useful

def parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def parse_http_date(value):
    """Parse an RFC 2822 HTTP Last-Modified header into a UTC datetime."""
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except (TypeError, ValueError, IndexError):
        return None


def get_local_node_id():
    try:
        with open(NODE_AGENT_ENV, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("AGENT_ID=node/"):
                    return line.strip().split("/", 1)[1]
    except OSError:
        pass
    return ""


def read_first_line(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


# The other NS8 checks on this node close their piggyback block with <<<<>>>>,
# after which no section is open. Emitting our own header keeps these lines
# inside the local section regardless of what ran before us.
LOCAL_SECTION = "<<<local:sep(0)>>>"


def local_line(state, service, perfdata, message):
    """Build one CheckMK local-check line: state, service, metrics (or -), detail."""
    return "%d %s %s %s" % (state, service, perfdata or "-", message)


def ns8_login():
    password = read_first_line(NS8_PASSWORD_FILE)
    if not password:
        return "", "no-credentials"
    body = json.dumps({"username": NS8_USER, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        "%s/login" % NS8_API.rstrip("/"),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        return "", "login-http-%d" % exc.code
    except (urllib.error.URLError, ValueError, OSError):
        return "", "api-unreachable"
    data = payload.get("data")
    token = data.get("token") if isinstance(data, dict) else payload.get("token")
    return (token or ""), ("" if token else "no-token")


def ns8_task_with_token(token, agent, action, timeout=25.0):
    base = NS8_API.rstrip("/")
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }
    body = json.dumps(
        {"action": action, "data": None, "parent": "", "extra": {"isNotificationHidden": True}}
    ).encode("utf-8")
    task_id = ""
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                "%s/%s/tasks" % (base, agent), data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                task_id = json.load(resp)["data"]["id"]
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 3:
                time.sleep(1.2 * (attempt + 1))
                continue
            if exc.code in (401, 403):
                return None, "auth-%d" % exc.code
            return None, "api-http-%d" % exc.code
        except (urllib.error.URLError, KeyError, ValueError, OSError):
            return None, "api-unreachable"

    deadline = time.monotonic() + timeout
    time.sleep(0.4)
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                "%s/%s/task/%s/status" % (base, agent, task_id), headers=headers
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)["data"]
            if data.get("exit_code") == 0:
                return data.get("output"), ""
            return None, "task-exit-%s" % data.get("exit_code")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                time.sleep(1.5)
                continue
            if exc.code != 400:  # 400 "redis: nil" means task is still running
                return None, "api-http-%d" % exc.code
        except (urllib.error.URLError, KeyError, ValueError, OSError):
            return None, "api-unreachable"
        time.sleep(0.5)
    return None, "task-timeout"


def ns8_task(agent, action, timeout=25.0):
    """Run a read-only NS8 task using the token file, falling back to login."""
    token = read_first_line(NS8_TOKEN_FILE)
    if token:
        out, err = ns8_task_with_token(token, agent, action, timeout=timeout)
        if not err.startswith("auth-"):
            return out, err
    token, login_err = ns8_login()
    if not token:
        return None, login_err
    return ns8_task_with_token(token, agent, action, timeout=timeout)


def cached_ns8_task(agent, action, timeout=25.0):
    """Cache cluster module queries for API_CACHE_TTL seconds so concurrent checks do not hit 429/503."""
    key = "%s|%s" % (agent, action)
    cache = {}
    try:
        with open(API_CACHE_FILE, encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    hit = cache.get(key)
    if isinstance(hit, dict) and (time.time() - hit.get("ts", 0)) <= API_CACHE_TTL:
        return hit.get("out"), ""
    out, err = ns8_task(agent, action, timeout=timeout)
    if err or out is None:
        if isinstance(hit, dict) and hit.get("out") is not None:
            return hit.get("out"), ""
        return out, err
    try:
        cache[key] = {"ts": time.time(), "out": out}
        tmp = "%s.%d.tmp" % (API_CACHE_FILE, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
        os.replace(tmp, API_CACHE_FILE)
    except OSError:
        pass
    return out, ""


def unix_get_json(sock_path, url_path, timeout=5.0):
    """Perform an HTTP GET over a Unix domain socket without classes or subprocess."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(sock_path)
        request_bytes = (
            "GET %s HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n" % url_path
        ).encode("ascii")
        sock.sendall(request_bytes)
        resp = http.client.HTTPResponse(sock)
        resp.begin()
        raw = resp.read()
        if resp.status != 200:
            return None
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass


## State file for Layer 2 ageing

def state_path():
    for path in STATE_CANDIDATES:
        parent = os.path.dirname(path)
        if os.path.isdir(parent) and os.access(parent, os.W_OK):
            return path
    return STATE_CANDIDATES[-1]


def load_state(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data.get("first_seen", {}) if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, first_seen):
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"first_seen": first_seen}, handle)
    except OSError:
        pass


def age_of_oldest(keys, first_seen, today):
    stamp = today.isoformat()
    updated = {}
    oldest = None
    for key in keys:
        seen = first_seen.get(key, stamp)
        updated[key] = seen
        seen_date = parse_date(seen) or today
        age = (today - seen_date).days
        if oldest is None or age > oldest:
            oldest = age
    return oldest, updated


## Layer 2: NS8 Module Updates (PR.PS-02.2)

def collect_module_updates(core_list, app_list, node_id=""):
    """Extract installed counts, stable updates, testing updates, and repo freshness.

    Returns dict with:
      installed_count, stable_updates [(id, cur, new)], testing_count,
      remote_repos_seen, newest_repo_dt
    """
    installed_count = 0
    stable_updates = []
    testing_count = 0
    remote_repos_seen = 0
    newest_repo_dt = None

    # Core modules from cluster/list-core-modules
    for pkg in core_list or []:
        for inst in pkg.get("instances") or []:
            inst_node = str(inst.get("node_id") or "")
            if node_id and inst_node and inst_node != str(node_id):
                continue
            installed_count += 1
            repo = inst.get("repository") or ""
            if repo and repo != "__local__":
                remote_repos_seen += 1
            upd = (inst.get("update") or "").strip()
            if upd:
                stable_updates.append((inst.get("id") or "core", inst.get("version") or "?", upd))

    # Application modules from cluster/list-modules
    for mod in app_list or []:
        repo = mod.get("repository") or ""
        if repo and repo != "__local__":
            remote_repos_seen += 1
            dt = parse_http_date(mod.get("repository_updated") or "")
            if dt is not None and (newest_repo_dt is None or dt > newest_repo_dt):
                newest_repo_dt = dt
        for inst in mod.get("installed") or []:
            inst_node = str(inst.get("node") or "")
            if node_id and inst_node and inst_node != str(node_id):
                continue
            installed_count += 1
        for upd_entry in mod.get("updates") or []:
            inst_node = str(upd_entry.get("node") or "")
            if node_id and inst_node and inst_node != str(node_id):
                continue
            stable_ver = (upd_entry.get("update") or "").strip()
            testing_ver = (upd_entry.get("testing_update") or "").strip()
            if stable_ver:
                stable_updates.append(
                    (upd_entry.get("id") or mod.get("id") or "?", upd_entry.get("version") or "?", stable_ver)
                )
            elif testing_ver:
                testing_count += 1

    return {
        "installed_count": installed_count,
        "stable_updates": stable_updates,
        "testing_count": testing_count,
        "remote_repos_seen": remote_repos_seen,
        "newest_repo_dt": newest_repo_dt,
    }


def evaluate_module_updates(summary, oldest_age, now_utc, first_run=False,
                            grace=None, sla=None, repo_stale_days=None):
    """Decide the Layer 2 verdict. Pure function for self-test."""
    grace = GRACE_DAYS if grace is None else grace
    sla = SLA_DAYS if sla is None else sla
    repo_stale_days = REPO_STALE_DAYS if repo_stale_days is None else repo_stale_days

    if summary is None:
        return 3, "-", "UNKNOWN: failed to query NS8 cluster module status"

    installed = summary["installed_count"]
    stable = summary["stable_updates"]
    testing = summary["testing_count"]
    repos_seen = summary["remote_repos_seen"]
    newest_dt = summary["newest_repo_dt"]

    count = len(stable)
    age_val = oldest_age or 0
    perf = "installed_modules=%d|pending_updates=%d|testing_updates=%d|oldest_days=%d" % (
        installed, count, testing, age_val,
    )

    # Guard against NS8's silent empty-update-list when repositories fail.
    if repos_seen == 0:
        return 3, perf, (
            "UNKNOWN: no remote Software Center repository metadata is loaded "
            "(repositories unreachable or disabled) - '0 pending updates' cannot be trusted"
        )

    repo_age_days = None
    if newest_dt is not None:
        repo_age_days = (now_utc - newest_dt).total_seconds() / 86400.0
        if repo_age_days > repo_stale_days:
            return 3, perf, (
                "UNKNOWN: Software Center repository metadata is %.1f days old "
                "(limit %d days) - refresh repositories before trusting 0 pending updates"
                % (repo_age_days, repo_stale_days)
            )

    if count == 0:
        extra = " (%d pre-release/testing ignored)" % testing if testing else ""
        age_note = ", repo metadata %.1fd old" % repo_age_days if repo_age_days is not None else ""
        return 0, perf, (
            "OK: all %d installed NS8 modules are on the latest stable release%s%s"
            % (installed, extra, age_note)
        )

    preview = ", ".join("%s %s->%s" % (i, cur, new) for i, cur, new in stable[:5])
    if count > 5:
        preview += " (+%d more)" % (count - 5)

    if first_run:
        return 1, perf, (
            "WARNING [%s]: %d NS8 module update%s pending (%s) - first run on this "
            "node, so how long they have been pending is not yet known; ageing starts now"
            % (CTRL_UPDATES, count, "" if count == 1 else "s", preview)
        )

    detail = "%d NS8 module update%s pending (%s), oldest first seen %d day%s ago" % (
        count, "" if count == 1 else "s", preview, age_val, "" if age_val == 1 else "s",
    )
    if age_val >= sla:
        return 2, perf, (
            "CRITICAL [%s]: %s - past the %d-day remediation deadline"
            % (CTRL_UPDATES, detail, sla)
        )
    if age_val >= grace:
        return 1, perf, (
            "WARNING [%s]: %s - deadline is %d days"
            % (CTRL_UPDATES, detail, sla)
        )
    return 0, perf, "OK: %s - within the %d-day grace period" % (detail, grace)


## Layer 3: Inner Container Component Lifecycle (PR.PS-02.1)

def parse_image_components(image_name, labels):
    """Extract [(product, cycle, source_hint)] from a container image tag & OCI labels."""
    found = []
    labels = labels or {}
    low_name = (image_name or "").lower()
    repo_part, _, tag_part = low_name.rpartition(":")
    if not repo_part:
        repo_part = low_name
        tag_part = ""
    short_image = repo_part.rsplit("/", 1)[-1]

    # 1. Engine version from the image name + tag (or OCI version label for vendor wrappers)
    ver_label = (labels.get("org.opencontainers.image.version") or "").strip()

    if short_image == "redis" or short_image.endswith("-redis"):
        m = re.match(r"^v?(\d+\.\d+)\.\d+", tag_part)
        if m:
            found.append(("redis", m.group(1), "%s:%s" % (short_image, tag_part)))

    elif short_image == "mariadb" or short_image.endswith("-mariadb"):
        # Official mariadb image has the version in the tag; nethvoice-mariadb
        # tags the module version and puts MariaDB's version in the OCI label.
        m = re.match(r"^v?(1[012]\.\d+)\.\d+", tag_part) or re.match(r"^v?(1[012]\.\d+)\.\d+", ver_label)
        if m:
            found.append(("mariadb", m.group(1), "%s (%s)" % (short_image, m.group(0))))

    elif short_image in ("postgres", "postgresql") or "timescaledb" in short_image or "pgvector" in short_image:
        m = re.search(r"(?:^|-)pg(\d+)(?:$|-)", tag_part) or re.match(r"^v?(\d+)\.\d+", tag_part)
        if m:
            found.append(("postgresql", m.group(1), "%s:%s" % (short_image, tag_part)))

    elif "mattermost" in short_image:
        m = re.match(r"^v?(\d+\.\d+)\.\d+", tag_part)
        if m:
            found.append(("mattermost", m.group(1), "%s:%s" % (short_image, tag_part)))

    elif short_image == "nginx":
        m = re.match(r"^v?(\d+\.\d+)\.\d+", tag_part)
        if m:
            found.append(("nginx", m.group(1), "nginx:%s" % tag_part))

    elif short_image == "traefik" and not repo_part.endswith("nethserver/traefik"):
        m = re.match(r"^v?(\d+\.\d+)\.\d+", tag_part)
        if m:
            found.append(("traefik", m.group(1), "traefik:%s" % tag_part))

    # 2. Base distribution from OCI labels or tag suffixes
    ref_name = (labels.get("org.opencontainers.image.ref.name") or "").strip().lower()
    base_name = (labels.get("org.opencontainers.image.base.name") or "").strip().lower()

    if ref_name == "ubuntu" and re.match(r"^\d{2}\.\d{2}$", ver_label):
        # Avoid false attribution when a downstream build overwrote version
        # with its own app version (only accept real Ubuntu YY.04/YY.10 cycles).
        if ver_label.endswith((".04", ".10")):
            found.append(("ubuntu", ver_label, "%s base ubuntu %s" % (short_image, ver_label)))

    for codename, cycle in UBUNTU_CODENAMES.items():
        if ("ubuntu:" + codename) in base_name or tag_part.endswith("-" + codename):
            found.append(("ubuntu", cycle, "%s base ubuntu %s" % (short_image, cycle)))
            break

    for codename, cycle in DEBIAN_CODENAMES.items():
        if ("debian:" + codename) in base_name or tag_part.endswith("-" + codename):
            found.append(("debian", cycle, "%s base debian %s" % (short_image, cycle)))
            break

    m_alp = re.search(r"alpine(\d+\.\d+)", tag_part)
    if m_alp:
        found.append(("alpine", m_alp.group(1), "%s base alpine %s" % (short_image, m_alp.group(1))))

    return found


def discover_module_images():
    """Query every rootless module's Podman socket and return a list of image records."""
    records = []
    run_user = "/run/user"
    if not os.path.isdir(run_user):
        return records
    try:
        entries = sorted(os.listdir(run_user))
    except OSError:
        return records

    for entry in entries:
        if not entry.isdigit():
            continue
        sock_path = os.path.join(run_user, entry, "podman", "podman.sock")
        if not os.path.exists(sock_path):
            continue
        uid = int(entry)
        try:
            module_name = pwd.getpwuid(uid).pw_name if pwd else ("uid-%d" % uid)
        except KeyError:
            module_name = "uid-%d" % uid
        images = unix_get_json(sock_path, "/v4.0.0/libpod/images/json")
        if not isinstance(images, list):
            continue
        for img in images:
            names = img.get("Names") or img.get("RepoTags") or []
            primary = names[0] if names else "<untagged>"
            records.append({
                "module": module_name,
                "image": primary,
                "created": img.get("Created"),
                "labels": img.get("Labels") or {},
            })
    return records


def evaluate_inner_lifecycle(records, today, table=None, data_as_of=DATA_AS_OF,
                             warn_before=None, img_warn_days=None, img_crit_days=None):
    """Evaluate Layer 3 records against COMPONENT_LIFECYCLE and image build age.

    Pure function so self_test() can exercise every branch."""
    table = COMPONENT_LIFECYCLE if table is None else table
    warn_before = WARN_BEFORE_DAYS if warn_before is None else warn_before
    img_warn_days = IMAGE_WARN_AGE_DAYS if img_warn_days is None else img_warn_days
    img_crit_days = IMAGE_CRIT_AGE_DAYS if img_crit_days is None else img_crit_days

    if not records:
        return 3, "-", "UNKNOWN: no rootless Podman module images found"

    crit_items = []
    warn_eol_items = []
    warn_age_items = []
    checked_components = 0
    oldest_image_days = 0

    for rec in records:
        mod = rec.get("module") or "?"
        img = rec.get("image") or "?"
        short_img = img.rsplit("/", 1)[-1]
        created = rec.get("created")
        img_age = None
        built_date = None
        if isinstance(created, (int, float)) and created > 0:
            built_date = datetime.datetime.fromtimestamp(created, datetime.timezone.utc).date()
            img_age = (today - built_date).days
            if img_age > oldest_image_days:
                oldest_image_days = img_age

        rec_flagged_eol = False
        for product, cycle, hint in parse_image_components(img, rec.get("labels")):
            entry = table.get((product, cycle))
            if entry is None:
                continue
            checked_components += 1
            eol = parse_date(entry[0])
            eoes = parse_date(entry[1]) if entry[1] else None
            if eol is None:
                continue
            left = (eol - today).days
            if left < 0:
                gone = -left
                rec_flagged_eol = True
                if eoes and today < eoes:
                    warn_eol_items.append(
                        "%s: %s left standard support on %s (%dd ago, extended until %s)"
                        % (mod, hint, eol, gone, eoes)
                    )
                else:
                    age_suffix = ", image built %dd ago" % img_age if (img_age and img_age >= img_warn_days) else ""
                    crit_items.append(
                        "%s: %s EOL on %s (%dd ago%s)" % (mod, hint, eol, gone, age_suffix)
                    )
            elif left <= warn_before:
                rec_flagged_eol = True
                warn_eol_items.append(
                    "%s: %s reaches EOL on %s (%dd left)" % (mod, hint, eol, left)
                )

        # Fall back to build age only when the image was not already flagged by
        # a more specific component lifecycle rule, so one container is not
        # double-counted in eol_critical.
        if not rec_flagged_eol and img_age is not None:
            if img_age >= img_crit_days:
                crit_items.append(
                    "%s/%s built %d days ago (%s)" % (mod, short_img, img_age, built_date)
                )
            elif img_age >= img_warn_days:
                warn_age_items.append(
                    "%s/%s built %d days ago (%s)" % (mod, short_img, img_age, built_date)
                )

    warn_items = warn_eol_items + warn_age_items

    perf = "images_scanned=%d|components_checked=%d|eol_critical=%d|eol_warning=%d|oldest_image_days=%d" % (
        len(records), checked_components, len(crit_items), len(warn_items), oldest_image_days,
    )

    # CheckMK rewrites ";" inside a local-check summary (it separates perfdata
    # fields), so items are joined with " | " to stay readable in the GUI.
    if crit_items:
        all_issues = crit_items + warn_items
        preview = " | ".join(all_issues[:5])
        if len(all_issues) > 5:
            preview += " (+%d more)" % (len(all_issues) - 5)
        return 2, perf, (
            "CRITICAL [%s]: %d end-of-life or ancient inner component%s across NS8 modules "
            "(+%d warning) - %s"
            % (CTRL_LIFECYCLE, len(crit_items), "" if len(crit_items) == 1 else "s", len(warn_items), preview)
        )

    if warn_items:
        preview = " | ".join(warn_items[:5])
        if len(warn_items) > 5:
            preview += " (+%d more)" % (len(warn_items) - 5)
        return 1, perf, (
            "WARNING [%s]: %d inner component%s on extended support or approaching EOL - %s"
            % (CTRL_LIFECYCLE, len(warn_items), "" if len(warn_items) == 1 else "s", preview)
        )

    # Guard against a stale embedded table claiming everything is still supported.
    refreshed = parse_date(data_as_of)
    if refreshed is None or (today - refreshed).days > STALE_AFTER_DAYS:
        return 3, perf, (
            "UNKNOWN: embedded component lifecycle table is stale (DATA_AS_OF=%s) - redeploy this check"
            % data_as_of
        )

    return 0, perf, (
        "OK: %d inner container images (%d versioned components) supported, oldest image built %d days ago"
        % (len(records), checked_components, oldest_image_days)
    )


## Self-test

def self_test():
    today = datetime.date(2026, 10, 29)
    now_utc = datetime.datetime(2026, 10, 29, 12, 0, tzinfo=datetime.timezone.utc)
    fresh_dt = datetime.datetime(2026, 10, 29, 6, 0, tzinfo=datetime.timezone.utc)
    stale_dt = datetime.datetime(2026, 10, 1, 6, 0, tzinfo=datetime.timezone.utc)

    failures = 0

    def expect(name, cond, detail=""):
        nonlocal failures
        if not cond:
            failures += 1
        print("%s  %s" % ("PASS" if cond else "FAIL", name))
        if not cond and detail:
            print("      %s" % detail)

    # Layer 2 tests
    s_clean = {
        "installed_count": 12,
        "stable_updates": [],
        "testing_count": 3,
        "remote_repos_seen": 2,
        "newest_repo_dt": fresh_dt,
    }
    st, _, msg = evaluate_module_updates(s_clean, 0, now_utc)
    expect("L2: clean node ignores testing updates and reports OK",
           st == 0 and "3 pre-release/testing ignored" in msg, msg)

    s_norepo = dict(s_clean, remote_repos_seen=0)
    st, _, msg = evaluate_module_updates(s_norepo, 0, now_utc)
    expect("L2: unreachable repositories downgrade 0 updates to UNKNOWN",
           st == 3 and "cannot be trusted" in msg, msg)

    s_stale_repo = dict(s_clean, newest_repo_dt=stale_dt)
    st, _, msg = evaluate_module_updates(s_stale_repo, 0, now_utc)
    expect("L2: stale repository metadata downgrades 0 updates to UNKNOWN",
           st == 3 and "metadata is" in msg, msg)

    s_pending = dict(s_clean, stable_updates=[("mail1", "1.9.0", "1.9.1")])
    st, _, msg = evaluate_module_updates(s_pending, 0, now_utc, first_run=True)
    expect("L2: first run with pending module update warns instead of OK",
           st == 1 and "first run" in msg, msg)

    st, _, msg = evaluate_module_updates(s_pending, 3, now_utc, first_run=False)
    expect("L2: pending module update inside grace period is OK",
           st == 0 and "grace period" in msg, msg)

    st, _, msg = evaluate_module_updates(s_pending, 10, now_utc, first_run=False)
    expect("L2: pending module update past grace is WARNING",
           st == 1 and "deadline is" in msg, msg)

    st, _, msg = evaluate_module_updates(s_pending, 20, now_utc, first_run=False)
    expect("L2: pending module update past SLA is CRITICAL",
           st == 2 and "remediation deadline" in msg, msg)

    # Layer 3 tests (using real image shapes found on NS8-RL98)
    real_like = [
        {
            "module": "nethvoice1",
            "image": "docker.io/library/redis:7.0.10-alpine",
            "created": 1680141928,  # 2023-03-30
            "labels": {},
        },
        {
            "module": "mattermost1",
            "image": "docker.io/mattermost/mattermost-team-edition:10.11.24",
            "created": 1760000000,
            "labels": {},
        },
        {
            "module": "nextcloud1",
            "image": "docker.io/library/mariadb:10.6.28",
            "created": 1760000000,
            "labels": {"org.opencontainers.image.base.name": "docker.io/library/ubuntu:jammy"},
        },
        {
            "module": "nethvoice-proxy2",
            "image": "ghcr.io/nethesis/nethvoice-proxy-kamailio:1.7.4",
            "created": 1760000000,
            "labels": {
                "org.opencontainers.image.ref.name": "ubuntu",
                "org.opencontainers.image.version": "20.04",
            },
        },
    ]
    st, _, msg = evaluate_inner_lifecycle(real_like, today)
    expect("L3: detects EOL Redis 7.0 + Mattermost 10.11 and extended-only MariaDB 10.6 + Ubuntu 20.04",
           st == 2 and "redis:7.0.10-alpine EOL" in msg and "mattermost" in msg, msg)

    only_warn = real_like[2:]  # MariaDB 10.6 + Ubuntu 20.04 base
    st, _, msg = evaluate_inner_lifecycle(only_warn, today)
    expect("L3: extended-support-only inner components report WARNING",
           st == 1 and "mariadb" in msg and "ubuntu 20.04" in msg, msg)

    healthy = [
        {
            "module": "mattermost1",
            "image": "docker.io/library/postgres:17.11-alpine",
            "created": int(datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc).timestamp()),
            "labels": {},
        },
        {
            "module": "nextcloud1",
            "image": "docker.io/library/redis:7.4.5-alpine",
            "created": int(datetime.datetime(2026, 9, 1, tzinfo=datetime.timezone.utc).timestamp()),
            "labels": {},
        },
    ]
    st, _, msg = evaluate_inner_lifecycle(healthy, today)
    expect("L3: healthy modern inner components report OK",
           st == 0 and "supported" in msg, msg)

    st, _, msg = evaluate_inner_lifecycle(healthy, today, data_as_of="2025-01-01")
    expect("L3: stale embedded table downgrades OK to UNKNOWN",
           st == 3 and "stale" in msg, msg)

    total = 11
    print("\n%d/%d passed" % (total - failures, total))
    sys.exit(1 if failures else 0)


## Check

def check():
    print(LOCAL_SECTION)
    today = datetime.date.today()
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    node_id = get_local_node_id()

    # --- Service 1: NS8.Modules.Updates (Layer 2) ---
    core_list, err_core = cached_ns8_task("cluster", "list-core-modules")
    app_list, err_app = cached_ns8_task("cluster", "list-modules")
    if err_core or err_app or core_list is None or app_list is None:
        why = err_core or err_app or "empty-response"
        print(local_line(3, SVC_UPDATES, "-", "UNKNOWN: NS8 cluster API query failed (%s)" % why))
    else:
        summary = collect_module_updates(core_list, app_list, node_id=node_id)
        oldest = None
        first_run = False
        if summary["stable_updates"]:
            keys = ["%s:%s" % (i, new) for i, _cur, new in summary["stable_updates"]]
            path = state_path()
            prior = load_state(path)
            first_run = not prior
            oldest, updated = age_of_oldest(keys, prior, today)
            save_state(path, updated)
        st, perf, msg = evaluate_module_updates(
            summary, oldest, now_utc, first_run=first_run
        )
        print(local_line(st, SVC_UPDATES, perf, msg))

    # --- Service 2: NS8.Modules.Lifecycle (Layer 3) ---
    records = discover_module_images()
    st3, perf3, msg3 = evaluate_inner_lifecycle(records, today)
    print(local_line(st3, SVC_LIFECYCLE, perf3, msg3))


if "--self-test" in sys.argv:
    self_test()
else:
    check()
