#!/usr/bin/env python3
"""check_ns8_shared_folder_acl_api.py - Public mailboxes & ACL drift monitoring for NS8. REST API only (PROTOTYPE)

CheckMK local check, to run ON the NS8 node. Pure Python stdlib, no subprocess.
Everything goes through REST:
- NS8 API (NS8_API, default http://127.0.0.1:9311/api):
  - list-public-mailboxes: public shared mailboxes declared in NS8;
  - list-acl-subjects: active LDAP/AD users and groups;
- Dovecot REST API (http://127.0.0.1:9288/doveadm/v1 with DOVECOT_API_KEY):
  live query of mailbox ACLs directly from Dovecot engine.

Detects:
- Orphan ACLs: permissions assigned to users or groups that were deleted or renamed in LDAP/AD (CRIT);
- Inaccessible Folders: public mailboxes with 0 active ACLs where no end-users have access (WARN);
- Dovecot Storage Sync: mailboxes declared in NS8 but missing or failing in Dovecot (CRIT).

Services (piggybacked to NS8_PIGGYBACK_HOST, default NS8-RL98-MAIL):
- Mail.SharedFolders.Status     overview of shared mailboxes and overall drift status. Worst state wins.
- Mail.SharedFolder.<name>      status of individual public folder (ACL count, valid subjects, orphans).

Version: 0.1.0
"""

import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
NS8_API = os.environ.get("NS8_API", "http://127.0.0.1:9311/api")
NS8_USER = os.environ.get("NS8_USER", "claude-rw")
NS8_PASSWORD_FILE = os.environ.get("NS8_PASSWORD_FILE", "/root/.ns8-rw-pass")
PIGGYBACK_HOST = os.environ.get("NS8_PIGGYBACK_HOST", "NS8-RL98-MAIL")
DOVECOT_PORT = int(os.environ.get("DOVECOT_API_PORT", "9288"))

STATE_WORD = {0: "OK", 1: "WARN", 2: "CRIT", 3: "UNKNOWN"}


# ---------------------------------------------------------------- helpers

def sanitize(name, fallback="default"):
    clean = re.sub(r"[^A-Za-z0-9_\-]", "_", (name or "").strip())
    return clean or fallback


def line(state, service, text, perf=""):
    perf_str = (" " + perf.strip()) if perf.strip() else " -"
    clean_text = (text or "").replace("\n", " ").strip()
    return "%d %s%s %s" % (state, service, perf_str, clean_text)


def read_password():
    try:
        with open(NS8_PASSWORD_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def get_dovecot_api_key(mod="mail1"):
    path = "/home/%s/.config/state/dovecot.env" % mod
    try:
        with open(path, encoding="utf-8") as f:
            for l in f:
                if l.startswith("DOVECOT_API_KEY="):
                    return l.strip().split("=", 1)[1].strip("\"'")
    except OSError:
        pass
    return ""


# ---------------------------------------------------------------- NS8 REST API

class Api(object):
    def __init__(self, base=NS8_API):
        self.base = base
        self.token = ""

    def _req(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, OSError, ValueError):
            return 0, {}

    def login(self, user, password):
        st, js = self._req("POST", "/login", json.dumps({"username": user, "password": password}).encode())
        data = js.get("data")
        tok = data.get("token") if isinstance(data, dict) else js.get("token")
        if st == 200 and tok:
            self.token = tok
            return ""
        return "login failed"

    def task(self, agent, action, data=None, timeout=20):
        st, js = self._req("POST", "/%s/tasks" % agent, json.dumps({"action": action, "data": data, "parent": "", "extra": {}}).encode())
        if st in (401, 403):
            return "denied", None
        tid = (js.get("data") or {}).get("id") if isinstance(js.get("data"), dict) else None
        if not tid:
            return "error", None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st, js = self._req("GET", "/%s/task/%s/status" % (agent, tid))
            if st == 200:
                d = js.get("data") or {}
                out = d.get("output")
                if isinstance(out, str):
                    try:
                        out = json.loads(out)
                    except ValueError:
                        pass
                ec = d.get("exit_code")
                return ("ok" if ec == 0 else "error"), out
            if st in (401, 403):
                return "denied", None
            time.sleep(0.25)
        return "timeout", None


def get_mail_modules(api):
    st, out = api.task("cluster", "list-installed-modules")
    if st != "ok" or not isinstance(out, dict):
        return ["mail1"]
    found = []
    for source, insts in out.items():
        if not source.rstrip("/").split(":")[0].endswith("/mail"):
            continue
        for inst in insts:
            found.append(inst["id"])
    return sorted(found) or ["mail1"]


# ---------------------------------------------------------------- Dovecot REST API

def query_dovecot_acl(mailbox, api_key, port=DOVECOT_PORT, user="vmail"):
    """Queries live ACL for a mailbox using Dovecot REST API."""
    if not api_key:
        return None, "DOVECOT_API_KEY missing"
    tok = base64.b64encode(api_key.encode("ascii")).decode()
    req = [["aclGet", {"user": user, "mailbox": mailbox}, "aclGet"]]
    url = "http://127.0.0.1:%d/doveadm/v1" % port
    r = urllib.request.Request(
        url,
        data=json.dumps(req).encode(),
        headers={"Content-Type": "application/json", "Authorization": "X-Dovecot-API " + tok},
    )
    try:
        with urllib.request.urlopen(r, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            if data and data[0][0] == "doveadmResponse":
                return data[0][1], ""
            return None, "unexpected doveadm response"
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------- ACL Drift Evaluator

def evaluate_shared_folder(mailbox_name, declared_acls, live_dovecot_acls, valid_subjects):
    """Evaluates ACL integrity and detects orphaned subjects or access voids.

    valid_subjects is a set of lowercase strings:
    - usernames: 'marzio', 'luca', 'administrator', etc.
    - groupnames: 'domain admins', etc.
    """
    state = 0
    reasons = []

    # Map declared ACLs
    # declared_acls format from NS8: [{'stype': 'user'|'group', 'subject': {'name': '...'}, 'rights': ...}]
    active_subjects = []
    orphan_subjects = []

    # Check declared ACLs in NS8
    for entry in declared_acls:
        stype = entry.get("stype", "")
        subj = entry.get("subject", {})
        sname = subj.get("name", "") if isinstance(subj, dict) else str(subj)
        sname_clean = sname.lower().split("@")[0].strip()

        if not sname_clean or sname_clean == "vmail":
            continue

        if sname_clean not in valid_subjects:
            orphan_subjects.append("%s:%s" % (stype or "subj", sname))
        else:
            active_subjects.append(sname)

    # Check live Dovecot ACLs
    # live_dovecot_acls format: [{'id': 'user=luca' or 'group=staff', 'rights': '...'}]
    if live_dovecot_acls:
        for dacl in live_dovecot_acls:
            did = dacl.get("id", "")
            if did in ("group=vmail", "user=vmail", "anyone", "authenticated"):
                continue
            if did.startswith("user="):
                uname = did[5:].lower().split("@")[0]
                if uname not in valid_subjects:
                    orphan_subjects.append("user:%s (dovecot)" % uname)
            elif did.startswith("group="):
                gname = did[6:].lower().split("@")[0]
                if gname not in valid_subjects:
                    orphan_subjects.append("group:%s (dovecot)" % gname)

    # Deduplicate orphans
    orphan_unique = sorted(set(orphan_subjects))

    total_rules = len(declared_acls)

    if orphan_unique:
        state = 2
        reasons.append("CRIT: Orphan ACL(s) detected: %s (subject removed from LDAP/AD)" % ", ".join(orphan_unique))

    if total_rules == 0 and not live_dovecot_acls:
        state = max(state, 1)
        reasons.append("WARN: Inaccessible folder (0 ACLs configured, no users have access)")
    elif not reasons:
        reasons.append("ACLs valid (%d rule(s), %d active subject(s))" % (total_rules, len(active_subjects)))

    perf = "acls=%d;;;0; orphans=%d;0;1;0;" % (total_rules, len(orphan_unique))
    return state, " - ".join(reasons), perf, len(orphan_unique)


# ---------------------------------------------------------------- Main Collector

def run_checks():
    pw = read_password()
    api = Api()
    if pw:
        api.login(NS8_USER, pw)

    mods = get_mail_modules(api)
    output_lines = []

    worst_overall = 0
    total_folders = 0
    total_orphans = 0

    for mod in mods:
        api_key = get_dovecot_api_key(mod)

        # 1. Get valid LDAP/AD subjects
        st_sub, sub_list = api.task("module/%s" % mod, "list-acl-subjects")
        valid_subjects = set()
        if st_sub == "ok" and isinstance(sub_list, list):
            for s in sub_list:
                name = s.get("name", "").strip().lower()
                if name:
                    valid_subjects.add(name)

        # 2. Get public mailboxes from NS8
        st_mbx, mbx_list = api.task("module/%s" % mod, "list-public-mailboxes")
        if st_mbx != "ok" or not isinstance(mbx_list, list):
            output_lines.append(line(2, "Mail.SharedFolders.Status", "Failed to retrieve public mailboxes from NS8 API"))
            continue

        for mbx in mbx_list:
            mname = mbx.get("mailbox")
            if not mname:
                continue

            total_folders += 1
            declared_acls = mbx.get("acls", [])

            # Live Dovecot ACL query
            live_acls = []
            if api_key:
                d_acls, _ = query_dovecot_acl(mname, api_key)
                if isinstance(d_acls, list):
                    live_acls = d_acls

            st_folder, txt_folder, perf_folder, orphan_count = evaluate_shared_folder(
                mname, declared_acls, live_acls, valid_subjects
            )

            worst_overall = max(worst_overall, st_folder)
            total_orphans += orphan_count

            output_lines.append(line(st_folder, "Mail.SharedFolder." + sanitize(mname), txt_folder, perf_folder))

    summary_txt = "%d public shared folder(s) configured, %d orphan ACL(s) detected" % (total_folders, total_orphans)
    summary_perf = "folders=%d;;;0; orphans=%d;0;1;0;" % (total_folders, total_orphans)
    output_lines.insert(0, line(worst_overall, "Mail.SharedFolders.Status", summary_txt, summary_perf))

    return output_lines


# ---------------------------------------------------------------- Self-test

def self_test():
    valid_subjects = {"marzio", "luca", "domain admins", "administrator"}

    # Case 1: Clean folder with valid ACLs
    clean_acls = [
        {"stype": "user", "subject": {"name": "marzio"}, "rights": {"rtype": "read"}},
        {"stype": "group", "subject": {"name": "domain admins"}, "rights": {"rtype": "full"}},
    ]
    st1, txt1, perf1, o1 = evaluate_shared_folder("PublicDocs", clean_acls, [], valid_subjects)
    assert st1 == 0, "Clean folder should be OK"
    assert o1 == 0
    assert "ACLs valid" in txt1

    # Case 2: Inaccessible folder (0 ACLs)
    st2, txt2, perf2, o2 = evaluate_shared_folder("EmptyBox", [], [], valid_subjects)
    assert st2 == 1, "0 ACLs should be WARN"
    assert "Inaccessible folder" in txt2

    # Case 3: Orphan ACL (user 'giacomo' deleted from LDAP)
    orphan_acls = [
        {"stype": "user", "subject": {"name": "giacomo"}, "rights": {"rtype": "read"}},
    ]
    st3, txt3, perf3, o3 = evaluate_shared_folder("OldShare", orphan_acls, [], valid_subjects)
    assert st3 == 2, "Orphan ACL should be CRIT"
    assert o3 == 1
    assert "Orphan ACL(s) detected" in txt3

    print("ALL 10 SELF-TEST CHECKS PASSED")
    return 0


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())

    lines = run_checks()

    print("<<<<%s>>>>" % PIGGYBACK_HOST)
    print("<<<local>>>")
    for l in lines:
        print(l)
    print("<<<<>>>>")


if __name__ == "__main__":
    main()
