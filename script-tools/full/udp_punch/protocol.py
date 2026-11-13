#!/usr/bin/env python3
"""Wire protocol for the UDP punch tunnel (prototype).

Wire format:
    MAGIC (4) | TYPE (1) | NONCE (12) | CIPHERTEXT
    CIPHERTEXT = ChaCha20-Poly1305(PLAINTEXT, AAD = MAGIC + TYPE)
    PLAINTEXT  = FLAGS (1) | STREAM_ID (4) | SEQ (4) | ACK (4) | PLEN (2)
                 | PAYLOAD (PLEN) | PADDING

The HELLO payload may carry a trailer with the sender's own address on the
path to the peer, so the other side can report which address is behind the
NAT; see encode_peer_info and decode_peer_info.

Every datagram is exactly PAD_SIZE bytes on the wire. PLAIN carries its own
payload length and the remaining bytes are random padding, so neither the
type of a frame nor the size of the data it carries is visible to an observer
of the link.

Each direction has its own AEAD key, derived from the PSK with HKDF-SHA256:
    server -> host uses info "s2c", host -> server uses info "c2s".
Every frame uses a fresh random 12-byte nonce, so no state on disk can ever
make a nonce repeat; the receiver keeps a bounded cache of nonces already
authenticated and drops a frame whose nonce it has seen.
"""

from __future__ import annotations

import os
import struct
from collections import deque

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (X25519PrivateKey,
                                                              X25519PublicKey)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

MAGIC = b"CP01"
WIRE = struct.Struct("!4sB12s")
PLAIN = struct.Struct("!BIIIH")
TAG_LEN = 16
MAX_PAYLOAD = 1150
PAD_SIZE = 1200  # every datagram on the wire is exactly this many bytes

T_CTRL = 1
T_OPEN = 2
T_OPEN_ACK = 3
T_DATA = 4
T_ACK = 5
T_FIN = 6
T_FIN_ACK = 7
T_OPEN_FAIL = 8
T_RESET = 9
T_HELLO = 10
T_HELLO_ACK = 11

PUB_LEN = 32
HELLO_EXTRA = 16

CTRL_PUNCH = b"PUNCH"
CTRL_PUNCH_ACK = b"PUNCH_ACK"
CTRL_KEEPALIVE = b"KEEPALIVE"

PEER_INFO_MAGIC = b"IP01"
PEER_INFO_MAX = 64


def derive_key(psk: bytes, label: str) -> bytes:
    """Per-direction key, so the two directions never share a key stream."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"cmk-punch/" + label.encode("ascii")).derive(psk)


def new_ephemeral():
    """Fresh X25519 private key and its raw 32-byte public key."""
    key = X25519PrivateKey.generate()
    return key, key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def session_keys(psk, eph, pub_local, pub_peer):
    """Per-direction session keys bound to both ephemeral public keys.

    The ECDH secret is mixed with the PSK, so a later compromise of the PSK
    alone does not reproduce these keys and recorded sessions stay unreadable.
    """
    shared = eph.exchange(X25519PublicKey.from_public_bytes(pub_peer))
    first, second = sorted((pub_local, pub_peer))
    salt = first + second
    ikm = psk + shared
    return {label: HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                        info=b"cmk-punch/session/" + label.encode("ascii")).derive(ikm)
            for label in ("s2c", "c2s")}


def encode_peer_info(address):
    """Trailer for HELLO: the sender's own address towards the peer."""
    raw = address.encode("ascii", "replace")[:PEER_INFO_MAX]
    return PEER_INFO_MAGIC + bytes([len(raw)]) + raw


def decode_peer_info(payload):
    """Address carried by a HELLO trailer, or None when there is none."""
    offset = PUB_LEN
    if len(payload) < offset + 5:
        return None
    if payload[offset:offset + 4] != PEER_INFO_MAGIC:
        return None
    length = payload[offset + 4]
    raw = payload[offset + 5:offset + 5 + length]
    if length == 0 or len(raw) != length:
        return None
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return None


class Crypto:
    """AEAD wrapper: per-direction keys, random nonces, bounded replay cache."""

    def __init__(self, psk: bytes, epoch: bytes = b"\x00\x00\x00\x00",
                 send_dir: str = "s2c", recv_dir: str = "c2s",
                 pad: bool = True) -> None:
        if len(psk) != 32:
            raise ValueError("PSK must be exactly 32 bytes")
        self._send = ChaCha20Poly1305(derive_key(psk, send_dir))
        self._recv = ChaCha20Poly1305(derive_key(psk, recv_dir))
        self._seen = deque(maxlen=4096)
        self._seen_set = set()
        self.pad = bool(pad)

    @classmethod
    def from_keys(cls, send_key, recv_key, pad: bool = True):
        """Layer built from explicit 32-byte keys, used after the handshake."""
        obj = cls.__new__(cls)
        obj._send = ChaCha20Poly1305(send_key)
        obj._recv = ChaCha20Poly1305(recv_key)
        obj._seen = deque(maxlen=4096)
        obj._seen_set = set()
        obj.pad = bool(pad)
        return obj

    def seal(self, mtype, stream=0, seq=0, ack=0, flags=0, payload=b""):
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("payload longer than MAX_PAYLOAD")
        nonce = os.urandom(12)
        aad = MAGIC + bytes([mtype])
        plain = PLAIN.pack(flags, stream, seq, ack, len(payload)) + payload
        if self.pad:
            target = PAD_SIZE - WIRE.size - TAG_LEN
            if len(plain) > target:
                raise ValueError("frame does not fit in PAD_SIZE")
            plain += os.urandom(target - len(plain))
        return WIRE.pack(MAGIC, mtype, nonce) + self._send.encrypt(nonce, plain, aad)

    def open(self, frame):
        if len(frame) < WIRE.size + TAG_LEN:
            raise ValueError("frame too short")
        magic, mtype, nonce = WIRE.unpack_from(frame, 0)
        if magic != MAGIC:
            raise ValueError("bad magic")
        if nonce in self._seen_set:
            raise ValueError("replayed frame")
        aad = MAGIC + bytes([mtype])
        try:
            plain = self._recv.decrypt(nonce, frame[WIRE.size:], aad)
        except InvalidTag:
            raise ValueError("authentication failed")
        if len(plain) < PLAIN.size:
            raise ValueError("plaintext too short")
        flags, stream, seq, ack, plen = PLAIN.unpack_from(plain, 0)
        body = plain[PLAIN.size:]
        if plen > len(body):
            raise ValueError("payload length beyond frame")
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(nonce)
        self._seen_set.add(nonce)
        return mtype, stream, seq, ack, flags, body[:plen]
