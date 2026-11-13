# sync_update

Repository synchronization and script/config update utilities.

## Auto-Git-Sync (Timer-Based Model)

The auto-git-sync system keeps `/opt/checkmk-tools/` synchronized with the upstream repository using a Python-managed, systemd timer-based architecture.

### Architecture

**Python-First Design:**
- Installer and orchestration logic is implemented in `../installation/install-checkmk-agent-linux.py`
- Configuration and scheduling are managed by Python code
- Minimal Bash wrapper is generated at installation time for systemd integration

**Runtime Model:**
- **Systemd Timer:** `auto-git-sync.timer` (configurable interval, default 30 seconds)
- **Oneshot Service:** `auto-git-sync.service` (Type=oneshot, triggered by timer)
- **Minimal Wrapper:** `/usr/local/bin/checkmk-git-sync.sh` (generated, not maintained in repo)
- **Fallback Cron:** On systems without systemd, sync runs every minute via crontab

### Sync Operation

Each sync cycle:
1. `git fetch origin main` — Fetch latest commits from upstream
2. `git fetch --tags origin` — Update release tags for traceability
3. `git reset --hard origin/main` — Reset working tree to upstream state
4. `git clean -fd` — Remove untracked files (safe on deploy clone)
5. Log status to `/var/log/auto-git-sync.log`

### Installation

```bash
# Install with systemd timer (default interval 30 seconds)
python3 ../installation/install-checkmk-agent-linux.py --git-interval 30

# Or with custom interval (5 minutes)
python3 ../installation/install-checkmk-agent-linux.py --git-interval 300
```

### Status and Logging

```bash
# Check timer and service status
systemctl status auto-git-sync.timer
systemctl status auto-git-sync.service

# View recent logs
tail -f /var/log/auto-git-sync.log
journalctl -u auto-git-sync.service -f

# Trigger immediate sync
systemctl start auto-git-sync.service

# List next scheduled runs
systemctl list-timers auto-git-sync.timer
```

### Cron Fallback (OpenWrt / No Systemd)

On systems without systemd, the installer automatically configures crontab:

```cron
* * * * * cd /opt/checkmk-tools && git fetch origin main && git fetch --tags origin && git reset --hard origin/main && git clean -fd >> /var/log/auto-git-sync.log 2>&1
```

### Design Rationale

- **Python Orchestration:** All orchestration, configuration, and logic is Python-based (Python-first policy)
- **Minimal Bash Wrapper:** The actual sync command is kept minimal for systemd integration, not as a maintained script
- **Systemd Timer:** Leverages standard systemd timers for reliability and easy interval adjustment
- **Stateless Design:** Each sync is independent; no long-running daemon process
- **Read-Only Deploy Clone:** The deploy clone `/opt/checkmk-tools/` is reset hard on every sync; safe for production use

## Local Check Distribution from a GitHub Release

The release-based model removes the repository clone from the monitored host.
It mirrors the Windows model (`sync_winchecks.ps1`): a public GitHub release
carries the checks plus a `manifest.json`, and an unprivileged HTTP downloader
keeps the agent local directory in sync. No GitHub account and no clone are
needed on the host.

### Components

| Script | Runs on | Purpose |
| --- | --- | --- |
| `build_publish_linux_checks.py` | operator workstation | collects `check*.py` from every Linux category, writes the assets and the manifest, optionally publishes the release |
| `sync_linuxchecks.py` | monitored host | reads the manifest, downloads only the missing or changed checks, verifies sha256, installs them atomically into the agent local directory |
| `install_sync_linux.py` | monitored host | copies the downloader into `/usr/local/bin` and schedules it (systemd timer, cron as fallback) |

Windows categories are never part of the Linux release: that side is served by
`build_publish_windows_checks.ps1` and `sync_winchecks.ps1`.

### Release Layout

One release per build, tag `linuxchecks-YYYY.MM.DD`. Every asset carries the
category in its name (`ubuntu--check_disk_space.py`) because the same file name
can exist in two categories; the manifest states the deployed name, which on
Linux is the file stem without extension:

```json
{
  "tag": "linuxchecks-2026.11.13",
  "categories": ["ns7", "ns8", "nsec8", "proxmox", "ubuntu", "tmate-server"],
  "checks": [
    {
      "category": "ubuntu",
      "name": "check_disk_space",
      "source": "check_disk_space.py",
      "asset": "ubuntu--check_disk_space.py",
      "sha256": "...",
      "size": 2713
    }
  ]
}
```

### Publishing

```bash
# Build into a temporary directory, no network
python3 build_publish_linux_checks.py

# Build and publish (gh must be authenticated)
python3 build_publish_linux_checks.py --publish

# Publish a draft first, then test the downloader against it
python3 build_publish_linux_checks.py --publish --draft
```

### Installing on a Host

```bash
# Preview, then install and schedule the sync every 5 minutes
python3 install_sync_linux.py --dry-run
python3 install_sync_linux.py

# Or run the downloader by hand with a temporary target
python3 sync_linuxchecks.py --categories ubuntu --target /tmp/local-preview --dry-run
```

### Behavior and Safety

- **Category detection:** `auto` recognizes NS7, NS8, NethSecurity 8, Proxmox
  and generic Debian/Ubuntu, plus the `tmate-server` role on any base, with the
  same rules as `sync-python-full-checks.py`.
- **Atomic install:** the verified copy is staged, then copied to a temporary
  name inside the target directory and renamed over the destination, so the
  agent never runs a half-written check.
- **Exclusions:** `/etc/checkmk-python-full-sync.exclude` is honored, one check
  name per line; excluded checks are neither installed nor removed.
- **Prune:** only checks previously deployed by this tool (tracked in
  `<staging>/state.json`) are removed when they leave the release. Hand-written
  files in the local directory are left untouched.
- **Rollback copy:** the replaced version is kept in `<staging>/previous`.
- **Defaults:** staging `/var/lib/cmk-sync`, target
  `/usr/lib/check_mk_agent/local`, state and `manifest.json` in the staging
  directory.

### Migration from auto-git-sync

The two mechanisms can coexist, but they both write the agent local directory,
so a host runs only one of them. The switch is always an explicit operator
action: no script here disables or removes `auto-git-sync`.

1. Install the downloader and run it once against a temporary target to check
   the result:

   ```bash
   python3 install_sync_linux.py --no-schedule
   python3 /usr/local/bin/sync_linuxchecks.py --dry-run \
       --target /tmp/local-preview
   ```

2. Let it deploy for real, then compare the agent local directory with what
   the git clone had produced (`diff -r` between the deployed names and
   `script-check-*/full/*.py`). The release manifest only carries `check*.py`,
   so any hand-written or non-`check` file stays where it is.

3. Disable the git clone:

   ```bash
   # systemd hosts
   systemctl disable --now auto-git-sync.timer
   # OpenWrt and other cron hosts: remove the auto-git-sync line
   crontab -l | grep -v auto-git-sync | crontab -
   ```

4. Keep `/opt/checkmk-tools` for a few days. Remove it only after the local
   directory is stable and CheckMK has discovered the same services:

   ```bash
   rm -rf /opt/checkmk-tools
   ```

5. Rollback: re-enable `auto-git-sync` and disable
   `cmk-local-checks-sync.timer`. The checks already deployed stay in place,
   so service discovery does not flap during the switch.
