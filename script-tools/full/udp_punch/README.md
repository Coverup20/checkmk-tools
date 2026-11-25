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
- Types: CTRL (PUNCH/PUNCH_ACK/KEEPALIVE/STATUS), OPEN, OPEN_ACK, OPEN_FAIL,
  DATA, ACK, FIN, FIN_ACK, RESET. HELLO and HELLO_ACK carry an identity block
  (magic ID01, protocol byte, ephemeral X25519 key, Ed25519 public key,
  signature) and may carry a trailer with the sender's own address on the path
  to the peer (an IP01 trailer after the identity block); the receiver logs it
  as "peer real address" and writes it to peer_real_ip.txt in the state
  directory. The advertise_ip configuration key overrides the detected address.
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

## Session watchdog and automatic recovery (p9)

Because a restart generates a new ephemeral keypair, the two sides no longer
share the same session keys. A peer that believes it still has a session would
never send HELLO again, so without a watchdog a restart of one side could leave
the tunnel dead on stale keys until a manual restart - for example when the
restarted side is behind NAT and its own HELLO to the peer is lost by a stale
mapping.

Both roles now run the same watchdog in tick():

- a session that has received no authenticated frame for session_dead_s
  (default 45, three keepalives) is dropped: the keys are forgotten, its
  streams are closed and HELLO starts again immediately. The peer learns the
  new endpoint from the HELLO source address.
- a peer that still has no session after bootstrap_timeout_s (default 120)
  exits with code 1. systemd (Restart=always, RestartSec=5) and the Windows
  task (run.cmd loops with a 5 second pause) restart it, so both sides keep
  restarting until the link is established.

Both keys are per-peer configuration; the decision logic is
PunchPeer.session_health() and is covered by selftest.py (rekey after
session_dead_s, give-up after bootstrap_timeout_s, and an end-to-end test that
kills one side, waits for the other to drop the stale session and checks that
the tunnel recovers by itself with a new stream).

This change does not alter the wire format: a p9 peer interoperates with a p8
peer, so the two sides can be updated one at a time. A p9 side also heals a
restart of a p8 side; the opposite direction only works once the restarted
side runs p9.

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
  "session_dead_s": 45,
  "bootstrap_timeout_s": 120,
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
  "advertise_ip": "<host-address-towards-the-peer>",
  "keepalive_s": 15,
  "punch_interval_s": 1.0,
  "session_dead_s": 45,
  "bootstrap_timeout_s": 120
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

## Keys per pair and rotation

Every pair can have its own key instead of one key shared by every tunnel.
The server keeps one file per instance (`psk-<instance>`, mode 600, root) and
`server-<instance>.json` points at it; the peer keeps the path already written
in its own config, normally `/etc/cmk-punch/psk`, so the peer configuration
does not change.

```sh
install_udp_punch.py rotate-psk --role server --instance box
install_udp_punch.py rotate-psk --role host --instance box --psk-file -
```

The server run generates the key (or reads it from `--psk-file`), backs up the
old key and the configuration, writes the new key, updates `psk_file` and
restarts the unit. It prints only the sha256 of the key and the path to feed
to the other side. Transfer it with a pipe, never on a command line or into a
terminal:

```sh
ssh server cat /etc/cmk-punch/psk-box \
  | ssh peer install_udp_punch.py rotate-psk --role host --psk-file -
```

Both sides must be updated in the same window: with different keys the HELLO
cannot be authenticated and the pair stays down until they match again. Use
`--dry-run` to see the plan, `--no-restart` to write the files without
restarting, and the `.bak-<timestamp>` files to roll back. A key dedicated to
one pair limits the damage of a leaked key to that pair. It does not stop
whoever holds the key from impersonating the peer: that needs an identity key,
planned as a later protocol step.

## Identities (p11)

Each side owns an Ed25519 identity: identity.key holds its 32-byte seed (mode
600) and the other side pins its public key in trusted_identity, one identity
per pair. HELLO carries a protocol byte, the sender's ephemeral X25519 key, its
public identity and a signature over all three; HELLO_ACK signs its own values
together with the ones it answers, so a recorded ACK cannot be replayed into
another handshake. Session keys are HKDF over the X25519 shared secret mixed
with the pair PSK, with both identities in the salt.

The protocol byte is inside the signed transcript, so a peer cannot claim a
version it does not speak. The receiver logs "peer speaks protocol N" when it
differs from its own, which makes a peer left behind by an upgrade visible at
the first handshake instead of as a silent failure. A layout change still
requires both sides to be updated together.

A peer that presents the right PSK but an identity that is not pinned is
rejected before any stream is opened, so a leaked key alone is no longer
enough to impersonate a host.

Provisioning is out of band and local to each side:

```sh
install_udp_punch.py pubkey --generate        # print this side's public key
install_udp_punch.py install --role host \
    --identity-key /etc/cmk-punch/identity.key \
    --trusted-identity <public key of the other side>
```

The installer creates identity.key when it is missing, writes both values into
the configuration and refuses to install without a trusted identity. pubkey
with --generate prints the key before the first install, when the peer's key
must be exchanged.

## Another instance on the same host

A host can run more than one server instance, one per pair. new-instance
writes the whole instance from a template: a dedicated PSK, an identity, the
configuration, the unit and the firewall rule. The peer's public key is
required, and the instance prints its own so the peer can pin it.

```sh
install_udp_punch.py new-instance --name box2 --udp-port 6040 \
    --trusted-identity <peer public key>
```

Each instance needs its own UDP port and its own key file: two instances
sharing a PSK file is a bug, because rotating one silently changes the key of
the other. --dry-run shows the plan; --force replaces an existing
configuration after a backup.

## Peer-side status (p12)

Inside an established session the peer sends a CTRL STATUS frame every 30
seconds (status_interval_s) with its version, role, session state, open
streams and uptime. The server authenticates it like any other frame, keeps
the last report in <state_dir>/peer_status.json and the dashboard shows it in
the Peer view column. A server that predates this feature ignores an unknown
CTRL payload, so the servers can be updated first and the peers later without
breaking a pair.

The report says only what the peer sees. A peer whose local agent is broken
still reports a healthy session; it is the fetch through the socket that
fails.

## Symmetric NAT detection

A NAT is symmetric when it opens a different public port for every
destination, and then two peers behind symmetric NATs cannot punch a hole. The
STATUS exchange makes it visible: each side reports its STUN endpoint and the
address it observes for the peer, and each side compares the address its peer
sees for it against its own STUN mapping. The verdict is cone (same address),
symmetric (same IP, different port) or mapping-changed (different IP); it is
logged when it changes and the dashboard shows it in the peer view.

The tunnel does not fix a symmetric NAT. When the verdict is symmetric the
pair needs a port forward, a relay, or a network that maps ports consistently.
Without a STUN server the verdict stays empty.

## Host addresses from the tunnel

Each tunnel knows an address for the host it serves: the target the peer
forwards to, or the peer's own address. sync_punch_hosts.py writes that
address into the CheckMK host configuration (ipaddress) and removes the
real_ip label that used to carry it. A mapping file lists which instance
belongs to which host; an entry marked manual takes the address from the
real_ip label set by hand at install time and removes the label after the
copy. That is how an appliance behind a proxy peer - a firewall whose agent
is reached through another machine - gets the address its operator chose.

The hosts need a host check that does not use ICMP, because the monitoring
server cannot reach their private addresses: a host_check_commands rule with
value ok covers them.

```sh
sync_punch_hosts.py --mapping /etc/cmk-punch/hosts.json --dry-run
sync_punch_hosts.py --mapping /etc/cmk-punch/hosts.json
```

Run it from a timer. It talks to the local REST API with an automation user
and the secret from the site's automation.secret file, and it activates the
changes with cmk -O only when something moved. CMK_API_USER and CMK_SITE set
the user and the site when the defaults do not fit.

## Windows host

The host role also runs on Windows, where it forwards each stream to a local
TCP target - the CheckMK Windows agent listens on 127.0.0.1:6556 - because
the command pipe used on Linux is not available there. The server role stays
Linux-only: it needs systemd, the Unix socket and the CheckMK site.

```powershell
powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1
powershell -ExecutionPolicy Bypass -File .\install_udp_punch_windows.ps1 `
    -PskFile .\psk -Peer <server>:6015
```

build_udp_punch_exe.ps1 builds a self-contained executable with PyInstaller in
onedir mode: dist\cmk-punch\cmk-punch.exe plus its `_internal` directory, about
25 MB, no Python needed on the target. When that folder exists next to the
installer the installer uses it automatically; -ExeDir points to another
build. -CertificateThumbprint signs the executable with signtool when a
code-signing certificate is available, otherwise the build is unsigned and the
antivirus exclusion still applies.

The script installs under C:\ProgramData\cmk-punch, writes host.json,
generates or imports the pre-shared key with a restricted ACL, opens the UDP
port in Windows Firewall and registers the scheduled task cmk-punch-host,
which starts the peer at boot as SYSTEM; the log is peer.log in the logs
directory. -Staging writes only the files and needs no elevation,
-NoStart registers the task without starting it, -Uninstall removes task,
firewall rule and code, and -Uninstall -Purge also deletes configuration,
key and state.

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

## Status dashboard

punch_dashboard.py collects the state of every server instance from
/etc/cmk-punch (unit active, restart count, peer real address, last handshake
or teardown from the journal) and serves one HTML page plus /api/status and
/api/probe?inst=NAME on a loopback address. The probe runs the agent client
through the instance Unix socket with a timeout, so the test button shows the
end-to-end result and not only the process state.

Install on the monitoring host:

```bash
install -m 0755 punch_dashboard.py /opt/cmk-punch/punch_dashboard.py
```

```ini
[Service]
ExecStart=/usr/bin/python3 /opt/cmk-punch/punch_dashboard.py --listen 127.0.0.1:8099
```

The dashboard, punch_check.py and the sidebar snapin are not covered by
install_udp_punch.py: they are installed by hand, so a rebuilt monitoring host
needs these steps repeated.

Reach it through an SSH local forward, never from a public address:

```bash
ssh -N -L 8099:127.0.0.1:8099 <monitoring-host>
```

then open <http://127.0.0.1:8099/>. --once prints the JSON and exits,
--self-test checks the journal parsing and the state classification.

## CheckMK integration

punch_check.py is a CheckMK datasource program: it reads the status snapshot
written by punch_dashboard.py and prints one local check per instance plus a
summary, so the tunnels become native services with history and alarms. It
runs as the CheckMK site user, which cannot read the system journal, so the
snapshot is the data source. The UDP punch feed service is emitted on every
run and turns UNKNOWN when the snapshot is missing or older than --max-age
(300 s by default), so a dead writer cannot leave the tunnel services stale
and green.

Create a host object (for example punch-tunnels) whose datasource is the
program:

```bash
/usr/bin/python3 /usr/local/lib/cmk-punch/punch_check.py
```

punch_dashboard.py writes the snapshot every 60 seconds with
--status-file (default /var/lib/cmk-punch-dashboard/status.json) and
--refresh-s.

checkmk/punch_snapin.py is a sidebar snapin for CheckMK 2.5: it renders the
same snapshot in the navigation sidebar with a link to the services view.
Install it under local/lib/python3/cmk/gui/plugins/sidebar/ and create a
custom sidebar element of type "UDP punch" in Setup. The snapin is a
CustomizableSidebarSnapin because the sidebar element page lists only
customizable types, and it uses internal CheckMK interfaces: re-check it
after a major upgrade.

## Roadmap and known limits

Status as of 2026-11-25. Closed items stay listed so the rationale behind each
choice is not lost.

- Symmetric NAT (mitigated). The STATUS exchange compares the STUN mapping with
  the address the peer observes, logs the verdict (cone, symmetric,
  mapping-changed) and shows it in the peer view. The punch still fails behind
  a symmetric NAT: the workaround stays out of band.

- Throughput (open). Each frame carries at most 1150 bytes and the
  per-direction window defaults to 32 frames (Go-Back-N, cumulative ACKs,
  retransmission). There is no congestion control and the window is not
  adaptive; a full agent fetch is about 100 frames.

- One peer per process (mitigated). Each peer gets its own server instance,
  with its own UDP port, socket, state directory and unit. A multi-peer server
  that maps endpoint to session is not implemented, and there is no relay or
  automatic fallback.

- PSK distribution and rotation (mitigated). rotate-psk gives each pair its
  own key file and describes the rotation procedure, and p11 pins an Ed25519
  identity per side, so the PSK is a second factor rather than the only
  authentication: a leaked key alone no longer lets anyone impersonate a peer.

- Metadata (open). Padding fixes the frame size, but the number of frames per
  transfer and the poller cadence remain observable. Cover traffic at a
  constant rate is not implemented.

- Server instance generator (mitigated). new-instance writes a whole server
  instance from a template, with a dedicated PSK and identity, the unit and
  the firewall rule; it still needs a free UDP port and the peer's public key
  chosen by hand.

- Peer-side status (mitigated). The peer sends a STATUS control frame inside
  the session and the server keeps it in peer_status.json, which the dashboard
  shows as the peer view; a peer with an older build sends nothing and the
  column stays empty.

- Protocol version in HELLO (mitigated). The signed identity block carries the
  protocol byte, the receiver logs a mismatch at handshake and the peer status
  reports it; the layout still changes when the protocol does, so both sides
  are updated together.

- Python 3.6 compatibility (open). The source targets modern Python; a host
  with 3.6 needs a local patch to the future import at every update.
