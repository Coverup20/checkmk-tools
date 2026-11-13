#!/usr/bin/env python3
"""install_udp_punch.py - local installer for a UDP punch tunnel peer

Installs one side of the tunnel on the machine where it runs: the peer code,
the JSON configuration, the pre-shared key and the systemd unit. Nothing is
sent to the other peer, so each side is installed on its own.

Usage:
    install_udp_punch.py install --role server --unix-owner USER --stun-server HOST:PORT [...]
    install_udp_punch.py install --role host --stun-server HOST:PORT [--target-command CMD]
    install_udp_punch.py uninstall --role server|host [--purge]
    install_udp_punch.py status --role server|host

With a terminal on stdin the install and uninstall commands ask for the
values they need, showing the default in brackets; every option can also be
passed on the command line, which is what happens with --non-interactive or
when stdin is not a terminal. --yes skips the final confirmation.

A --root directory installs everything under that directory instead of /,
skips systemctl and skips the user lookup, so an installation can be
rehearsed without touching the running system.

Version: 1.1.0"""

import argparse
import hashlib
import importlib
import json
import os
import pwd
import shutil
import subprocess
import sys
import time
from pathlib import Path

VERSION = "1.1.0"

HERE = Path(__file__).resolve().parent
CODE_DIR = "/opt/cmk-punch"
CONF_DIR = "/etc/cmk-punch"
STATE_DIR = "/var/lib/cmk-punch"
AGENT_DIR = "/usr/local/lib/cmk-punch"
UNITS_DIR = "/etc/systemd/system"

TOOLSET: tuple[str, ...] = ("protocol.py", "punch_peer.py")
AGENT_CLIENT = "cmk_punch_agent.py"
CONFIG_NAME = {"server": "server.json", "host": "host.json"}
UNIT_NAME = {"server": "cmk-punch-server.service",
             "host": "cmk-punch-host.service"}
UNIT_DESC = {"server": "CheckMK UDP punch server",
             "host": "CheckMK UDP punch host"}
DEFAULT_UDP_BIND = "0.0.0.0:6015"
DEFAULT_SOCKET = "/run/cmk-punch/agent.sock"
DEFAULT_TARGET = "/usr/bin/check_mk_agent"


def log(msg):
    print("[INFO] %s" % msg)


def warn(msg):
    print("[WARN] %s" % msg, file=sys.stderr)


def fail(msg):
    print("[ERROR] %s" % msg, file=sys.stderr)
    raise SystemExit(1)


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        fail("%s failed: %s" % (" ".join(cmd), detail))
    return result


def run_optional(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def resolve(root, path):
    return Path(path) if root == "/" else Path(root.rstrip("/") + path)


def is_staged(args):
    return args.root != "/"


def interactive(args):
    return sys.stdin.isatty() and not getattr(args, "non_interactive", False)


def ask(prompt, default=None, required=False):
    shown = " [%s]" % default if default else ""
    while True:
        try:
            value = input("%s%s: " % (prompt, shown)).strip()
        except EOFError:
            fail("no input available: pass the options on the command line")
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("  a value is required")


def ask_bool(prompt, default=False):
    shown = "Y/n" if default else "y/N"
    while True:
        try:
            value = input("%s [%s]: " % (prompt, shown)).strip().lower()
        except EOFError:
            fail("no input available: pass the options on the command line")
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  answer y or n")


def require_root(args):
    if not is_staged(args) and os.geteuid() != 0:
        fail("this installer needs root (or use --root DIR for a staged install)")


def check_python_module():
    try:
        importlib.import_module("cryptography")
    except ImportError:
        fail("python3-cryptography is missing: apt install python3-cryptography")


def check_sources(role):
    names = list(TOOLSET)
    if role == "server":
        names.append(AGENT_CLIENT)
    for name in names:
        if not (HERE / name).is_file():
            fail("%s is missing next to this installer" % name)
    for name in TOOLSET:
        run([sys.executable, "-B", "-c",
             "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')",
             str(HERE / name)])
    log("toolset sources verified (%s)" % ", ".join(names))


def backup(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = path.with_name("%s.bak-%s" % (path.name, stamp))
    shutil.copy2(path, dest)
    log("backed up %s as %s" % (path, dest.name))


def paths(root, role):
    conf = resolve(root, CONF_DIR)
    return {
        "code": resolve(root, CODE_DIR),
        "conf": conf,
        "state": resolve(root, STATE_DIR),
        "agent": resolve(root, AGENT_DIR),
        "config": conf / CONFIG_NAME[role],
        "psk": conf / "psk",
        "peer": conf / "peer.json",
        "unit": resolve(root, UNITS_DIR) / UNIT_NAME[role],
    }


def split_list(value):
    return [item.strip() for item in value.split(",") if item.strip()]


def fill_install(args):
    if not args.role:
        args.role = ask("Role (server or host)", "server")
    if args.role not in ("server", "host"):
        fail("role must be server or host")
    args.stun_server = ask("STUN server, empty to disable",
                          args.stun_server or "stun.l.google.com:19302")
    args.udp_bind = ask("UDP bind address",
                        args.udp_bind or DEFAULT_UDP_BIND)
    hint = " (empty: learned from the handshake)" if args.role == "server" else ""
    args.peer = ask("Peer endpoint host:port" + hint, args.peer)
    if args.role == "server":
        args.unix_listen = ask("UNIX socket path, empty for none",
                               args.unix_listen or DEFAULT_SOCKET)
        if args.unix_listen:
            args.unix_owner = ask("CheckMK site user that owns the socket",
                                  args.unix_owner, required=True)
        args.tcp_listen = ask("TCP listen address, empty for none",
                              args.tcp_listen)
        if not args.allowed_uid:
            raw = ask("Allowed uids, comma separated, empty to use the "
                      "site user", "")
            args.allowed_uid = split_list(raw) or None
        if args.tcp_listen and not args.allowed_exe:
            raw = ask("Allowed executables, comma separated", "")
            args.allowed_exe = split_list(raw) or None
        while True:
            answer = ask("Rate limit packets per second, empty for the default",
                         str(int(args.rate_limit_pps))
                         if args.rate_limit_pps else "")
            if not answer:
                args.rate_limit_pps = None
                break
            try:
                args.rate_limit_pps = float(answer)
                break
            except ValueError:
                print("  a number is required")
    else:
        args.target = ask("TCP target host:port, empty to run a command",
                          args.target)
        if not args.target:
            args.target_command = ask("Command to run for each stream",
                                      args.target_command or DEFAULT_TARGET)
    p = paths(args.root, args.role)
    if p["psk"].exists():
        print("  existing PSK %s will be reused" % p["psk"])
    elif not args.psk_file:
        choice = ask("PSK: generate a new one or copy from a file? (g/c)", "g")
        if choice.lower().startswith("c"):
            args.psk_file = ask("PSK file to copy", "", required=True)


def show_plan(role, args):
    print()
    print("  role:       %s" % role)
    print("  udp bind:   %s" % args.udp_bind)
    print("  stun:       %s" % (args.stun_server or "disabled"))
    print("  peer:       %s" % (args.peer or "(learned from the handshake)"))
    if role == "server":
        print("  socket:     %s" % (args.unix_listen or "(none)"))
        if args.unix_listen:
            print("  socket user: %s" % args.unix_owner)
        print("  tcp listen: %s" % (args.tcp_listen or "(none)"))
        print("  allowed:    %s" % (", ".join(args.allowed_uid or [])
                                    or "(site user)"))
    else:
        print("  target:     %s" % (args.target
                                    or args.target_command or DEFAULT_TARGET))
    print()


def check_server_users(args):
    if not args.unix_listen:
        return
    if not args.unix_owner:
        fail("--unix-owner is required with --unix-listen")
    if is_staged(args):
        return
    try:
        pwd.getpwnam(args.unix_owner)
    except KeyError:
        fail("user %s does not exist on this host" % args.unix_owner)


def install_psk(args, p):
    p["conf"].mkdir(parents=True, exist_ok=True)
    psk = p["psk"]
    if psk.exists():
        log("reusing the existing PSK %s" % psk)
        return psk
    if args.psk_file:
        text = Path(args.psk_file).read_text(encoding="ascii").strip()
        if len(text) != 64 or any(c not in "0123456789abcdefABCDEF" for c in text):
            fail("--psk-file must contain 32 bytes as hex")
        psk.write_text(text.lower() + "\n", encoding="ascii")
        log("copied the PSK from %s" % args.psk_file)
    else:
        psk.write_text(os.urandom(32).hex() + "\n", encoding="ascii")
        log("generated a new PSK")
    os.chmod(psk, 0o600)
    return psk


def build_config(role, args, p):
    cfg = {"role": role, "psk_file": str(p["psk"]), "udp_bind": args.udp_bind}
    if args.stun_server:
        cfg["stun_server"] = args.stun_server
    cfg["peer_file"] = str(p["peer"])
    cfg["state_dir"] = str(p["state"])
    if role == "server":
        if args.unix_listen:
            cfg["unix_listen"] = str(resolve(args.root, args.unix_listen))
            cfg["unix_mode"] = args.unix_mode
            cfg["unix_owner"] = args.unix_owner
        if args.tcp_listen:
            cfg["tcp_listen"] = args.tcp_listen
        allowed = list(args.allowed_uid or [])
        if not allowed and args.unix_owner:
            allowed = [args.unix_owner]
        if allowed:
            cfg["allowed_uids"] = allowed
        if args.allowed_exe:
            cfg["allowed_exe"] = list(args.allowed_exe)
        if args.rate_limit_pps is not None:
            cfg["rate_limit_pps"] = args.rate_limit_pps
        if cfg.get("tcp_listen") and not cfg.get("allowed_uids") \
                and not cfg.get("allowed_exe"):
            fail("tcp_listen requires --allowed-uid or --allowed-exe")
    else:
        if args.target:
            cfg["target"] = args.target
        elif args.target_command:
            cfg["target_command"] = args.target_command
        else:
            fail("the host role needs --target-command or --target")
    cfg["keepalive_s"] = args.keepalive
    cfg["punch_interval_s"] = args.punch_interval
    if role == "server":
        cfg["restun_max_interval_s"] = args.restun_max
        cfg["restun_interval_s"] = args.restun
    return cfg


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o644)


def install_config(config, args, p):
    if p["config"].exists():
        if not args.force:
            fail("%s exists, use --force to replace it (a backup is kept)"
                 % p["config"])
        backup(p["config"])
    write_json(p["config"], config)
    log("wrote %s" % p["config"])


def install_peer_file(args, p):
    if not args.peer:
        return
    if p["peer"].exists():
        try:
            old = json.loads(p["peer"].read_text(encoding="utf-8"))
        except ValueError:
            old = {}
        if old.get("peer") != args.peer:
            backup(p["peer"])
    write_json(p["peer"], {"peer": args.peer})
    log("wrote %s" % p["peer"])


def install_code(role, args, p):
    p["code"].mkdir(parents=True, exist_ok=True)
    for name in TOOLSET:
        target = p["code"] / name
        if target.exists():
            backup(target)
        shutil.copyfile(HERE / name, target)
        os.chmod(target, 0o644)
    if role == "server":
        p["agent"].mkdir(parents=True, exist_ok=True)
        target = p["agent"] / AGENT_CLIENT
        if target.exists():
            backup(target)
        shutil.copyfile(HERE / AGENT_CLIENT, target)
        os.chmod(target, 0o755)
    log("installed the peer code in %s" % p["code"])


def unit_text(role, p):
    return """[Unit]
Description=%s
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=%s
ExecStart=/usr/bin/python3 %s/punch_peer.py --config %s
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
""" % (UNIT_DESC[role], p["code"], p["code"], p["config"])


def install_unit(role, args, p):
    p["unit"].parent.mkdir(parents=True, exist_ok=True)
    p["unit"].write_text(unit_text(role, p), encoding="utf-8")
    os.chmod(p["unit"], 0o644)
    log("wrote %s" % p["unit"])


def start_unit(role, args):
    if is_staged(args):
        log("staged install: skipping systemctl")
        return
    run(["systemctl", "daemon-reload"])
    if args.no_start:
        log("unit written, not enabled or started (--no-start)")
        return
    run(["systemctl", "enable", UNIT_NAME[role]])
    run(["systemctl", "restart", UNIT_NAME[role]])
    state = run_optional(["systemctl", "is-active", UNIT_NAME[role]]).stdout.strip()
    log("%s is %s" % (UNIT_NAME[role], state or "unknown"))


def print_summary(role, args, p):
    digest = hashlib.sha256(p["psk"].read_bytes()).hexdigest()
    print()
    log("installation complete for the %s role" % role)
    print("  code:       %s" % p["code"])
    print("  config:     %s" % p["config"])
    print("  psk:        %s (mode 600)" % p["psk"])
    print("  psk sha256: %s" % digest)
    print()
    print("  Copy the psk file to the other peer and install it there with")
    print("  --psk-file PATH, then write the peer endpoint on both sides.")
    if role == "server":
        config = json.loads(p["config"].read_text(encoding="utf-8"))
        unix = config.get("unix_listen") or ""
        print()
        print("  CheckMK rule for the monitored host:")
        print("    rule:         Individual program call instead of agent access")
        print("    command line: /usr/bin/python3 %s/%s %s"
              % (p["agent"], AGENT_CLIENT, unix))
        print("  The peer endpoint is read from %s at every start." % p["peer"])


def install(args):
    require_root(args)
    if not args.role and not interactive(args):
        fail("--role is required (or run interactively)")
    if interactive(args):
        fill_install(args)
    args.udp_bind = args.udp_bind or DEFAULT_UDP_BIND
    if args.role == "server" and args.unix_listen is None:
        args.unix_listen = DEFAULT_SOCKET
    if args.role == "host" and not args.target and not args.target_command:
        args.target_command = DEFAULT_TARGET
    check_python_module()
    check_sources(args.role)
    if args.role == "server":
        check_server_users(args)
    p = paths(args.root, args.role)
    if p["config"].exists() and not args.force:
        fail("%s exists, use --force to replace it (a backup is kept)"
             % p["config"])
    config = build_config(args.role, args, p)
    if interactive(args) and not args.yes:
        show_plan(args.role, args)
        if not ask_bool("Proceed with the installation", True):
            log("aborted")
            return
    install_psk(args, p)
    install_code(args.role, args, p)
    install_config(config, args, p)
    install_peer_file(args, p)
    install_unit(args.role, args, p)
    start_unit(args.role, args)
    print_summary(args.role, args, p)


def uninstall(role, args):
    require_root(args)
    if not role and not interactive(args):
        fail("--role is required (or run interactively)")
    if not role:
        role = ask("Role (server or host)", "server")
    if interactive(args) and not args.yes:
        if not ask_bool("Remove the %s peer on this machine" % role, False):
            log("aborted")
            return
        if not args.purge:
            args.purge = ask_bool("Also delete configuration, PSK and state",
                                  False)
    p = paths(args.root, role)
    if not is_staged(args):
        run_optional(["systemctl", "disable", "--now", UNIT_NAME[role]])
    if p["unit"].exists():
        p["unit"].unlink()
        log("removed %s" % p["unit"])
    if not is_staged(args):
        run_optional(["systemctl", "daemon-reload"])
    for name in TOOLSET:
        target = p["code"] / name
        if target.exists():
            target.unlink()
    cache = p["code"] / "__pycache__"
    if cache.is_dir():
        shutil.rmtree(cache)
    if role == "server":
        target = p["agent"] / AGENT_CLIENT
        if target.exists():
            target.unlink()
    log("removed the peer code")
    if args.purge:
        for path in (p["conf"], p["state"]):
            if path.is_dir():
                shutil.rmtree(path)
                log("removed %s" % path)
    else:
        log("kept %s and %s (use --purge to remove them)"
            % (p["conf"], p["state"]))


def status(role, args):
    p = paths(args.root, role)
    print("role:  %s" % role)
    print("root:  %s" % args.root)
    if not is_staged(args):
        state = run_optional(["systemctl", "is-active", UNIT_NAME[role]]).stdout.strip()
        print("unit:  %s (%s)" % (UNIT_NAME[role], state or "not installed"))
    for key in ("code", "config", "psk", "peer", "unit"):
        path = p[key]
        if path.exists():
            mode = path.stat().st_mode & 0o777
            print("%-7s %s (%o)" % (key, path, mode))
        else:
            print("%-7s %s (missing)" % (key, path))


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default="/",
                        help="install under DIR instead of / (staging)")
    common.add_argument("--non-interactive", action="store_true",
                        help="never ask, use the flags and the defaults")
    common.add_argument("--yes", action="store_true",
                        help="skip the final confirmation")
    parser = argparse.ArgumentParser(
        description="Local installer for a UDP punch tunnel peer (v%s)" % VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    inst = sub.add_parser("install", parents=[common], help="install one peer")
    inst.add_argument("--role", choices=("server", "host"))
    inst.add_argument("--stun-server", default="", metavar="HOST:PORT")
    inst.add_argument("--udp-bind", default=None, metavar="HOST:PORT")
    inst.add_argument("--peer", default="", metavar="HOST:PORT")
    inst.add_argument("--psk-file", default="", metavar="PATH")
    inst.add_argument("--force", action="store_true")
    inst.add_argument("--no-start", action="store_true")
    inst.add_argument("--keepalive", type=float, default=15.0)
    inst.add_argument("--punch-interval", type=float, default=1.0)
    inst.add_argument("--restun", type=float, default=300.0)
    inst.add_argument("--restun-max", type=float, default=1800.0)
    inst.add_argument("--unix-listen", default=None, metavar="PATH")
    inst.add_argument("--unix-mode", default="0660")
    inst.add_argument("--unix-owner", default=None, metavar="USER")
    inst.add_argument("--tcp-listen", default="", metavar="HOST:PORT")
    inst.add_argument("--allowed-uid", action="append", default=None, metavar="USER")
    inst.add_argument("--allowed-exe", action="append", default=None, metavar="PATH")
    inst.add_argument("--rate-limit-pps", type=float, default=None)
    inst.add_argument("--target-command", default=None, metavar="CMD")
    inst.add_argument("--target", default="", metavar="HOST:PORT")

    un = sub.add_parser("uninstall", parents=[common], help="remove one peer")
    un.add_argument("--role", choices=("server", "host"))
    un.add_argument("--purge", action="store_true")

    st = sub.add_parser("status", parents=[common], help="show one peer")
    st.add_argument("--role", choices=("server", "host"), required=True)
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.command == "install":
        install(args)
    elif args.command == "uninstall":
        uninstall(args.role, args)
    else:
        status(args.role, args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
