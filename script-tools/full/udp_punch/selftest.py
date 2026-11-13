#!/usr/bin/env python3
"""End-to-end self-test for the UDP punch prototype, over loopback only."""

import json
import os
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import punch_peer
from protocol import MAX_PAYLOAD, PAD_SIZE, PUB_LEN, Crypto, T_DATA, decode_peer_info, encode_peer_info
from punch_peer import PunchPeer, socket_uid


def echo_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def handle(conn):
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                conn.sendall(data)
        finally:
            conn.close()

    def accept_loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()
    return srv.getsockname()


def free_port():
    tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tmp.bind(("127.0.0.1", 0))
    port = tmp.getsockname()[1]
    tmp.close()
    return port


def crypto_checks(psk):
    a = Crypto(psk, b"\x00\x00\x00\x02", "c2s", "s2c")
    b = Crypto(psk, b"\x00\x00\x00\x02", "s2c", "c2s")
    frame = a.seal(T_DATA, 1, seq=1, payload=b"x")
    assert b.open(frame)[5] == b"x", "cross-direction frame not accepted"
    try:
        b.open(frame)
        raise AssertionError("replayed frame accepted")
    except ValueError:
        pass
    frames = {Crypto(psk, b"\x00\x00\x00\x02", "c2s", "s2c").seal(T_DATA, 1, seq=2, payload=b"y")[5:17] for _ in range(200)}
    assert len(frames) == 200, "nonce repeated"
    try:
        a.open(frame)
        raise AssertionError("frame accepted with the wrong direction key")
    except ValueError:
        pass
    print("crypto checks: OK")


def uid_lookup_check():
    """socket_uid() must report the uid of the process that owns the socket."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    client = socket.create_connection(listener.getsockname(), timeout=5)
    server_side, _ = listener.accept()
    try:
        uid = socket_uid(client.getsockname(), client.getpeername())
    finally:
        client.close()
        server_side.close()
        listener.close()
    assert uid == os.getuid(), "socket_uid returned %r, expected %r" % (uid, os.getuid())
    print("uid lookup: OK (uid %d)" % os.getuid())


def recv_exact(sock, size):
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise AssertionError("connection closed after %d/%d bytes" % (len(buf), size))
        buf += chunk
    return buf


def make_cfg(tmp, psk_path, role, peer_file, tcp_port, echo_addr, extra=None, tcp=True):
    base = {
        "role": role,
        "psk_file": psk_path,
        "udp_bind": "127.0.0.1:0",
        "peer_file": peer_file,
        "state_dir": os.path.join(tmp, "%s-%s" % (role, os.path.basename(peer_file))),
        "use_stun": False,
        "keepalive_s": 2,
        "punch_interval_s": 0.2,
        "ack_timeout_s": 0.2,
        "max_retries": 200,
    }
    if role == "server":
        if tcp:
            base["tcp_listen"] = "127.0.0.1:%d" % tcp_port
        if "allowed_uids" not in base and "allowed_exe" not in base:
            base["allowed_uids"] = [os.getuid()]
    else:
        base["target"] = "%s:%d" % echo_addr
    if extra:
        base.update(extra)
    return base


def start_pair(tmp, psk_path, echo_addr, tag, server_extra=None):
    tcp_port = free_port()
    server_file = os.path.join(tmp, "server-peer-%s.json" % tag)
    host_file = os.path.join(tmp, "host-peer-%s.json" % tag)
    server = PunchPeer(make_cfg(tmp, psk_path, "server", server_file, tcp_port,
                                echo_addr, server_extra))
    host = PunchPeer(make_cfg(tmp, psk_path, "host", host_file, tcp_port, echo_addr))
    with open(server_file, "w", encoding="utf-8") as fh:
        json.dump({"peer": "127.0.0.1:%d" % host.local_udp[1]}, fh)
    with open(host_file, "w", encoding="utf-8") as fh:
        json.dump({"peer": "127.0.0.1:%d" % server.local_udp[1]}, fh)
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=host.run, daemon=True).start()
    time.sleep(1.5)
    return server, host, tcp_port, server_file


def restun_backoff_check(tmp, psk_path):
    peer_file = os.path.join(tmp, "server-peer-backoff.json")
    cfg = make_cfg(tmp, psk_path, "server", peer_file, free_port(), ("127.0.0.1", 9))
    cfg["restun_interval_s"] = 300
    cfg["restun_max_interval_s"] = 1000
    cfg["stun_server"] = "no-such-host.invalid:3478"
    peer = PunchPeer(cfg)
    try:
        assert peer.restun_delay == 300, peer.restun_delay
        peer.restun()
        assert peer.restun_delay == 600, peer.restun_delay
        peer.restun()
        assert peer.restun_delay == 1000, peer.restun_delay
        peer.restun()
        assert peer.restun_delay == 1000, peer.restun_delay
        original = punch_peer.stun_discover
        punch_peer.stun_discover = lambda *a, **k: peer.local_udp
        try:
            peer.restun()
        finally:
            punch_peer.stun_discover = original
        assert peer.restun_delay == 300, peer.restun_delay
    finally:
        peer.shutdown()
    print("restun backoff: OK (300 -> 600 -> 1000 capped -> 300 after success)")


def uid_gate_checks(tmp, psk_path, echo_addr):
    payload = b"uid-gate"

    server, host, tcp_port, _ = start_pair(
        tmp, psk_path, echo_addr, "allow", {"allowed_uids": [os.getuid()]})
    try:
        client = socket.create_connection(("127.0.0.1", tcp_port), timeout=10)
        client.sendall(payload)
        got = recv_exact(client, len(payload))
        client.close()
        assert got == payload, got
    finally:
        server.shutdown()
        host.shutdown()
    print("uid gate allow: OK")

    deny_uid = 65534 if os.getuid() == 0 else 0
    server, host, tcp_port, _ = start_pair(
        tmp, psk_path, echo_addr, "deny", {"allowed_uids": [deny_uid]})
    try:
        client = socket.create_connection(("127.0.0.1", tcp_port), timeout=10)
        client.settimeout(5)
        try:
            got = client.recv(16)
        except OSError:
            got = b""
        client.close()
        time.sleep(0.5)
        assert got == b"", got
        assert not host.streams, host.streams
    finally:
        server.shutdown()
        host.shutdown()
    print("uid gate deny: OK (closed before OPEN)")


def unix_socket_checks(tmp, psk_path, echo_addr):
    payload = b"unix-gate"
    sock_path = os.path.join(tmp, "run", "agent.sock")
    uid = os.getuid()

    def start(extra, tag):
        server_file = os.path.join(tmp, "server-peer-%s.json" % tag)
        host_file = os.path.join(tmp, "host-peer-%s.json" % tag)
        cfg_s = make_cfg(tmp, psk_path, "server", server_file, free_port(),
                         echo_addr, extra, tcp=False)
        server = PunchPeer(cfg_s)
        host = PunchPeer(make_cfg(tmp, psk_path, "host", host_file, 0, echo_addr))
        with open(server_file, "w", encoding="utf-8") as fh:
            json.dump({"peer": "127.0.0.1:%d" % host.local_udp[1]}, fh)
        with open(host_file, "w", encoding="utf-8") as fh:
            json.dump({"peer": "127.0.0.1:%d" % server.local_udp[1]}, fh)
        threading.Thread(target=server.run, daemon=True).start()
        threading.Thread(target=host.run, daemon=True).start()
        time.sleep(1.5)
        return server, host

    def connect():
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(10)
        client.connect(sock_path)
        return client

    server, host = start({"unix_listen": sock_path, "unix_mode": "0660",
                          "allowed_uids": [uid]}, "unix-allow")
    try:
        mode = os.stat(sock_path).st_mode & 0o777
        assert mode == 0o660, oct(mode)
        client = connect()
        client.sendall(payload)
        got = recv_exact(client, len(payload))
        client.close()
        assert got == payload, got
    finally:
        server.shutdown()
        host.shutdown()
    assert not os.path.exists(sock_path), "socket file not removed on shutdown"
    print("unix socket allow: OK (mode 0660)")

    deny_uid = 65534 if uid == 0 else 0
    server, host = start({"unix_listen": sock_path, "allowed_uids": [deny_uid]},
                         "unix-deny")
    try:
        client = connect()
        try:
            got = client.recv(16)
        except OSError:
            got = b""
        client.close()
        time.sleep(0.5)
        assert got == b"", got
        assert not host.streams, host.streams
    finally:
        server.shutdown()
        host.shutdown()
    print("unix socket deny: OK (closed before OPEN)")

    real_exe = os.path.realpath("/proc/self/exe")
    server, host = start({"unix_listen": sock_path, "allowed_exe": [real_exe]},
                         "unix-exe")
    try:
        client = connect()
        client.sendall(payload)
        got = recv_exact(client, len(payload))
        client.close()
        assert got == payload, got
    finally:
        server.shutdown()
        host.shutdown()
    print("unix socket allowed_exe: OK (%s)" % real_exe)


def handshake_checks(psk):
    from protocol import Crypto, T_DATA, new_ephemeral, session_keys
    a_priv, a_pub = new_ephemeral()
    b_priv, b_pub = new_ephemeral()
    ka = session_keys(psk, a_priv, a_pub, b_pub)
    kb = session_keys(psk, b_priv, b_pub, a_pub)
    assert ka["s2c"] == kb["s2c"], "the two sides derive different s2c keys"
    assert ka["c2s"] == kb["c2s"], "the two sides derive different c2s keys"
    c_priv, c_pub = new_ephemeral()
    kc = session_keys(psk, a_priv, a_pub, c_pub)
    assert kc["s2c"] != ka["s2c"], "session keys ignore the peer ephemeral key"
    layer = Crypto.from_keys(ka["s2c"], ka["c2s"])
    frame = layer.seal(T_DATA, 1, payload=b"x")
    boot = Crypto(psk, send_dir="boot", recv_dir="boot")
    try:
        boot.open(frame)
        raise AssertionError("the boot key opened a session frame")
    except ValueError:
        pass
    print("handshake checks: OK")


def gate_requirement_check(tmp, psk_path, echo_addr):
    cfg = make_cfg(tmp, psk_path, "server", os.path.join(tmp, "server-nogate.json"),
                   free_port(), echo_addr, {"allowed_uids": []})
    try:
        PunchPeer(cfg)
        raise AssertionError("a TCP listener started without any admission gate")
    except ValueError:
        pass
    print("gate requirement: OK (tcp_listen refused without allowed_uids)")


def rate_limit_check(tmp, psk_path, echo_addr):
    cfg = make_cfg(tmp, psk_path, "server", os.path.join(tmp, "server-rate.json"),
                   free_port(), echo_addr, {"rate_limit_pps": 5})
    peer = PunchPeer(cfg)
    try:
        addr = ("127.0.0.1", 12345)
        allowed = sum(1 for _ in range(10) if peer.rate_ok(addr))
        assert allowed == 5, allowed
        assert peer.rate_ok(("127.0.0.1", 54321)), "a second source was limited"
    finally:
        peer.shutdown()
    print("rate limit: OK (5 of 10 from one source, another source allowed)")


def padding_checks(psk):
    a = Crypto(psk, b"\x00\x00\x00\x02", "c2s", "s2c")
    b = Crypto(psk, b"\x00\x00\x00\x02", "s2c", "c2s")
    for n in (0, 1, 100, 1150):
        frame = a.seal(T_DATA, 1, seq=n + 1, payload=b"z" * n)
        assert len(frame) == PAD_SIZE, (n, len(frame))
        assert b.open(frame)[5] == b"z" * n, n
    plain = Crypto(psk, b"\x00\x00\x00\x02", "c2s", "s2c", pad=False)
    plain_rx = Crypto(psk, b"\x00\x00\x00\x02", "s2c", "c2s", pad=False)
    frame = plain.seal(T_DATA, 1, seq=99, payload=b"y")
    assert len(frame) < PAD_SIZE, len(frame)
    assert plain_rx.open(frame)[5] == b"y"
    try:
        a.seal(T_DATA, 1, payload=b"x" * (MAX_PAYLOAD + 1))
        raise AssertionError("oversized payload accepted")
    except ValueError:
        pass
    print("padding: OK (every frame %d bytes, payload restored)" % PAD_SIZE)


def peer_info_checks():
    sample = "192.0.2.10"
    blob = encode_peer_info(sample)
    payload = b"\x00" * PUB_LEN + blob + b"\x01" * 16
    assert decode_peer_info(payload) == sample, decode_peer_info(payload)
    assert decode_peer_info(b"\x00" * PUB_LEN + b"\x01" * 16) is None
    assert decode_peer_info(b"\x00" * 16) is None
    print("peer info: OK (%s)" % sample)


def main():
    tmp = tempfile.mkdtemp(prefix="punch-selftest-")
    psk_path = os.path.join(tmp, "psk")
    psk = os.urandom(32)
    with open(psk_path, "w", encoding="ascii") as fh:
        fh.write(psk.hex())

    crypto_checks(psk)
    padding_checks(psk)
    peer_info_checks()
    handshake_checks(psk)
    if not hasattr(os, "getuid"):
        raise SystemExit("this self-test needs /proc and getuid (POSIX only)")
    uid_lookup_check()
    restun_backoff_check(tmp, psk_path)
    gate_requirement_check(tmp, psk_path, ("127.0.0.1", 9))
    rate_limit_check(tmp, psk_path, ("127.0.0.1", 9))

    echo_addr = echo_server()
    server, host, tcp_port, server_file = start_pair(tmp, psk_path, echo_addr, "main")
    assert server.crypto is not None, "server did not complete the handshake"
    assert host.crypto is not None, "host did not complete the handshake"
    assert server.peer_real_ip == "127.0.0.1", server.peer_real_ip
    print("peer real address: OK (%s)" % server.peer_real_ip)

    client = socket.create_connection(("127.0.0.1", tcp_port), timeout=10)
    payload = b"hello-punch"
    client.sendall(payload)
    got = recv_exact(client, len(payload))
    assert got == payload, (got, payload)
    print("small payload: OK (%r)" % got)

    big = os.urandom(200 * 1024)
    client.sendall(big)
    got = recv_exact(client, len(big))
    assert got == big, "large payload mismatch"
    print("large payload: OK (%d bytes)" % len(got))

    # The first stream is still open on the host: a restarted server process
    # must not reuse its stream id.
    server.shutdown()
    time.sleep(0.5)
    server2 = PunchPeer(make_cfg(tmp, psk_path, "server", server_file, tcp_port, echo_addr))
    threading.Thread(target=server2.run, daemon=True).start()
    time.sleep(1.5)

    client2 = socket.create_connection(("127.0.0.1", tcp_port), timeout=10)
    client2.sendall(payload)
    got = recv_exact(client2, len(payload))
    assert got == payload, ("after server restart", got)
    print("after server restart: OK (%r)" % got)

    client.close()
    client2.close()
    server2.shutdown()
    host.shutdown()

    uid_gate_checks(tmp, psk_path, echo_addr)
    unix_socket_checks(tmp, psk_path, echo_addr)
    print("SELFTEST PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
