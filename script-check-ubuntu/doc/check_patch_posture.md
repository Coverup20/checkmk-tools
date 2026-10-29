# check_patch_posture

Reports how long security updates have been left uninstalled. Supports `apt`
(Debian/Ubuntu) and `dnf` (Rocky/RHEL family), detected at runtime, and emits
a single `Patch.Posture` service with `security_updates`, `total_updates` and
`oldest_days` as perfdata.

This check maps to NIS base measure **PR.PS-02.2** — the latest vendor security
updates are installed without undue delay — and the control code is printed in
the WARNING and CRITICAL messages so the service output doubles as evidence.

## States

| State | Meaning |
| --- | --- |
| `0` OK | No pending security updates, or some pending but still inside the grace period. |
| `1` WARNING | Pending past the grace period; or a reboot is required to activate updates already installed; or this is the first run on the host. |
| `2` CRITICAL | The oldest pending security update is past the remediation deadline. |
| `3` UNKNOWN | No supported package manager, the package manager failed, or the metadata is too stale for an empty result to mean anything. |

## Thresholds are provisional

"Without undue delay" is a governance decision, not a technical constant: the
owning organisation has to state the number of days and accept it. The
defaults below are placeholders so the check is usable now, and each can be
overridden per host through the environment.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHECK_PATCH_GRACE_DAYS` | 7 | Below this age, pending updates are tolerated. |
| `CHECK_PATCH_SLA_DAYS` | 14 | At or beyond this age, CRITICAL. |
| `CHECK_PATCH_METADATA_DAYS` | 3 | Older metadata makes an empty result untrustworthy. |

## How ageing works, and what it does not claim

Nothing on the host records when an update became available, so this check
keeps its own state file and measures age from the moment it first saw a
package listed. The message says "first seen" rather than "released" on
purpose: it is **time since this check noticed**, not time since the vendor
published.

State lives in `/var/lib/check_mk_agent/patch_posture_state.json`, falling back
to `/var/tmp/`. Packages that are no longer pending are pruned, so a package
reinstalled later does not inherit the age of an earlier occurrence. If the
file cannot be written the check still produces a verdict, just without ageing.

**The first run on a host reports WARNING, not OK**, whenever security updates
are pending. There is no history yet, so every update looks new, and reporting
OK would hand a clean bill of health to a host that might have been neglected
for a year. The check says what it actually knows and starts ageing from there.

## The stale-metadata guard

An empty update list is only meaningful if the package metadata is fresh. A
host that has not refreshed its lists reports zero pending updates and looks
healthy while being months behind — the same failure mode as a vulnerability
scan that returns "clean" against an unsupported base.

When metadata is older than `CHECK_PATCH_METADATA_DAYS`, or its age cannot be
determined, the check reports UNKNOWN rather than OK. Not knowing is not the
same as being up to date.

This guard matters most on `apt`, where simulating an upgrade does not refresh
the lists. On `dnf` the query refreshes metadata as a side effect, so the age
read back is almost always near zero; the guard still catches the case where
`dnf` cannot reach its repositories, which surfaces as UNKNOWN.

## Reboot detection

A security update that is installed but not yet active leaves the host exposed.
Detection differs by platform:

- Debian/Ubuntu: presence of `/var/run/reboot-required`.
- RHEL family: `needs-restarting -r`, exit 1 meaning a reboot is required.
  On RHEL 8+ this is a **dnf plugin**, not a binary on `PATH`; only older
  `yum-utils` installs a standalone command. The check tries both forms.
  Missing this is exactly how a host running an old kernel while the patched
  one sits installed gets reported as healthy — it was a real bug found
  during testing on Rocky 9.

## Known limitations

- Age is measured from first observation by this check, not from vendor
  release. A more precise figure would need advisory dates from the vendor
  feeds, which belongs to the vulnerability correlation work, not here.
- `apt-check`, where present, returns counts rather than package names, so
  ageing on those hosts is per-slot rather than per-package: a changing set
  of the same size keeps its age. The fallback path parses real names.
- Severity is not weighted. Every security update counts the same, so a
  critical remote-code-execution fix and a minor one age identically.
  Prioritisation by KEV/EPSS belongs to a later check.

## Usage

```bash
# Normal invocation (what CheckMK runs)
python3 check_patch_posture.py

# Self-test: exercises the verdict and ageing logic against fixed data
python3 check_patch_posture.py --self-test
```

The self-test exits non-zero if any case fails, so it can gate a release.

## Compatibility

Must stay compatible with **Python 3.9**, the oldest interpreter in the fleet
(Rocky 9 ships 3.9). Verified on Ubuntu 22.04 with Python 3.10 and on Rocky 9.8
with Python 3.9.
