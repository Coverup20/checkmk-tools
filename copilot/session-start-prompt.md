# Session Start Prompt - checkmk-tools

Copy and paste this prompt at the start of any new session to give the agent full context.

---

```
Before starting any work, read the following memory files in order and internalize all rules:

## User memory (persistent rules):
- /memories/backup-before-modify.md
- /memories/checkmk-passive-checks.md
- /memories/checkmk-stall-recovery.md
- /memories/hosts.md
- /memories/srv-monitoring-permissions.md

## Repository memory (project-specific):
- /memories/repo/hosts-access.md       → SSH access method per host (key vs password)
- /memories/repo/copilot-scripts-index.md   → Index of all copilot/ scripts and their purpose
- /memories/repo/copilot-scripts-policy.md  → Where to save temporary scripts (always copilot/)

## Workspace instructions:
- .github/copilot-instructions.md      → MASTER RULES: git workflow, safety, versioning, Python-first policy
- .copilot-context.md                  → Auto-sync architecture, language preferences, repo structure
- script-check-ns8/copilot-instructions.md  → NS8-specific check rules

## Key facts to remember immediately:
- Workspace: C:\Users\Marzio\Desktop\CheckMK\checkmk-tools
- Git remotes: origin = Coverup20/checkmk-tools, upstream = nethesis/checkmk-tools
- Default push: origin only. Push upstream only on explicit user confirmation.
- srv-monitoring-sp: 45.33.235.86:2333, root, ProxyJump sos MANDATORY, key ~/.ssh/copilot_srv_monitoring
  - Command: wsl -d kali-linux bash -c "ssh srv-monitoring-sp 'cmd'" (NO -tt flag)
  - All files must be monitoring:monitoring
- nsec8-stable: 10.155.100.100:22, password auth → give commands to paste, do NOT run_in_terminal
- checkmk-vps-01/02: wsl -d kali-linux bash -c "ssh checkmk-vps-0X 'cmd'" (key, passphrase)
- Temporary scripts: ALWAYS save in copilot/ folder, NEVER in workspace root
- All new scripts must be Python, follow Nethesis style (no classes, no type hints, flat functions)
- NEVER touch active_checks_enabled without explicit user confirmation
- Chat language: Italian always

After reading all files, confirm with: "Contesto caricato. Pronto."
```
