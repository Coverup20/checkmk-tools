#!/usr/bin/env python3
"""UDP hole-punching tunnel peer (prototype).

Roles:
  server: listens on a local TCP port (CheckMK polls 127.0.0.1:<port>) and
          carries each TCP stream over the punched UDP path.
  host:   accepts stream OPENs over UDP and forwards them to a local TCP
          target or to a command's stdout (the CheckMK agent).

Signalling is out of band. The daemon learns its public endpoint with STUN
and reads the peer endpoint from a JSON file written by the operator over
SSH. There is no relay: data travels only on the punched UDP path.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import shlex
import socket
import struct
import subprocess
import sys
import threading
import time

from protocol import (CTRL_KEEPALIVE, CTRL_PUNCH, CTRL_PUNCH_ACK, HELLO_EXTRA,
                      MAX_PAYLOAD, PUB_LEN, T_ACK, T_CTRL, T_DATA, T_FIN,
                      T_FIN_ACK, T_HELLO, T_HELLO_ACK, T_OPEN, T_OPEN_ACK,
                      T_OPEN_FAIL, T_RESET, Crypto, new_ephemeral,
                      session_keys)

try:
    import pwd
except ImportError:  # non-POSIX: only numeric uids are accepted
    pwd = None

VERSION = "p5"


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, file=sys.stderr, flush=True)


def parse_endpoint(text):
    host, port = text.rsplit(":", 1)
    return host, int(port)


def load_psk(path):
    with open(path, "r", encoding="ascii") as fh:
        return bytes.fromhex(fh.read().strip())


def stun_discover(sock, server, timeout=3.0):
    host, port = parse_endpoint(server)
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
    addr = infos[0][4]
    tid = os.urandom(12)
    req = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + tid
    old = sock.gettimeout()
    sock.settimeout(timeout)
    try:
        for _ in range(3):
            sock.sendto(req, addr)
            try:
                data, _src = sock.recvfrom(2048)
            except socket.timeout:
                continue
            result = _parse_stun(data, tid)
            if result:
                return result
        raise RuntimeError("STUN did not answer")
    finally:
        sock.settimeout(old)


def _parse_stun(data, tid):
    if len(data) < 20:
        return None
    _mtype, _mlen, magic = struct.unpack("!HHI", data[:8])
    if magic != 0x2112A442 or data[8:20] != tid:
        return None
    i = 20
    while i + 4 <= len(data):
        at, al = struct.unpack("!HH", data[i:i + 4])
        val = data[i + 4:i + 4 + al]
        if at in (0x0001, 0x0020) and len(val) >= 8 and val[1] == 0x01:
            port = struct.unpack("!H", val[2:4])[0]
            ip = val[4:8]
            if at == 0x0020:
                port ^= 0x2112
                ip = bytes(a ^ b for a, b in zip(ip, b"\x21\x12\xa4\x42"))
            return socket.inet_ntoa(ip), port
        i += 4 + al + ((4 - al % 4) % 4)
    return None


def _decode_proc_addr(text):
    """Decode an address from /proc/net/tcp{,6}: HEXIP:HEXPORT."""
    ip_hex, port_hex = text.split(":")
    raw = bytes.fromhex(ip_hex)
    port = int(port_hex, 16)
    if len(raw) == 4:
        return socket.inet_ntoa(raw[::-1]), port
    groups = b"".join(raw[i:i + 4][::-1] for i in range(0, 16, 4))
    return socket.inet_ntop(socket.AF_INET6, groups), port


def socket_uid(local, remote):
    """Owner UID of the ESTABLISHED TCP socket (local -> remote), or None.

    Returns None when the lookup is impossible, so the caller can fail closed.
    """
    want_local = (local[0], local[1])
    want_remote = (remote[0], remote[1])
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, "r", encoding="ascii") as fh:
                lines = fh.readlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "01":
                continue
            try:
                if (_decode_proc_addr(fields[1]) != want_local
                        or _decode_proc_addr(fields[2]) != want_remote):
                    continue
                return int(fields[7])
            except ValueError:
                continue
    return None


def peer_creds(conn):
    """Kernel-verified (pid, uid, gid) of a UNIX socket peer, or None."""
    opt = getattr(socket, "SO_PEERCRED", None)
    if opt is None:
        return None
    try:
        raw = conn.getsockopt(socket.SOL_SOCKET, opt, struct.calcsize("3i"))
    except OSError:
        return None
    return struct.unpack("3i", raw)


def proc_exe(pid):
    """Resolved executable of pid, or None."""
    try:
        return os.path.realpath("/proc/%d/exe" % pid)
    except OSError:
        return None


class Stream:
    def __init__(self, sid, sock, window):
        self.sid = sid
        self.sock = sock
        self.cond = threading.Condition()
        self.window = window
        self.send_base = 1
        self.send_next = 1
        self.unacked = {}
        self.expected = 1
        self.out_of_order = {}
        self.closed = False
        self.opened = False
        self.fin_acked = False
        self.last_send = 0.0
        self.last_progress = time.time()

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
        with self.cond:
            self.cond.notify_all()


class PipeProc:
    """Adapter that gives a subprocess pipe the same interface as a socket."""

    def __init__(self, proc):
        self.proc = proc
        self._out = proc.stdout.fileno()
        self._in = proc.stdin

    def fileno(self):
        return self._out

    def recv(self, size):
        return os.read(self._out, size)

    def sendall(self, data):
        if self._in is None:
            return
        try:
            self._in.write(data)
            self._in.flush()
        except (BrokenPipeError, OSError):
            pass

    def close(self):
        proc = self.proc
        try:
            if proc.poll() is None:
                if hasattr(os, "killpg"):
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if hasattr(os, "killpg"):
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait(timeout=1)
        except OSError:
            pass


class PunchPeer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.role = cfg["role"]
        self.state_dir = cfg.get("state_dir", "/var/lib/cmk-punch")
        psk = load_psk(cfg["psk_file"])
        self.psk = psk
        self.eph, self.eph_pub = new_ephemeral()
        self.boot = Crypto(psk, send_dir="boot", recv_dir="boot")
        self.crypto = None
        self.handshake_s = float(cfg.get("handshake_interval_s", 1.0))
        self.last_hello = 0.0
        self.sessions = 0
        self.bind = parse_endpoint(cfg["udp_bind"])
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(self.bind)
        self.sock.settimeout(0.5)
        self.local_udp = self.sock.getsockname()
        self.peer = None
        self.peer_file = cfg["peer_file"]
        self.keepalive_s = float(cfg.get("keepalive_s", 15))
        self.restun_s = float(cfg.get("restun_interval_s", 300))
        self.restun_max_s = float(cfg.get("restun_max_interval_s", 1800))
        self.restun_delay = self.restun_s
        self.last_stun = 0.0
        self.peer_silence_s = float(cfg.get("peer_silence_s", 45))
        self.last_peer_rx = 0.0
        self.local_endpoint = None
        self.punch_s = float(cfg.get("punch_interval_s", 1.0))
        self.ack_timeout = float(cfg.get("ack_timeout_s", 1.0))
        self.window = int(cfg.get("window", 32))
        self.stream_timeout = float(cfg.get("stream_timeout_s", 120))
        self.retries = int(cfg.get("max_retries", 20))
        self.punched = False
        self.last_punch = 0.0
        self.last_keepalive = 0.0
        self.last_peer_mtime = 0.0
        self.streams = {}
        self.next_sid = struct.unpack("!I", os.urandom(4))[0] or 1
        self.stop = threading.Event()
        self.tcp_listener = None
        self.unix_listener = None
        if self.role == "server":
            if cfg.get("tcp_listen"):
                host, port = parse_endpoint(cfg["tcp_listen"])
                self.tcp_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tcp_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.tcp_listener.bind((host, port))
                self.tcp_listener.listen(16)
            if cfg.get("unix_listen"):
                self.unix_listener = self._open_unix(cfg["unix_listen"],
                                                     cfg.get("unix_mode", "0660"),
                                                     cfg.get("unix_owner"))
            if self.tcp_listener is None and self.unix_listener is None:
                raise ValueError("server needs tcp_listen and/or unix_listen")
        else:
            self.command = cfg.get("target_command")
            self.target = None if self.command else parse_endpoint(cfg["target"])
        self.allowed_uids = self._resolve_uids(cfg.get("allowed_uids"))
        self.allowed_exe = [os.path.realpath(p) for p in (cfg.get("allowed_exe") or [])]

    @staticmethod
    def _resolve_uids(values):
        uids = set()
        for value in values or []:
            if isinstance(value, int):
                uids.add(value)
            elif pwd is not None:
                try:
                    uids.add(pwd.getpwnam(str(value)).pw_uid)
                except KeyError:
                    log("allowed_uids: unknown user %r, ignored" % (value,))
            else:
                log("allowed_uids: user names unsupported here, %r ignored" % (value,))
        return uids

    @staticmethod
    def _open_unix(path, mode, owner):
        mode = int(mode, 8) if isinstance(mode, str) else int(mode)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(path)
        os.chmod(path, mode)
        if owner:
            pw = pwd.getpwnam(str(owner))
            os.chown(path, pw.pw_uid, pw.pw_gid)
        sock.listen(16)
        return sock


    def send(self, mtype, stream=0, seq=0, ack=0, flags=0, payload=b"", addr=None):
        addr = addr or self.peer
        if not addr:
            return
        if mtype in (T_HELLO, T_HELLO_ACK):
            layer = self.boot
        else:
            layer = self.crypto
            if layer is None:
                return
        try:
            self.sock.sendto(layer.seal(mtype, stream, seq, ack, flags, payload), addr)
        except OSError as exc:
            log("send error: %s" % exc)

    def send_ctrl(self, payload):
        self.send(T_CTRL, payload=payload)

    def refresh_peer(self):
        try:
            mtime = os.path.getmtime(self.peer_file)
        except OSError:
            return
        if mtime == self.last_peer_mtime:
            return
        self.last_peer_mtime = mtime
        try:
            with open(self.peer_file, "r", encoding="utf-8") as fh:
                value = json.load(fh).get("peer")
            self.peer = parse_endpoint(value) if value else None
            self.punched = False
            log("peer endpoint set to %s" % (value,))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log("cannot read peer file: %s" % exc)

    def restun(self):
        self.last_stun = time.time()
        try:
            public = stun_discover(self.sock, self.cfg["stun_server"], timeout=1.5)
        except Exception as exc:
            self.restun_delay = min(self.restun_delay * 2, self.restun_max_s)
            log("re-STUN failed: %s (next attempt in %ds)" % (exc, int(self.restun_delay)))
            return
        self.restun_delay = self.restun_s
        if public != self.local_endpoint:
            self.local_endpoint = public
            self.write_endpoint(public)
            log("PUBLIC endpoint changed to %s:%d" % public)

    def send_chunk(self, st, payload):
        with st.cond:
            while not st.closed and st.send_next - st.send_base >= st.window:
                st.cond.wait(0.5)
            if st.closed:
                return False
            seq = st.send_next
            st.send_next += 1
            st.unacked[seq] = payload
            st.last_send = time.time()
            st.last_progress = time.time()
        self.send(T_DATA, st.sid, seq=seq, payload=payload)
        return True

    def deliver(self, st, payload):
        try:
            st.sock.sendall(payload)
            return True
        except OSError:
            return False

    def drain(self, st):
        while st.expected in st.out_of_order:
            payload = st.out_of_order.pop(st.expected)
            if not self.deliver(st, payload):
                self.drop_stream(st, notify=True)
                return
            st.expected += 1

    def drop_stream(self, st, notify=False):
        if self.streams.get(st.sid) is st:
            self.streams.pop(st.sid, None)
        if notify:
            for _ in range(3):
                self.send(T_RESET, st.sid)
        st.close()

    def read_chunk(self, sock, size):
        """Return None if no data yet, b"" on EOF, bytes otherwise."""
        ready, _, _ = select.select([sock], [], [], 0.5)
        if not ready:
            return None
        first = sock.recv(size)
        if not first:
            return b""
        buf = bytearray(first)
        deadline = time.monotonic() + 0.020
        while len(buf) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([sock], [], [], remaining)
            if not ready:
                break
            part = sock.recv(size - len(buf))
            if not part:
                break
            buf.extend(part)
        return bytes(buf)

    def reader_thread(self, st):
        try:
            while not st.closed:
                data = self.read_chunk(st.sock, MAX_PAYLOAD)
                if data is None:
                    if self.stop.is_set() or st.closed:
                        break
                    continue
                if not data:
                    self.finish_stream(st)
                    break
                if not self.send_chunk(st, data):
                    break
        except (OSError, ValueError):
            self.drop_stream(st, notify=True)

    def finish_stream(self, st):
        with st.cond:
            deadline = time.time() + 30
            while st.unacked and not st.closed and time.time() < deadline:
                st.cond.wait(0.5)
            stuck = bool(st.unacked)
        if stuck:
            self.drop_stream(st, notify=True)
            return
        for _ in range(12):
            if st.closed or st.fin_acked:
                return
            self.send(T_FIN, st.sid, seq=st.send_next)
            with st.cond:
                st.cond.wait(0.5)
        if not st.closed:
            self.drop_stream(st)

    def open_stream_for_tcp(self, conn):
        sid = self.next_sid
        self.next_sid += 1
        st = Stream(sid, conn, self.window)
        self.streams[sid] = st
        deadline = time.time() + self.ack_timeout * self.retries
        while self.crypto is None and time.time() < deadline and not self.stop.is_set():
            time.sleep(0.1)
        if self.crypto is None:
            log("stream %d: no session, closing" % sid)
            st.close()
            self.streams.pop(sid, None)
            return
        while time.time() < deadline and not st.closed:
            self.send(T_OPEN, sid)
            end = time.time() + self.ack_timeout * 2
            while time.time() < end:
                if st.opened or st.closed:
                    break
                time.sleep(0.05)
            if st.opened:
                break
        if not st.opened:
            log("stream %d: no OPEN_ACK" % sid)
            st.close()
            self.streams.pop(sid, None)
            return
        threading.Thread(target=self.reader_thread, args=(st,), daemon=True).start()

    def handle_open(self, sid):
        if sid in self.streams:
            self.send(T_OPEN_ACK, sid)
            return
        if self.command:
            try:
                proc = subprocess.Popen(shlex.split(self.command), shell=False,
                                        stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL,
                                        start_new_session=True,
                                        bufsize=0)
            except OSError as exc:
                log("stream %d: command failed: %s" % (sid, exc))
                self.send(T_OPEN_FAIL, sid)
                return
            sock = PipeProc(proc)
        else:
            try:
                sock = socket.create_connection(self.target, timeout=5)
            except OSError as exc:
                log("stream %d: target connect failed: %s" % (sid, exc))
                self.send(T_OPEN_FAIL, sid)
                return
        st = Stream(sid, sock, self.window)
        st.opened = True
        st.expected = 1
        self.streams[sid] = st
        if self.command:
            log("stream %d: OPEN accepted, command started" % sid)
        else:
            log("stream %d: OPEN accepted, connected to %s:%d" % ((sid,) + self.target))
        self.send(T_OPEN_ACK, sid)
        threading.Thread(target=self.reader_thread, args=(st,), daemon=True).start()

    @staticmethod
    def open_with(layer, frame):
        try:
            return layer.open(frame)
        except Exception:
            return None

    def handle_hello(self, mtype, payload, addr):
        if len(payload) < PUB_LEN:
            return
        peer_pub = payload[:PUB_LEN]
        self.last_peer_rx = time.time()
        if self.peer is None:
            log("peer endpoint learned from handshake: %s:%d" % addr)
        elif addr != self.peer:
            log("peer endpoint changed: %s:%d -> %s:%d" % (self.peer + addr))
        self.peer = addr
        self.punched = True
        keys = session_keys(self.psk, self.eph, self.eph_pub, peer_pub)
        send_dir, recv_dir = ("s2c", "c2s") if self.role == "server" else ("c2s", "s2c")
        self.crypto = Crypto.from_keys(keys[send_dir], keys[recv_dir])
        self.sessions += 1
        log("session established with %s:%d (%s, #%d)"
            % (addr[0], addr[1], "HELLO" if mtype == T_HELLO else "HELLO_ACK",
               self.sessions))
        if mtype == T_HELLO:
            self.send(T_HELLO_ACK, payload=self.eph_pub + os.urandom(HELLO_EXTRA))

    def handle_frame(self, frame, addr):
        hello = self.open_with(self.boot, frame)
        if hello is not None and hello[0] in (T_HELLO, T_HELLO_ACK):
            self.handle_hello(hello[0], hello[5], addr)
            return
        if self.crypto is None:
            return
        opened = self.open_with(self.crypto, frame)
        if opened is None:
            return
        mtype, sid, seq, _ack, _flags, payload = opened
        self.last_peer_rx = time.time()
        if self.peer is None:
            self.peer = addr
            self.punched = True
            log("peer endpoint learned from traffic: %s:%d" % addr)
        elif mtype == T_CTRL and addr != self.peer:
            log("peer endpoint changed: %s:%d -> %s:%d" % (self.peer + addr))
            self.peer = addr
            self.punched = True
        if mtype == T_CTRL:
            if payload == CTRL_PUNCH:
                self.punched = True
                self.send_ctrl(CTRL_PUNCH_ACK)
            elif payload == CTRL_PUNCH_ACK:
                self.punched = True
            return
        if mtype == T_OPEN and self.role == "host":
            self.handle_open(sid)
            return
        if mtype == T_OPEN_ACK:
            st = self.streams.get(sid)
            if st is not None:
                st.opened = True
            return
        if mtype == T_OPEN_FAIL:
            st = self.streams.pop(sid, None)
            if st is not None:
                st.close()
            return
        if mtype == T_RESET:
            st = self.streams.pop(sid, None)
            if st is not None:
                st.close()
            return
        st = self.streams.get(sid)
        if mtype == T_DATA:
            if st is None:
                return
            if seq == st.expected:
                if self.deliver(st, payload):
                    st.expected += 1
                else:
                    self.drop_stream(st, notify=True)
                    return
            elif st.expected < seq <= st.expected + 2 * st.window:
                st.out_of_order[seq] = payload
            self.drain(st)
            if st.closed:
                return
            self.send(T_ACK, sid, ack=st.expected - 1)
            return
        if mtype == T_ACK:
            if st is None:
                return
            with st.cond:
                if st.send_base <= _ack < st.send_next:
                    while st.send_base <= _ack:
                        st.unacked.pop(st.send_base, None)
                        st.send_base += 1
                    st.last_progress = time.time()
                    st.cond.notify_all()
            return
        if mtype == T_FIN:
            if st is None:
                self.send(T_FIN_ACK, sid)
                return
            st.close()
            self.streams.pop(sid, None)
            for _ in range(3):
                self.send(T_FIN_ACK, sid)
            return
        if mtype == T_FIN_ACK:
            if st is not None:
                with st.cond:
                    st.fin_acked = True
                    st.cond.notify_all()
                st.close()
                self.streams.pop(sid, None)
            return

    def tick(self):
        now = time.time()
        self.refresh_peer()
        if (self.cfg.get("use_stun", True) and self.cfg.get("stun_server")
                and not self.streams and now - self.last_stun >= self.restun_delay):
            self.restun()
        if self.peer and self.crypto is None and now - self.last_hello >= self.handshake_s:
            self.send(T_HELLO, payload=self.eph_pub + os.urandom(HELLO_EXTRA))
            self.last_hello = now
        if self.peer and self.crypto is not None and not self.punched and now - self.last_punch >= self.punch_s:
            self.send_ctrl(CTRL_PUNCH)
            self.last_punch = now
        if self.peer and now - self.last_keepalive >= self.keepalive_s:
            self.send_ctrl(CTRL_KEEPALIVE)
            self.last_keepalive = now
        for st in list(self.streams.values()):
            with st.cond:
                if st.closed:
                    continue
                items = []
                if (st.unacked and now - st.last_send >= self.ack_timeout
                        and now - self.last_peer_rx < self.peer_silence_s):
                    st.last_send = now
                    items = list(st.unacked.items())[:st.window]
                stale = bool(st.unacked) and now - st.last_progress > self.stream_timeout
            for seq, payload in items:
                self.send(T_DATA, st.sid, seq=seq, payload=payload)
            if stale:
                log("stream %d: no progress, closing" % st.sid)
                self.drop_stream(st, notify=True)

    def recv_loop(self):
        errors = 0
        while not self.stop.is_set():
            try:
                frame, addr = self.sock.recvfrom(2048)
            except socket.timeout:
                self.tick()
                continue
            except OSError as exc:
                if self.stop.is_set():
                    break
                errors += 1
                log("recv error: %s (continuing)" % exc)
                if errors >= 50:
                    log("too many receive errors, stopping")
                    break
                time.sleep(0.05)
                continue
            errors = 0
            self.handle_frame(frame, addr)
            self.tick()

    def admit(self, conn):
        """Decide whether a local connection may open a stream (fail closed)."""
        if not self.allowed_uids and not self.allowed_exe:
            return True
        pid = None
        uid = None
        if conn.family == socket.AF_UNIX:
            creds = peer_creds(conn)
            if creds is not None:
                pid, uid, _gid = creds
        else:
            try:
                uid = socket_uid(conn.getpeername(), conn.getsockname())
            except OSError:
                uid = None
        if uid is None:
            log("connection denied: cannot determine the peer uid")
            return False
        if self.allowed_uids and uid not in self.allowed_uids:
            log("connection from uid=%d pid=%s denied (allowed_uids=%s)"
                % (uid, pid, sorted(self.allowed_uids)))
            return False
        if self.allowed_exe:
            exe = proc_exe(pid) if pid is not None else None
            if exe not in self.allowed_exe:
                log("connection from uid=%d pid=%s exe=%s denied (allowed_exe)"
                    % (uid, pid, exe))
                return False
        log("connection from uid=%d pid=%s accepted" % (uid, pid))
        return True

    def accept_loop(self, listener):
        if listener is None:
            return
        listener.settimeout(0.5)
        while not self.stop.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.admit(conn):
                conn.close()
                continue
            threading.Thread(target=self.open_stream_for_tcp, args=(conn,), daemon=True).start()

    def write_endpoint(self, addr):
        os.makedirs(self.state_dir, exist_ok=True)
        with open(os.path.join(self.state_dir, "endpoint.txt"), "w", encoding="ascii") as fh:
            fh.write("%s:%d\n" % addr)

    def run(self):
        log("cmk-punch %s starting (role=%s, allowed_uids=%s, allowed_exe=%s)"
            % (VERSION, self.role, sorted(self.allowed_uids) or "any",
               self.allowed_exe or "any"))
        if self.cfg.get("use_stun", True) and self.cfg.get("stun_server"):
            try:
                public = stun_discover(self.sock, self.cfg["stun_server"])
                self.write_endpoint(public)
                log("PUBLIC endpoint %s:%d (local %s:%d)" % (public[0], public[1], self.local_udp[0], self.local_udp[1]))
                self.local_endpoint = public
            except Exception as exc:
                log("STUN failed: %s" % exc)
                self.write_endpoint(self.local_udp)
                self.local_endpoint = self.local_udp
        else:
            self.write_endpoint(self.local_udp)
            self.local_endpoint = self.local_udp
        self.last_stun = time.time()
        if self.tcp_listener is not None:
            threading.Thread(target=self.accept_loop, args=(self.tcp_listener,),
                             daemon=True).start()
            log("server listening on tcp %s" % self.cfg["tcp_listen"])
        if self.unix_listener is not None:
            threading.Thread(target=self.accept_loop, args=(self.unix_listener,),
                             daemon=True).start()
            log("server listening on unix %s mode=%s owner=%s"
                % (self.cfg["unix_listen"], self.cfg.get("unix_mode", "0660"),
                   self.cfg.get("unix_owner") or "-"))
        self.recv_loop()

    def shutdown(self, *_args):
        self.stop.set()
        for st in list(self.streams.values()):
            self.drop_stream(st)
        try:
            self.sock.close()
        except OSError:
            pass
        for listener in (self.tcp_listener, self.unix_listener):
            if listener is not None:
                try:
                    listener.close()
                except OSError:
                    pass
        unix_path = self.cfg.get("unix_listen")
        if unix_path:
            try:
                os.unlink(unix_path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="UDP punch tunnel peer")
    parser.add_argument("--config", required=True)
    parser.add_argument("--no-stun", action="store_true")
    args = parser.parse_args()
    with open(args.config, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    if args.no_stun:
        cfg["use_stun"] = False
    peer = PunchPeer(cfg)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, peer.shutdown)
    peer.run()


if __name__ == "__main__":
    main()
