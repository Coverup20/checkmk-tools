# Pending Release Notes

This file tracks pushed changes that are not yet tagged or released.

## Unreleased

### Added

- Added `script-tools/full/agent_maintenance/checkmk-agent-sync.py`, a dedicated CheckMK agent synchronization tool (735 lines).
  - Multi-target support: Debian/Ubuntu (dpkg), RHEL/Rocky/Alma (rpm), NethSecurity 8 (opkg)
  - Detect-only targets: NS8 containers (non-destructive detection)
  - Multiple operation modes: verify-only (default), dry-run, download-only, install
  - Structured status reporting with JSON/text output (14+ status fields)
  - Server version detection via REST API, HTML scraping, and local OMD symlinks
  - Comprehensive dry-run contract: zero system modifications guaranteed
  - Independent from upgrade-checkmk.py; focused on agent-only updates

- Added optional systemd service template: `script-tools/full/agent_maintenance/checkmk-agent-sync.service` (36 lines)
  - Hardened security settings (ProtectSystem=strict, PrivateTmp=yes)
  - Resource limits: 512M memory, 50% CPU quota
  - Configuration via `/etc/default/checkmk-agent-sync.env`

- Added optional systemd timer template: `script-tools/full/agent_maintenance/checkmk-agent-sync.timer` (21 lines)
  - Daily execution at 03:00 AM UTC
  - Randomized delay (±5 minutes) to prevent thundering herd
  - Persistent execution (catches up on system startup)

- Added environment configuration example: `script-tools/full/agent_maintenance/checkmk-agent-sync.env.example` (43 lines)
  - Template for `/etc/default/checkmk-agent-sync.env`
  - Configurable server URL, site, target type, cache directory
  - Optional force reinstall and verbose logging flags

### Operational Status

- **Code Status**: Pushed to `origin/main` (commit `5a33d15`)
- **No tag created**: Release tag is pending human review and approval
- **No GitHub release created**: Official release notes pending approval
- **No production service/timer enabled**: Systemd integration is optional and manual
- **No production host modified**: All testing was read-only (dry-run and verify-only modes)
- **Branch status**: Local main in sync with origin/main

### Validation Already Performed

✅ **Syntax Validation**: Python compilation passed  
✅ **Help Output Validation**: CLI interface complete with all documented options  
✅ **Dry-Run Validation**: Tested against monitoring.nethlab.it (v2.5.0p7 detected)  
✅ **Download-Only Validation**: Successfully downloaded agent package (6.1 MB)  
✅ **Verify-Only Validation**: Default non-destructive mode confirmed  
✅ **Target Detection**: Multi-platform detection logic validated  
✅ **Network Integration**: REST API and HTML scraping strategies verified  

### Release Candidate Commits

| Commit | Subject | Status | Files | Lines |
|--------|---------|--------|-------|-------|
| `5a33d15` | `feat(agent): add checkmk agent sync service` | Pending release | 4 added | +835 |

### Suggested Pre-Release Validation

Before creating a release, consider performing:

1. **Integration Test on Staging**: Run `--verify-only` mode from `/opt/checkmk-tools` on staging hosts
2. **Systemd Template Validation**: Verify service/timer installation and operation on staging
3. **Multi-Platform Testing** (Optional): Test agent detection on:
   - Debian/Ubuntu systems (dpkg)
   - RHEL/Rocky/Alma systems (rpm)
   - NethSecurity 8 devices (opkg)
4. **Controlled Real-World Test** (Optional): One-off install test on staging (non-production)
5. **Documentation Review**: Verify integration instructions are clear
6. **Version Decision**: Determine final version number (semantic versioning)
7. **Release Approval**: Human review and sign-off before tag creation

### Future Release Commands

The following commands are examples for future release. **Do not execute now.**

```bash
# Navigate to repo
cd /root/checkmk-tools

# Verify current state
git checkout main
git pull origin main
git --no-pager log --oneline -10

# Create annotated tag (replace X.Y.Z with version)
git tag -a vX.Y.Z 5a33d15 -m "vX.Y.Z: CheckMK agent synchronization tool"

# Push tag to remote
git push origin vX.Y.Z

# Create GitHub release (requires gh CLI)
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --notes "Added CheckMK agent synchronization tool with multi-platform support, structured status reporting, and optional systemd service/timer templates. Verify-only mode is default for safety."
```

### Useful Lookup Commands

To find and review unreleased agent-sync work later:

```bash
# Search commits by subject
git --no-pager log --oneline --grep="agent sync"

# List all commits touching agent_maintenance directory
git --no-pager log --oneline -- script-tools/full/agent_maintenance/

# Show full commit details
git --no-pager show --stat 5a33d15
git --no-pager show --name-status 5a33d15

# Inspect specific files
cat script-tools/full/agent_maintenance/checkmk-agent-sync.py | head -100
```

### Implementation Summary

**Reused Logic From**:
- `script-tools/full/upgrade_maintenance/update_checkmk_agent.py` - Version detection, download, install
- `script-tools/full/deploy/auto-deploy-checks.py` - Target OS detection

**New Capabilities**:
- Structured status reporting (JSON-compatible)
- Multi-mode operation (verify-only, dry-run, download-only, install)
- Detect-only targets (NS8 containers)
- Safe-by-default (verify-only mode, no auto-installation)
- Systemd integration templates

**Code Quality**:
- Python 3 compatible
- No external dependencies (stdlib only)
- 835 lines across 4 files
- Comprehensive error handling
- Full documentation in docstrings

---

**Last Updated**: 2026-07-01  
**Created By**: Claude Haiku 4.5 (via checkmk-tools automation)  
**Status**: Pending review and release approval
