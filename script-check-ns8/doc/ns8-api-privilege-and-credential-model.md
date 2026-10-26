# NS8 API privilege and credential model

How the REST-only CheckMK checks authenticate against an NS8 node, what a
read-only API account really protects, and what it does not. Written after a
least-privilege review of a lab node; every statement below was verified on a
running NS8 node, not taken from documentation.

## Why the checks use a dedicated read-only account

The checks run on the node itself, as root, and reach the node's own API over
loopback. A reasonable objection is: root on the node can already drive the
cluster without any account, so why store an account's password at all?

Both halves of that are true, and they do not cancel out:

- Root on the node **is** a full cluster administrator. `api-cli` falls back to
  the `redis://cluster-leader` endpoint using the node's own agent identity,
  whose credentials sit in the cluster agent environment file (mode 0600,
  root-owned). That identity holds `+@all` on `~*` in the Redis ACL, and the
  API server accepts its actions while bypassing the role system entirely -
  `api-cli`'s own source comments say the `cluster` user "has no roles. It can
  run actions with redis:// endpoint though". This was demonstrated, not
  inferred: as root, with no user token of any kind, a user-management action
  was executed that **changed a stored attribute of an existing account**, the
  new value was read back through the API, and the original value was then
  restored. Privileged writes therefore succeed with no user credential at all;
  a refusal is never what stops them.
- The read-only account still matters, for a different reason: it constrains
  the **automated** path. A monitoring script that authenticates as a reader
  cannot write, even if it has a bug, even if its logic is subverted. Every
  write action tested against such an account is refused, including the ones
  that would disclose module master credentials.

So the account is not a gate against an attacker who already owns the node. It
keeps unattended code inside a boundary that is provable, and it keeps the
blast radius of a leaked check-side credential at "read".

## The asymmetry that decides where hardening pays off

Root's power is **local**: it depends on a root-only file on the node itself.
An API account's password is **portable**: by default it works from any network
that can reach the cluster admin route through the node's reverse proxy. That
asymmetry, not the file permissions, is what makes a stored password worth
attacking.

The practical consequence: restrict the account's `allowed_networks` to
loopback. The checks are unaffected, because they reach both the API and the
metrics route over loopback. A copy of the password taken off the node - from a
backup, a VM snapshot, a stray archive - then buys nothing that standing on the
node did not already give.

A remote consumer of the same account (for instance an MCP server on another
host querying the API over HTTPS) stops working when this is applied. Decide
that trade deliberately: either accept it and reach the API through SSH on the
node for ad-hoc work, or list the specific remote address alongside loopback.

## What cannot be achieved

Making the stored credential unreadable **to root on the node** is not
achievable while an unattended root process must present it to the API. Any
local encryption needs a key the same root can read.

`systemd-creds` with `LoadCredential=` is the right shape for the problem - the
plaintext would exist only in a tmpfs for the service's lifetime, and the check
would still just read a file path, so the REST-only design is untouched. Its
value depends entirely on TPM sealing. Without a TPM the encryption key is
stored next to the encrypted file on the same disk, so an offline copy still
yields the secret and the gain is close to cosmetic. On a virtual machine,
adding a virtual TPM is therefore a prerequisite for this to be worth doing.

Moving the secret into the kernel keyring removes it from disk entirely, but it
has to be re-entered by hand after every reboot - during which the dependent
services report UNKNOWN. On a monitoring host that is usually the wrong trade.

## The grant model, and two traps

Authorization has two independent layers, stored separately:

1. **User to role bindings** - which role a user holds on each object
   (`roles/<user>` in Redis, a hash of `object -> role`). Objects are prefixed
   agent ids: `cluster`, `node/<n>`, `module/<id>`.
2. **Role to action mappings** - which actions a role may run on an object
   (`<object>/roles/<role>`, a set of action names, wildcards allowed).

Granting a role binding uses `alter-user` with a `grant` list of
`{"role": ..., "on": ...}`. Granting an action to a role uses `grant-actions`
with `{"action": ..., "to": <role>, "on": <object>}`.

**Trap 1 - the `on` clause must carry the prefix.** `grant-actions` with a bare
module name returns an empty object, exactly like a success, and grants
nothing. The `on` field must be `module/<id>`, `node/<n>` or `cluster`. Always
confirm a grant by re-running the real call, never by trusting the return
value.

**Trap 2 - the session token freezes the role bindings.** The token returned by
the login endpoint carries the user's role bindings as they were at login time,
while role-to-action mappings are resolved live on every call. The visible
effect is confusing: adding an action to a role takes effect immediately even
for an old cached token, but binding the user to a role on a new object does
not - calls keep failing with a permission error until the account logs in
again. **After any `alter-user` grant, refresh any cached token file**, or the
check that uses it will keep reporting UNKNOWN for no apparent reason.

Grants that are easy to miss: a role on the node object is needed for actions
that target `node/<n>` rather than a module, and the metrics route behind the
reverse proxy is authorised by a dedicated action on the metrics module - a
forward-auth middleware calls the API server, so a refusal there surfaces as an
HTTP 403 from the proxy and looks like a dashboard permission problem when it
is really a plain action grant.

## Local exposure worth knowing about

The cluster's Redis instance accepts unauthenticated local connections as the
`default` user, which is configured without a password and holds read
permission over the `cluster/*`, `node/*` and `module/*` key spaces. This was
verified from an unprivileged local account: key existence, types, field counts
and field names all come back without any credential.

Two consequences:

- Any local account on the node - including the unprivileged users that
  rootless module containers run as - can read cluster state, and some module
  environment hashes contain fields whose names denote service passwords.
- A node-local credential file with mode 0600 is therefore **not** the weakest
  link on the host. Reviewing what the key spaces expose is the higher-value
  exercise.

Changing this ACL is an upstream design decision, not a local tuning knob:
modules may depend on unauthenticated reads. Treat it as a finding to raise,
not as something to tighten in place.

## Network exposure: verify, do not assume

Redis and the API server bind to all interfaces, which looks alarming until the
host firewall is read: neither port is published by the firewall zone, so
neither is reachable off-node. The exposed surface is the reverse proxy and the
services the zone explicitly allows.

One caveat that produced a wrong conclusion during this review: when the
workstation reaches the node through a zero-trust client, a TCP connect test
succeeds even for ports the host firewall blocks, because the connector
completes the handshake locally. **A port check through such a client proves
nothing.** Send a real protocol exchange instead - an SSH banner, an HTTP
response - and compare against a port known to be open. Ports that connect but
return no data are not actually reachable.

## Monitoring agent exposure

The agent runs in pull mode: the monitoring server opens the connection to the
agent's port, so that port can never be bound to loopback without ending data
collection. Restrict it instead by listing the monitoring server in the agent
controller's allowed-IP setting, and optionally with a firewall rule limited to
the same source, which has the advantage of not answering at all.

Note for anyone reusing the installer in this repository: its agent
configuration routine also deletes existing registrations and enables legacy
plain pull. On a node registered with TLS, apply only the allowed-IP part by
hand, or the registration is destroyed.

## Checklist for a new node

1. Create the automation account as a reader, and grant it a role on every
   object it must read, including the node object - module roles alone are not
   enough.
2. Grant individually the extra actions the checks need; do not promote the
   account to owner to make one call work.
3. Set `allowed_networks` to loopback, plus any deliberately chosen remote
   address.
4. Refresh any cached token file after the grants are complete.
5. Verify by running the full agent output and confirming no service reports
   UNKNOWN - and give the run enough time to finish, since a truncated run
   looks deceptively clean.
6. Restrict the agent port to the monitoring server.
