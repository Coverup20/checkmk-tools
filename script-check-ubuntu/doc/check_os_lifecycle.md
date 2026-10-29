# check_os_lifecycle

Reports whether the operating system running on the host is still covered by
security updates. It reads `ID` and `VERSION_ID` from `/etc/os-release`,
resolves them against an embedded lifecycle table, and emits a single
`OS.Lifecycle` service with the number of days left before end of support as
perfdata (`days_to_eol`, negative once support has ended).

This check maps to NIS base measure **PR.PS-02.1** — only software for which
security updates are guaranteed may be installed — and the control code is
printed in the WARNING and CRITICAL messages so the service output doubles as
evidence.

## States

| State | Meaning |
| --- | --- |
| `0` OK | Supported, and more than 180 days remain before end of support. |
| `1` WARNING | End of support is within 180 days, **or** free support has already ended while extended support (Ubuntu Pro ESM / Debian ELTS) is still running. |
| `2` CRITICAL | Support has ended and no extended support exists. Security updates are no longer guaranteed. |
| `3` UNKNOWN | `/etc/os-release` is missing or unreadable, the release is absent from the table, or the table is too old to trust a "supported" verdict. |

The distinction behind the WARNING state matters: extended support exists only
with an active paid subscription, which this check cannot verify from the host.
It therefore reports the situation and asks for confirmation rather than
assuming either outcome.

## Embedded lifecycle data

The table is embedded deliberately. A local check runs on every host at every
cycle, so it must not depend on an external service to produce a verdict and
must work on hosts with no outbound connectivity.

`DATA_AS_OF` records when the table was last refreshed. Once it is older than
`STALE_AFTER_DAYS` (180), an otherwise-OK verdict is downgraded to UNKNOWN,
because stale data can hide a release that has since reached end of life.
Staleness never softens a WARNING or CRITICAL verdict: data age can only
invalidate a claim that something is *still* supported.

Dates come from endoflife.date, cross-checked against the vendor lifecycle
pages. Refresh the table and bump `DATA_AS_OF` before each release.

## Covered distributions

Ubuntu (LTS and recent interim releases), Debian 9-13, Rocky Linux 8-10.
`VERSION_ID` minors are dropped for Debian and the RHEL family, so Rocky
`9.5` resolves to `9`.

## Known limitations

- Proxmox VE hosts report `ID=debian`, so the verdict reflects the Debian base
  rather than the Proxmox VE lifecycle, which runs on its own schedule.
- Whether an Ubuntu Pro or Debian ELTS subscription is actually active is not
  verified; that is deferred to a later check.
- Packages are not examined, only the OS release. Per-package security status
  belongs to the patch posture and vulnerability checks.

## Usage

```bash
# Normal invocation (what CheckMK runs)
python3 check_os_lifecycle.py

# Self-test: exercises the verdict logic against fixed data
python3 check_os_lifecycle.py --self-test
```

The self-test exits non-zero if any case fails, so it can gate a release.

## Compatibility

Must stay compatible with **Python 3.9**, the oldest interpreter in the fleet
(Rocky 9 ships 3.9). Verified on Ubuntu 22.04 with Python 3.10 and on Rocky 9.8
with Python 3.9.
