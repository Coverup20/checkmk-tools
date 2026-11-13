# udp_punch - TCP-over-UDP tunnel prototype with hole punching

No component runs on a relay host. Signalling is out of band (over SSH);
STUN is only used to learn the local NAT mapping. Data travels only on the
direct UDP path between the two peers.

## Roles

| Role | Where | What it does |
| --- | --- | --- |
| server | CheckMK host | local listener, one stream per connection |
| host | monitored host | accepts OPEN, forwards to the local agent |

Both peers punch towards the public endpoint of the other; keepalives every
15 seconds keep the NAT mappings alive.

## Wire protocol

- Frame: CP01 | type | nonce(12) | ciphertext, always 1200 bytes on the
  wire. The plaintext starts with flags, stream id, sequence, ack and a
  two-byte payload length; everything after the payload is random padding.
- AEAD ChaCha20-Poly1305 with a 32-byte PSK; 4096-entry replay window.
- Types: CTRL (PUNCH/PUNCH_ACK/KEEPALIVE), OPEN, OPEN_ACK, OPEN_FAIL, DATA,
  ACK, FIN, FIN_ACK, RESET.
- Streams multiplexed on one UDP socket; per direction a Go-Back-N window
  (default 32 packets), cumulative ACKs, retransmission and a reliable FIN
  (maximum payload 1150 bytes).

## Metadata

Padding is on by default (pad_frames, true). Every datagram is exactly
PAD_SIZE bytes - 1200 - whatever it carries, so an observer of the link
cannot tell control frames from data frames and cannot read the size of a
chunk from a frame. What remains visible: the number of frames, that is the
order of magnitude of the transfer, and the schedule of the poller, which
belongs to the monitoring system and not to the tunnel. Hiding either would
need constant-rate cover traffic.

## Session keys and forward secrecy

At every start each peer generates a fresh X25519 keypair. The HELLO and
HELLO_ACK frames are protected with a key derived from the PSK alone and carry
the ephemeral public key; the session keys are then derived from the PSK mixed
with the ECDH shared secret, with both public keys as salt and s2c or c2s as
info. A later compromise of the PSK alone therefore does not reveal recorded
sessions. Every frame uses a fresh random 12-byte nonce and the receiver keeps
a bounded cache of the nonces it has already authenticated, so no state on disk
can make a nonce repeat.

## Deploy

PSK (32-byte hex, mode 600) on both peers:

```bash
openssl rand -hex 32 > /etc/cmk-punch/psk
chmod 600 /etc/cmk-punch/psk
```

Server configuration, `/etc/cmk-punch/server.json`:

```json
{
  "role": "server",
  "psk_file": "/etc/cmk-punch/psk",
  "udp_bind": "0.0.0.0:6015",
  "stun_server": "<stun-server>:3478",
  "peer_file": "/etc/cmk-punch/peer.json",
  "state_dir": "/var/lib/cmk-punch",
  "unix_listen": "/run/cmk-punch/agent.sock",
  "unix_mode": "0660",
  "unix_owner": "monitoring",
  "pad_frames": true,
  "allowed_uids": ["monitoring"],
  "rate_limit_pps": 200,
  "keepalive_s": 15,
  "punch_interval_s": 1.0,
  "restun_max_interval_s": 1800,
  "restun_interval_s": 300
}
```

Host configuration, `/etc/cmk-punch/host.json`:

```json
{
  "role": "host",
  "psk_file": "/etc/cmk-punch/psk",
  "udp_bind": "0.0.0.0:6015",
  "stun_server": "<stun-server>:3478",
  "peer_file": "/etc/cmk-punch/peer.json",
  "state_dir": "/var/lib/cmk-punch",
  "pad_frames": true,
  "target_command": "/usr/bin/check_mk_agent",
  "keepalive_s": 15,
  "punch_interval_s": 1.0
}
```

Use target_command to run the agent and forward its stdout; target stays
available for a plain TCP destination.

Update both peers in the same change: with the payload length field the frame
layout changed, so an old peer cannot read frames from a new one.

## Admission control before OPEN

Two mechanisms, both fail closed: if the peer cannot be identified the
connection is closed before any OPEN is sent.

### TCP listener, source uid (P3)

With tcp_listen set, the server accepts the connection only when the client
socket belongs to an allowed uid, read from /proc/net/tcp or /proc/net/tcp6
(uid field, ESTABLISHED state). Key: allowed_uids, with user names or numeric
uids; absent or empty means no filter. Every accepted or denied connection is
logged in the unit journal.

Caveat measured on 2026-11-12: an endpoint security agent that installs
nftables rules redirecting all TCP traffic through its own proxy (for example
a rule matching skuid != its own uid and redirecting to a local proxy port)
re-originates every local connection, so the server always sees the agent
socket and never the real client. With the filter enabled the CheckMK poller
itself was denied: zero-byte fetches and an empty-output error in the client.
The filter is therefore unusable on a host where such an agent is active; it
starts working again as soon as the interceptor is gone.

### Unix socket, kernel credentials (P4)

The local TCP listener can be replaced (or accompanied) by a Unix socket: the
peer is verified by the kernel with SO_PEERCRED and filesystem permissions act
as the first filter. Keys: unix_listen (path, enables the listener), unix_mode
(octal, as a string), unix_owner (user that owns the socket, its group and its
primary group), allowed_uids (peer uids from SO_PEERCRED), allowed_exe
(optional, resolved paths from /proc/pid/exe; only usable when credentials are
available). At least one of tcp_listen and unix_listen must be set, otherwise
the server refuses to start.

The TCP listener refuses to start when neither allowed_uids nor allowed_exe is
configured, so a plain TCP path can never be opened without an admission gate.
Incoming datagrams are rate limited per source address before any decryption
(rate_limit_pps, default 200, 0 disables); two streams from one legitimate
peer stay far below that.

On the CheckMK side the socket is used with the rule "Individual program call
instead of agent access", which runs, as the site user,
/usr/bin/python3 /cmk-punch/cmk_punch_agent.py [path] and reads stdout as the
agent output. The program exits 0 with data, 2 when it cannot connect, 3 on a
read error and 4 when it receives no bytes.

Production layout since 2026-11-12: no tcp_listen, only unix_listen with
allowed_uids set to the site user; the datasource rule is active on the
monitored host, so cmk -D shows the program line and cmk -vvn reports agent
Success with cmk_time_ds between 11 and 13 seconds; the server journal logs one
"connection from uid=SITE_UID pid=... accepted" line per poll.

## Install on a peer

Each peer is installed on the machine itself; nothing is pushed from the
other side. The installer lives next to the rest of the toolset and needs
python3-cryptography on the target. Both peers must allow the UDP port
selected with --udp-bind (default 6015) inbound.

With a terminal on stdin the installer asks for the missing values, shows
each default in brackets and prints a summary before writing anything;
--non-interactive forces the flag-only behaviour and --yes skips the final
confirmation.

Server side, the CheckMK host:

```bash
sudo python3 install_udp_punch.py install --role server \
    --stun-server <stun-server>:3478 \
    --unix-owner <checkmk-site-user> \
    --peer <other-peer-public-address>:6015
```

Host side, the monitored host:

```bash
sudo python3 install_udp_punch.py install --role host \
    --stun-server <stun-server>:3478 \
    --peer <other-peer-public-address>:6015
```

The first run generates /etc/cmk-punch/psk and prints its sha256; copy that
file to the other peer and install it there with --psk-file PATH so both
sides share the same key. The installer verifies the source files, backs up
every file it replaces, writes the configuration and the systemd unit, and
starts the unit. The server role also installs the datasource client and
prints the CheckMK rule to configure by hand. Useful flags: --root DIR to
rehearse an installation under a directory without touching systemd,
--force to replace an existing configuration, --no-start to write the unit
without enabling it; the status and uninstall subcommands inspect and remove
one peer, and uninstall --purge also deletes configuration and state.

## Re-STUN backoff

restun_interval_s (default 300) is the first interval between two re-STUN
attempts; every failure doubles the wait up to restun_max_interval_s (default
1800), and the first success brings it back to restun_interval_s. The code
version is logged at startup as "cmk-punch VERSION starting".

## Out-of-band signalling

1. Start the daemon on both peers.
2. Read /var/lib/cmk-punch/endpoint.txt on each side (public address).
3. Write /etc/cmk-punch/peer.json on each peer as {"peer": "OTHER_PEER_ADDRESS"},
   over SSH.
4. The log shows "peer endpoint learned from traffic" and "peer endpoint set".
5. Test the tunnel from the server side:

```bash
timeout 20 bash -c 'exec 3<>/dev/tcp/127.0.0.1/6010; head -6 <&3'
```

It must return the agent header line and the hostname of the monitored host.

## Prototype limits

- Symmetric NAT: the mapping towards the STUN server can differ from the one
  towards the peer and the punch fails; this has to be detected and documented.
- Throughput: stop-and-wait, about 1150 bytes per RTT per stream.
- One peer per process; no relay, no automatic fallback.
- The PSK has to be distributed out of band and rotated by hand.
