#!/usr/bin/env python3
"""Wire protocol for the UDP punch tunnel (prototype).

Wire format:
    MAGIC (4) | TYPE (1) | NONCE (12) | CIPHERTEXT
    CIPHERTEXT = ChaCha20-Poly1305(PLAINTEXT, AAD = MAGIC + TYPE)
    PLAINTEXT  = FLAGS (1) | STREAM_ID (4) | SEQ (4) | ACK (4) | PAYLOAD

Each direction has its own AEAD key, derived from the PSK with HKDF-SHA256:
    server -> host uses info "s2c", host -> server uses info "c2s".
Nonce = 4-byte persisted epoch + 8-byte counter. The epoch is increased at
every process start and written to disk before any frame leaves, so a
restarted peer never reuses a nonce. A receiver rejects any frame whose epoch
is older than the newest epoch it has already authenticated.
"""

from __future__ import annotations

import struct
from collections import deque

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"CP01"
WIRE = struct.Struct("!4sB12s")
PLAIN = struct.Struct("!BIII")
MAX_PAYLOAD = 1150

T_CTRL = 1
T_OPEN = 2
T_OPEN_ACK = 3
T_DATA = 4
T_ACK = 5
T_FIN = 6
T_FIN_ACK = 7
T_OPEN_FAIL = 8
T_RESET = 9

CTRL_PUNCH = b"PUNCH"
CTRL_PUNCH_ACK = b"PUNCH_ACK"
CTRL_KEEPALIVE = b"KEEPALIVE"


def derive_key(psk: bytes, label: str) -> bytes:
    """Per-direction key, so the two directions never share a key stream."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"cmk-punch/" + label.encode("ascii")).derive(psk)


class Crypto:
    """AEAD wrapper: per-direction keys, epoch-counter nonces, replay window."""

    def __init__(self, psk: bytes, epoch: bytes, send_dir: str, recv_dir: str) -> None:
        if len(psk) != 32:
            raise ValueError("PSK must be exactly 32 bytes")
        if len(epoch) != 4:
            raise ValueError("epoch must be 4 bytes")
        self._send = ChaCha20Poly1305(derive_key(psk, send_dir))
        self._recv = ChaCha20Poly1305(derive_key(psk, recv_dir))
        self._epoch = epoch
        self._counter = 0
        self._max_epoch = b"\x00\x00\x00\x00"
        self._seen = deque(maxlen=4096)
        self._seen_set = set()

    def seal(self, mtype, stream=0, seq=0, ack=0, flags=0, payload=b""):
        self._counter += 1
        nonce = self._epoch + struct.pack("!Q", self._counter)
        aad = MAGIC + bytes([mtype])
        plain = PLAIN.pack(flags, stream, seq, ack) + payload
        return WIRE.pack(MAGIC, mtype, nonce) + self._send.encrypt(nonce, plain, aad)

    def open(self, frame):
        if len(frame) < WIRE.size + 16:
            raise ValueError("frame too short")
        magic, mtype, nonce = WIRE.unpack_from(frame, 0)
        if magic != MAGIC:
            raise ValueError("bad magic")
        epoch = nonce[:4]
        if epoch < self._max_epoch:
            raise ValueError("stale epoch")
        if epoch == self._max_epoch and nonce in self._seen_set:
            raise ValueError("replayed frame")
        aad = MAGIC + bytes([mtype])
        try:
            plain = self._recv.decrypt(nonce, frame[WIRE.size:], aad)
        except InvalidTag:
            raise ValueError("authentication failed")
        if epoch > self._max_epoch:
            self._max_epoch = epoch
            self._seen.clear()
            self._seen_set.clear()
        if len(plain) < PLAIN.size:
            raise ValueError("plaintext too short")
        flags, stream, seq, ack = PLAIN.unpack_from(plain, 0)
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(nonce)
        self._seen_set.add(nonce)
        return mtype, stream, seq, ack, flags, plain[PLAIN.size:]
