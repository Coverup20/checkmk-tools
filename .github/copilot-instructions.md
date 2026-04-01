# GitHub Copilot Instructions - checkmk-tools

## MANDATORY PRELIMINARY RULE

** BEFORE STARTING ANY WORK:**

- **ALWAYS read THIS file** (`.github/copilot-instructions.md`) at the beginning of EVERY conversation
- **ALWAYS consult** this file before starting any task
- This file contains **ALL rules, workflows and mandatory procedures**
- **DO NOT start work** without reading and understanding the instructions
- If in doubt about how to proceed → **reread this file**

**Related files:**
- `.copilot-preferences.md` → Summary/quick reference (220 lines)
- `.github/copilot-instructions.md` → **THIS FILE** - Complete rules (~2250 lines, automatically updated)

---

## MANDATORY GENERAL RULES

### File language (script, code, comments, documentation)

- **ALL text in files must be in English**: comments, docstrings, log messages, descriptive variables, README, doc
- **New files**: write directly in English
- **Modified existing files**: Translate the touching parts into English
- **Gradual migration**: When editing an old script, translate the entire file into English
- **NEVER add Italian text** to code or documentation files

### Emojis in files

- **ZERO emojis in files** — no exceptions: scripts, code, comments, markdown, Copilot instruction files
- **Existing files modified**: Remove all emoji from entire file when tapping
- **New files**: never insert emojis

### Chat communications

- **Communications between us in chat always remain in Italian**

### No personal names or brand names in files

- **NEVER include names of people** (real names, usernames, GitHub handles, etc.) in any file
- **NEVER include internal brand names, customer names, or project codenames** in files
- Use generic references: "Nethesis style", "upstream standard", "reference codebase"
- If a person or brand must be referenced → use only the company name (e.g. "Nethesis")
- This rule applies to: code, comments, docstrings, markdown, instructions files — no exceptions

### No hardcoded environment data in files

- **NEVER hardcode** IP addresses, hostnames, domain names, ports, URLs that refer to a specific environment
- **NEVER hardcode** credentials, tokens, API keys, passwords, secrets of any kind
- **NEVER hardcode** filesystem paths that are environment-specific (e.g. `/omd/sites/monitoring/`, specific usernames)
- **NEVER hardcode** site names, tenant names, customer-specific identifiers
- **ALWAYS use** environment variables, config files, or parameters passed at runtime
- **ALWAYS use** placeholder values in examples: `YOUR_TOKEN_HERE`, `<hostname>`, `<ip_address>`
- If a default is needed → use a clearly fake/generic value that cannot be mistaken for real data
- This rule applies to ALL file types: scripts, config templates, markdown, instructions — no exceptions

### No archived/ folders — delete replaced scripts

- **NO `archived/` folders** — scripts that are replaced must be deleted, not archived
- **NEVER move superseded scripts to `archived/`** — delete them directly with `git rm`
- **NEVER keep old versions alongside new ones** — one version only, the current one
- Git history preserves the old versions — no need to keep them in the tree
- When replacing a script with a new one → `git rm` the old one in the same commit
- If `archived/` folders are found → delete them immediately

---

## FUNDAMENTAL WORKING PHILOSOPHY

** ZERO RULE - QUALITY FIRST: **

> **"PRICE TAKES TIME!!"**  
> _Doing things in a hurry = doing them 10 times instead of doing them right once_

- **DO THINGS RIGHT** - Use all the time necessary
- **NO SHORTCUTS** - Never skip steps without explicit user permission
- **ABSOLUTE COMPLETENESS** - Follow complete workflows to the end
- **THERE IS NO RUSH** - I have no commitments that force me to speed up
- **MANDATORY WORKFLOWS** - ALWAYS follow all documented steps
- **DO NOT "OPTIMIZE" VIA STEP** - Each workflow step has a reason to exist
- **BETTER SLOW AND CORRECT** - How fast and to be done 10 times

**Examples of what NOT to do:**
- Commit without testing on remote hosts → then redo 10 times
- Skip validations "it works anyway" → then debug for hours to find the error
- Omit steps "for speed" → then waste time recovering
- Assuming something works without testing → then discovering that it doesn't work in production
- **LA PRESCIA**: do it quickly = do it again 10 times

**Examples of what to DO:**
- Follow every step of the documented workflow → done right the first time
- ALWAYS test on remote hosts → no surprises in production
- Validate EVERY change → bugs found immediately, not later
- Take the time to do it right → save total time
- **NO HURRY**: do well = done only 1 time

** ABSOLUTE RULE - IF THE USER ASKS, JUST DO IT:**

> **"If you ask me, it's because you know I can do it"**

- **NEVER** respond with "I can't because..." when the user asks to do something
- **NEVER** give commands to paste when the user has asked to execute them independently
- **NEVER** explain technical limitations without REALLY trying to execute first
- **ALWAYS ATTEMPT** to do what you are asked, whatever the difficulty
- If there are real technical obstacles → solve them yourself, do not delegate to the user
- The user already knows your capabilities: trust their request and take action

---

## WORKFLOW GIT - Fork and Upstream

### Repository structure

| Remote | URL | Role |
|--------|-----|------|
| `origin` | `git@github.com:Coverup20/checkmk-tools.git` | **Work forks** — daily pushes |
| `upstream` | `git@github.com:nethesis/checkmk-tools.git` | **Official Nethesis Repo** — push upon release |

### MANDATORY rule - Due-push workflow

**All day-to-day work goes on `origin` (fork). Only when the job is completed does it push to `upstream`.**

**Complete Workflow:**

```bash
#1. Work normally, commit on fork
git add .
git commit -m "type(scope): vX.Y.Z - description"
git push origin main

# 2. Only when the work is FINISHED and tested → push to upstream Nethesis
git push upstream main
```

**Rules:**

- **During development**: push ONLY to `origin` (Coverup20 fork)
- **When work is completed**: same commit → push also on `upstream` (nethesis)
- **Same commit message** on both pushes (same commit, same tag/version)
- **NEVER** push on `upstream` without first testing on `origin`
- **NEVER** `git push` without specifying `origin` or `upstream` (may go to the wrong one)
- **Default push**: always `origin` unless otherwise specified by the user

**When to push upstream:**

- Feature/fix completed + tested on remote hosts
- User gives explicit green light ("ok, push on nethesis too")
- NEVER during development/debug iterations

---

## MANDATORY SAFETY RULES

### Data Protection and Confirmations

**ALWAYS respect these rules:**

1. **One command at a time** _(valid for DESTRUCTIVE operations or on remote systems)_
   - DO NOT execute multiple destructive commands without confirmation
   - Execute a destructive command, wait for user confirmation
   - ESPECIALLY for: deletions, file modifications, deployments, SSH commands
   - **EXCEPTION**: read-only tools in parallel are OK (grep, read_file, file_search, etc.)
   - **EXCEPTION**: `multi_replace_string_in_file` is OK for batch edit on the same file/project

    **Additional rule (MANDATORY): pause at the end of the command**
    - After EVERY command launched in terminal, add a short pause to allow the output to be read.
    - Default: **3 seconds**.
    - PowerShell (local): always add `; Start-Sleep -Seconds 3`
       - Example: `wsl -d kali-linux ssh host "uptime"; Start-Sleep -Seconds 3`
    - Bash (remote / inside SSH): add `; sleep 3`
       - Example: `ssh host "uptime; sleep 3"`
    - Objective: to prevent the output from "disappearing" immediately and reduce perceived errors/timeouts.

2. **Backup before deleting**
   - NEVER delete files/directories without backup
   - ALWAYS create backups before destructive operations
   - Backup format: `ORIGINAL_NAME.backup_YYYY-MM-DD_HH-MM-SS`
   - Confirm path backup with user before proceeding

3. **Confirm critical operations**
   - Cancellations
   - Massive changes (>10 files)
   - Deploy on production
   - Commands on remote systems

4. **Check Copilot preferences periodically**
   - Check `.github/copilot-instructions.md` regularly
   - Make sure you always follow the latest instructions
   - Suggest updates when necessary

5. **Stores useful information**
   - If you discover useful patterns/commands/procedures → add them to the copilot-instructions
- Workflows that work well must be documented
   - Common paths, standard configurations, troubleshooting tips

6. **Clean backup after test**
   - When tests on backed up files finish successfully
   - Propose removal of created backup files
   - WAIT for user confirmation before deleting
   - Never delete backups without explicit confirmation

7. **Automatic periodic integrity check**
   - During conversations, periodically propose `.\script-ps-tools\check-integrity.ps1 -SendEmail`
   - Check at appropriate times (after changes, major commits, user requests)
   - Send email if even 1 corrupt file is found
   - Email includes: list of corrupt files, error percentage, details
   - Don't send email if everything OK (console output only)

8. ** MANDATORY SENSITIVE DATA CONTROL **
   - **ALWAYS** check for sensitive data when creating/modifying a script
   - Scan for:
     - **Token**: API keys, auth tokens, access tokens
     - **Password**: hardcoded passwords, default credentials
     - **Secrets**: SSH/GPG keys, private certificates
     - **Credentials**: username+password, connection strings
     - **Private IP addresses**: if they expose critical infrastructure
     - **Internal domains**: if reserved/confidential
   - **CRITICAL PATTERNS to look for**:
     - `token=`, `password=`, `secret=`, `key=`
     - `AUTH_TOKEN=`, `API_KEY=`, `PRIVATE_KEY=`
     - Hardcoded alphanumeric long strings (token-like)
     - Default credentials with real values
   - **Corrective actions**:
     - Remove hardcoded values
     - Use environment variables without sensitive defaults
     - Force manual user input (with validation)
     - Use generic placeholders (`INSERT_TOKEN_HERE`)
   - **Mandatory workflow**:
     1. Before commit → scan modified scripts
     2. If sensitive data found → notify user
     3. Propose immediate fix (removal/env variables)
     4. Validate that the fix does not break functionality
     5. Remind the user to **rotate credentials** if already published

9. ** EFFICIENCY AND TOKEN CONTAINMENT - Think Before Acting**
   - **MONTHLY BUDGET**: 1500 usable tokens/month
   - **Extra budgets available BUT prefer NOT to use them** - keep them as an emergency reserve
   - **ALWAYS think and plan** before taking actions
   - **Decisional autonomy**: Making obvious decisions without asking for confirmation out of banality
   - **Deep reasoning**: Analyze available context, infer answers, infer user intent
   - **Capitalize first request token**: Use information already provided, avoid redundant questions
   - **Ask only if necessary**: Only for decisions with real impact or substantial ambiguity
   - **Fix attempt limit**: Max 3 iterations for the same problem
   - **If 3 attempts fail** → STOP and ask user for help
   - **Avoid infinite loops**: Don't repeat the same approach if it fails
   - **Incremental approach**: Small, tested fixes, not massive changes without validation
   - **Long sessions**: Every 15-20 interactions → short recap and confirmation of direction
   - **Massive operations**: Before modifications >20 files → ask for strategy confirmation
   - **DO NOT blindly iterate**: If a command fails 2 times → change approach
   - **Evaluate cost/benefit**: For long operations → propose more efficient alternatives
   - **Explicit reasoning**: For complex problems → explain action plan before executing

   **Example of AUTONOMOUS decisions (DO NOT ask):**
   ```text
    Fix obvious syntax (missing parenthesis, comma, etc.)
    Renumber lists after element insertion
    Update timestamps in backups
    Correct relative path → absolute (known workspace)
    Make .sh script executable with git update-index
    Descriptive commit message from obvious changes
   ```

   **Example decisions that REQUIRE confirmation:**
   ```text
    Delete data/files (even with backup)
    Deploy on production
    Choice between different technical approaches with trade-offs
    Changes that impact security/performance
    Choice between multiple hosts for testing when not obvious
   ```

   **Retry management example:**
   ```text
   Attempt 1: wsl bash -n script.sh → ERROR line 45
   Fix 1: Fix syntax → test
   
   Attempt 2: wsl bash -n script.sh → ERROR line 67
   Fix 2: fix second error → test
Attempt 3: wsl bash -n script.sh → ERROR line 45 (same line!)
    STOP: Approach doesn't work, pattern unclear
   → Ask for help: "I tried 3 times, error persists. Can I see the full context of line 45?"
   ```

   **When to stop and ask for help:**
   - Loop fix on the same error (>2 attempts)
   - Theoretically correct approach but fails repeatedly
   - Unclear or ambiguous errors after 2 attempts
   - Problem out of your control (permissions, system configuration, etc.)
   - Solution requires specific knowledge that you don't have

10. ** INCREMENTAL APPROACH - Breaking Complex Problems **
   - **For complex situations**: DO NOT rewrite the entire script/code immediately
   - **Break large problem** into many manageable micro-problems
   - **Solve on the fly**: Tackle one micro-problem at a time
   - **Validate step-by-step**: Only when micro-problem solved → move on to the next one
   - **Scalar approach**: Iterate until all micro-problems are solved
   - **Rewrite code** only when ALL micro-issues are resolved
   - **DO NOT do massive rewrites** without first breaking down and validating each piece

   **Correct workflow for complex problems:**
   ```text
   Problem: Script fails with 5 different errors
   
    WRONG: Rewrite entire script right away
   
    CORRECT: Incremental approach
   1. Identify micro-issue 1 (e.g. bash syntax line 45)
   2. Fix micro-issue 1 on the fly (single change)
   3. Validation test (wsl bash -n)
   4. Confirm resolution → move to micro-problem 2
   5. Identify micro-problem 2 (e.g. incorrect file path)
   6. Fix micro-issue 2 on the fly
   7. Validation test
   8. Repeat until all micro-issues are resolved
   9. NOW ONLY: Consider full refactoring/rewriting if necessary
   ```

   **Incremental approach benefits:**
   - Reduces risk of introducing new bugs
   - Facilitates debugging (each step isolated)
   - Maintains existing functionality during fixes
   - Allows partial rollback if necessary
   - Reduced token cost (targeted fixes vs massive rewrites)

11. ** MANDATORY PROBLEM CHECK **
   - **ALWAYS** check the PROBLEMS panel before considering a task complete
   - Run `get_errors()` after changes to markdown/script files
   - Error correction priority:
     - **MD051** (invalid link fragments) → MANDATORY fix
     - **MD042** (empty links) → Remove links or make them valid
     - **MD022/MD031/MD032** (spacing) → Fix for code quality
     - **MD060** (table style) → Fix if easy, ignore otherwise
     - **MD024** (duplicate headings) → Evaluate on a case-by-case basis
   - If >50 errors: fix batch with `multi_replace_string_in_file`
   - Confirm "0 errors" before declaring task completed
   - **DO NOT** ignore issues without consulting user

12. **MANDATORY TEST - ALL SCRIPTS MODIFIED**
   - **NEVER** say "test completed" without testing ALL modified scripts
   - **ALWAYS** test EVERY script modified in the current session
   - List of modified scripts → test EACH separately
   - **CRITICAL**: If you edit 3 scripts → test all 3, not just 1!
   - Validate bash syntax: `wsl bash -n script.sh`
   - Test execution: run on remote host (nsec8-stable, laboratory, etc.)
   - Check output/log to confirm operation
   - Don't assume that "if one works, they all work"

**CORRECT test workflow example:**

```bash
# Changed: install-script.sh, rocksolid-startup.sh, other-script.sh

# REQUIRED: Test ALL 3 separately
wsl bash -n install-script.sh # Validation 1
wsl bash -n rocksolid-startup.sh # Validation 2
wsl bash -n other-script.sh # Validation 3

# Test running ALL 3 on remote host
wsl -d kali-linux ssh nsec8-stable "curl -fsSL .../install-script.sh | bash" # Test 1
wsl -d kali-linux ssh nsec8-stable "curl -fsSL .../rocksolid-startup.sh | bash" # Test 2
wsl -d kali-linux ssh nsec8-stable "curl -fsSL .../other-script.sh | bash" # Test 3

# ONLY NOW can you say "test completed"

```text

**Example of WRONG test workflow:**

```bash
# Changed: install-script.sh, rocksolid-startup.sh

# Rocksolid testing only
wsl -d kali-linux ssh nsec8-stable "rocksolid-startup.sh" # Test 1
# NOT tested install-script.sh!

# ERROR: You say "test completed" without testing install-script.sh
```text

**Correct workflow example:**

```bash
#1. Backups
cp file.txt file.txt.backup_2026-01-27_20-30-00

#2. Ask for confirmation
"I created backups in file.txt.backup_2026-01-27_20-30-00. Do I proceed with deletion?"

#3. Only after OK user
rm file.txt

```text

13. ** MARKDOWN QUALITY - Markdownlint Error Prevention**
   - **MANDATORY WORKFLOW for EVERY .md file created/modified:**
     1. **BEFORE**: Follow markdownlint best practices (see below)
     2. **IMMEDIATELY AFTER modification**: Run `markdownlint file.md` (exit code 0=OK)
     3. **IF ERRORS**: Fix immediately and re-run `markdownlint`
     4. **REPEAT**: Until you get exit code 0
     5. **OPTIONAL**: `get_errors()` to check VSCode (file path errors)
     6. **ONLY THEN**: Consider task complete
   - **Mandatory rules to be respected:**
     - **Heading spacing**: Empty line ALWAYS after heading `###`

     - **List spacing**: Empty line after last list item before paragraph/heading
     - **Code block spacing**: Empty line before AND after ` ``` ` blocks
     - **Code language**: ALWAYS specify language in code blocks (bash, powershell, python, json, text)
     - **No empty links**: Never use empty links with anchor #, use valid URL or remove links
     - **Link fragments**: If you use TOC with emoji in headings, use bold text instead of links
   - **Correct examples:**
     - Heading with empty line below
     - List with empty line after last entry
     - Code block with specified language (bash/powershell/json)
     - Code block with empty lines before and after
   - **WRONG Examples:**
     - Heading without empty line below
     - List without empty line before paragraph/heading
     - Code block without specified language
     - Code block without empty lines around it
   - After creating/modifying .md file → `get_errors()` for immediate validation
   - Prefer TOC without links if headings have emojis (use **bold text** instead)

14. **Recover corrupt or lost scripts**
   - **Method 1**: Git history - `git log`, `git show`, `git checkout`
   - **Method 2**: Local Backups - `C:\CheckMK-Backups\<timestamp>\`
   - **Method 3**: Network Backup - `\\192.168.10.132\usbshare\CheckMK-Backups\<timestamp>\`
   - **always** check backup availability before massive changes
   - Automatic backups performed daily: job00 (local+network), ultra-minimal (local)

**File recovery example:**

```powershell
# From Git (previous commit)
git show HEAD~1:script-tools/full/script.sh > script.sh.recovered

# From local backup
Copy-Item "C:\CheckMK-Backups\2026-01-29_03-00-00\script-tools\full\script.sh" -Destination ".\"

# From network backup
Copy-Item "\\192.168.10.132\usbshare\CheckMK-Backups\2026-01-29_00-00-00\script-tools\full\script.sh" -Destination ".\"

```text

15. **Test-Fix-Validate Automatic Loop**
   - When we edit a script AND we have access to test hosts
   - **ALWAYS** follow this automatic cycle after each change:
     1. **Edit** script
     2. **Valid** syntax (`bash -n` or PSParser)
     3. **Test** on remote host (real run)
     4. **If it fails** → Fix error
     5. **Re-validate** syntax
     6. **Re-test** on host
     7. **Repeat** until it works or until user stops
   - **DO NOT stop** after syntax validation if test fails
   - **DO NOT wait** user command to fix - do it automatically
   - **Continue** iterating until complete success

**Example test-driven workflow:**

```powershell
#1. Edit scripts
# ... edit file ...

#2. Valid syntax
wsl bash -n script.sh # EXIT CODE: 0 

#3. Test on host
wsl -d kali-linux ssh nsec8-stable "bash /opt/checkmk-tools/script.sh"
# Output: ERROR line 45: command not found

#4. Auto Fix (DO NOT Stop!)
# ... fix error line 45 ...

#5. Re-validate
wsl bash -n script.sh # EXIT CODE: 0 

#6. Re-test
wsl -d kali-linux ssh nsec8-stable "bash /opt/checkmk-tools/script.sh"
# Output: SUCCESS 

#7. Only now does he commit
git commit -m "fix: fixed command error"

```text

**Hosts available for testing:**
- `nsec8-stable` (10.155.100.100) - NethSecurity 8 test environment
- `checkmk-vps-02` (monitor01.nethlab.it) - CheckMK staging/test
- `checkmk-z1plus` (192.168.10.128) - CheckMK local test

16. ** MANDATORY WORKFLOW - Development and Test Script**
   - **ALWAYS follow this complete workflow** for bash/shell script changes
   - **NEVER** skip steps or declare "completed" without real testing
- **LOOP until everything works** - don't exit until completely successful

**MANDATORY WORKFLOW (to ALWAYS be followed):**

```text

┌──────────────────────────── ─────────────────────────────┐
│ 1. EDITING/WRITING SCRIPT │
│ - Implement requested functionality │
│ - Follow bash/PowerShell best practices │
└──────────────────────────── ─────────────────────────────┘
                         ↓
┌──────────────────────────── ─────────────────────────────┐
│ 2. SYNTAX TEST │
│ Bash: wsl bash -n script.sh │
│ PowerShell: PSParser validation │
│ Exit code MUST be 0 │
└──────────────────────────── ─────────────────────────────┘
                         ↓
┌──────────────────────────── ─────────────────────────────┐
│ 3. EXECUTABILITY CHECK │
│ git ls-files -s script.sh │
│ MUST show 100755 (executable) │
│ If 100644 → git update-index --chmod=+x script.sh │
└──────────────────────────── ─────────────────────────────┘
                         ↓
┌──────────────────────────── ─────────────────────────────┐
│ 4. ALIGN REPO AND COMMIT (on the fork) │
│ git add script.sh │
│ git commit -m "type(scope): vX.Y.Z - description" │
│ git push origin main ← ONLY on the fork!              │
└──────────────────────────── ─────────────────────────────┘
                         ↓
┌──────────────────────────── ─────────────────────────────┐
│ 5. ASK HOST FOR TEST │
│ "Which host do you want to test on?"                        │
│ Available hosts: nsec8-stable, laboratory, etc.    │
└──────────────────────────── ─────────────────────────────┘
                         ↓
┌──────────────────────────── ─────────────────────────────┐
│ 6. CHECK AND UPDATE LOCAL REPO │
│ - Check existence /opt/checkmk-tools/ │
│ - If it does NOT exist → git clone │
│ - If exists → cd /opt/checkmk-tools && git pull │
│ MANDATORY before each test │
└──────────────────────────── ─────────────────────────────┘
                         ↓
┌──────────────────────────── ─────────────────────────────┐
│ 7. COMPLETE OPERATION TEST │
│ - Run script from LOCAL REPO │
│ - Path: /opt/checkmk-tools/script-check-*/full/xxx │
│ - Check output/log │
│ - Check exit code │
│ - Valid expected result │
└──────────────────────────── ─────────────────────────────┘
                         ↓
              ┌──────────────────┐
              │ DOES EVERYTHING WORK?  │
              └──────────────────┘
                    / \
                   / \
              NO ↙ ↘ YES
                / \
    ┌──────────────┐ ┌──────────────────────┐
    │ RETURN TO 1. │ │ EXIT LOOP │
    │ FIX + RITEST │ │ Task completed!     │
    └──────────────┘ └──────────────────────┘

```text

**CRITICAL RULES:**
- **NEVER** say "test completed" without REAL testing on remote host
- **NEVER** exit the loop if there are errors
- **NEVER** skip workflow steps without explicit user authorization
- **NEVER** assume it works without testing
- **ALWAYS** fix errors and re-test automatically
- **ALWAYS** test ALL scripts modified in the session
- **ALWAYS** follow ALL steps 1-7 of the workflow
- **Infinite LOOP** until it works or user stops
- **NO RUSH** - Take all the time you need to do well
- **STEP 7 ON HOST PASSWORD**: if the target host requires password (e.g. ns-lab00, laboratory)
  → DO NOT carry out the test yourself → give the commands to paste to the user

**Full example:**

```bash
#1. Edit
vi install-script.sh

#2. Syntax Test
wsl bash -n install-script.sh # Exit: 0 

#3. Check executable
git ls-files -s install-script.sh #100755 

#4. Commit
git add install-script.sh
git commit -m "fix: dynamic download fix"
git push

#5. Ask for hosts
"On which host do I text? [nsec8-stable]"

#6. Check and update local repo
wsl -d kali-linux ssh nsec8-stable "[ -d /opt/checkmk-tools ] && echo 'EXISTS' || echo 'MISSING'"
# If MISSING → git clone https://github.com/Coverup20/checkmk-tools.git /opt/checkmk-tools
# If EXISTS → wsl -d kali-linux ssh nsec8-stable "cd /opt/checkmk-tools && git pull"

#7. Test from LOCAL REPO (NOT GitHub!)
wsl -d kali-linux ssh nsec8-stable "/opt/checkmk-tools/script-tools/full/install-script.sh"
# Output: ERROR line 45

# ERROR → RETURN TO 1 (fix + retest)
# Fix error line 45, recommit, retest...

# OK → Test completed, EXIT LOOP
```

17. **Executable scripts - ALWAYS check Git permissions**
   - **Windows (NTFS) does NOT preserve the Unix executable bit**
   - **ALWAYS** when creating/editing bash/shell scripts (.sh):
     1. Create/edit the file
     2. Check permissions: `git ls-files -s script.sh`
     3. If it shows `100644` (NOT executable) → FIX:
        ```bash
        git update-index --chmod=+x script.sh
        ```

     4. Check: `git ls-files -s script.sh` → should show `100755`
     5. I commit and push normally
   - **Batch control** on directories:
     ```bash
     # Find NON-executable scripts
     git ls-files -s script-tools/full/*.sh | Select String "100644"

     # Make all executable
     git update-index --chmod=+x script-tools/full/*.sh
     ```

   - **DO NOT rely** on `wsl -- test -x` on Windows → use `git ls-files -s`
   - When you propose new bash scripts → make them immediately executable with git update-index

**Example script creation workflow:**

```powershell
#1. Create scripts
New-Item script-tools/full/nuovo-script.sh

#2. Write content
# ... edit file ...

#3. REQUIRED: Make executable
git add script-tools/full/new-script.sh
git update-index --chmod=+x script-tools/full/new-script.sh

#4. Verify (must show 100755)
git ls-files -s script-tools/full/new-script.sh

#5. Commit
git commit -m "feat: new script"

```

18. ** MANDATORY VERSIONING SCRIPT **
   - **ALWAYS add VERSION variable** at the beginning of every bash/PowerShell/Python script
   - Make **version visible in the output/header** of the script
   - **Update version with EVERY change** committed
   - Allows immediate identification of version running on remote hosts
   
   **Version scheme:**
   - `MAJOR.MINOR.PATCH` (e.g. `2.0.5`)
   - MAJOR: architecture change/breaking changes
   - MINOR: new backwards-compatible features
   - PATCH: minor bugfixes/improvements
   
   **Python Template (PREFERRED - Python-first policy):**
   ```python
   #!/usr/bin/env python3
   VERSION = "1.0.0" # Script version (update with each change)
   
   # Show version in output/help
   print(f"Script Name - Version v{VERSION}")
   ```
   
   **Bash Templates:**
   ```bash
   #!/bin/bash
   VERSION="1.0.0" # Script version (update with each change)
   
   # Show version in output/help
   echo "Script Name - Version v${VERSION}"
   ```
   
   **PowerShell Templates:**
   ```powershell
   # Script Name
   $VERSION = "1.0.0" # Script version (update with each change)
   
   Write-Host "Script Name - Version v$VERSION"
   ```
   
   **Example commit message with version bump:**
   ```bash
   git commit -m "fix(script): v1.0.1 - fixes ACL parsing bug"
   ```
   
   **Script editing workflow:**
   1. Edit code
   2. **MANDATORY**: Bump VERSION variable
   3. Validation test
   4. Commit with versioned message
   5. Push

---
## NethSecurity 8 - Local Checks CheckMK

### DEPLOYMENT RULE - Keep .sh extension

**Local checks must maintain the `.sh` extension even when deployed:**

```bash
# CORRECT - Keep extension
cp /opt/checkmk-tools/script-check-nsec8/full/check_vpn_tunnels.sh \
   /usr/lib/check_mk_agent/local/check_vpn_tunnels.sh
# ^^^ WITH .sh

# WRONG - Do not remove extension
cp script.sh /usr/lib/check_mk_agent/local/script # NO!

```text

**User preference reason:**
- Consistency with repositories (all .sh scripts)
- Easier to identify file type
- CheckMK still runs files with extension

**Auto-restore must use full name with extension:**

```bash
# In rocksolid-startup-check.sh
basename_script=$(basename "$script") # DO NOT remove .sh
cp "$script" "/usr/lib/check_mk_agent/local/$basename_script"

```text

---
## � NethServer - Configuration Management

### CRITICAL RULE - DO NOT edit configuration files manually
**NethServer (NS7/NS8) uses e-smith/template system:**
- **NEVER directly edit** files in `/etc/` (fail2ban, httpd, postfix, etc.)
- **ALWAYS use web interface** or `config` commands
- Manual file changes = **lost at next `signal-event`**

**Example configurations managed by template:**

```bash
/etc/fail2ban/fail2ban.conf # Managed by templates
/etc/fail2ban/jail.conf # Managed by templates
/etc/httpd/conf.d/* # Managed by templates
/etc/postfix/main.cf # Managed by templates
/etc/shorewall/* # Managed by templates

```text

**Correct methods to change configurations:**

1. **Via NethServer web interface**
   - Server Manager → specific section
   - Persistent and validated changes

2. **Via config commands (CLI)**

```bash
# View configuration
config show fail2ban

# Edit properties
config setprop fail2ban LogLevel NOTICE
config setprop fail2ban DbPurgeAge 30d

# Apply changes
signal-event nethserver-fail2ban-save

```text

3. **Via custom template** (advanced)

```bash
# Create custom templates in /etc/e-smith/templates-custom/
# Changes survive signal-events

```text

** Consequences of manual changes:**
- `signal-event nethserver-<service>-save` → configuration restored
- Service restart → configuration restored
- System updates → configuration restored

**ALWAYS ask user confirmation** before suggesting manual changes to files on NethServer!

---

## NethSecurity 8 - NGINX Web UI Major Upgrade Issue

### CRITICAL ISSUE - Symlink /etc/nginx/uci.conf deleted during upgrade

**Symptom:**
- Post major upgrade: nginx doesn't start, Web UI (port 9090) not available
- Log error: `open() "/etc/nginx/nginx.conf" failed (2: No such file or directory)`
- Directory `/etc/nginx/` exists and is protected, but symlink is missing

**ROOT cause:**
- NethSecurity uses `/var/lib/nginx/uci.conf` as the main nginx configuration
- `/etc/nginx/uci.conf` is a **symlink** → `/var/lib/nginx/uci.conf`
- During major upgrade: symlink deleted even if `/etc/nginx/` is protected in sysupgrade.conf
- Nginx searches for `uci.conf` but doesn't find it → fails to start

**Solution implemented (commit 6107753 + 1986623):**

1. **Directory Protection** (`install-checkmk-agent-persistent-nsec8.sh`):

```bash
# In protect_checkmk_installation()
add_to_sysupgrade "/etc/nginx/" "NGINX configuration (Web UI NethSecurity)"

```text

2. **Symlink Automatic Repair** (`rocksolid-startup-check.sh`):

```bash
# Before checking nginx
if [ ! -L /etc/nginx/uci.conf ] && [ -f /var/lib/nginx/uci.conf ]; then
    log "[Nginx] Restoring symlink uci.conf..."
    ln -sf /var/lib/nginx/uci.conf /etc/nginx/uci.conf 2>/dev/null || true
fi

```text

**Emergency manual fix:**

```bash
# On already upgraded system with broken nginx
ln -sf /var/lib/nginx/uci.conf /etc/nginx/uci.conf
/etc/init.d/nginx restart
# Web UI is available again on port 9090

```text

**Check solution:**

```bash
# After upgrade/reboot
ls -la /etc/nginx/uci.conf # Must be symlink
/etc/init.d/nginx status # Must be "running"
netstat -tlnp | grep :9090 # Must show nginx listening

```text

**Technical notes:**
- `/var/lib/nginx/uci.conf` dynamically generated by nginx-ssl-util
- Contains server blocks configurations for ports 80/443/9090
- Symlink needed because nginx includes `/etc/nginx/uci.conf` in main config
- Lab backup available: `C:\Users\Marzio\Desktop\CheckMK\nginx-backup-laboratorio.tar.gz`

---

## � Quality Control Tools

### check-integrity.ps1 - Repository Integrity Check

**When to use this tool:**
- When user asks to "check integrity" or "check corruption"
- After massive changes to bash or PowerShell scripts
- Before major merges
- When you suspect file corruption in the repository

**Commands available:**

```powershell
# Standard check with summary
.\script-ps-tools\check-integrity.ps1

# Detailed check with complete error list
.\script-ps-tools\check-integrity.ps1 -Detailed

# Export complete report to file
.\script-ps-tools\check-integrity.ps1 -ExportReport

# Change corruption threshold (default: 15%)
.\script-ps-tools\check-integrity.ps1 -Threshold 20

```text

**Features:**
- Check **PowerShell** syntax via `[System.Management.Automation.Language.Parser]::ParseFile()`
- Check **Bash/Shell** syntax via WSL `bash -n`
- Detects **massive corruption** (default threshold: 15%)
- Detailed report by file type (PS1, Bash, Batch, Python)
- Exit codes: 0=OK, 1=Warning (<15%), 2=Critical (>15%)

**Integration with Backup System:**
- `backup-simple.ps1` uses the same validation logic
- Backup is **blocked** if corruption exceeds 15%
- Backup emails include detailed reports of errors detected

**Verified Repository Structure:**

```text

checkmk-tools/
├── script-check-ns7/full/ # NethServer 7 script
├── script-check-ns8/full/ # NethServer 8 script
├── script-check-proxmox/full/ # Proxmox script
├── script-check-ubuntu/full/ # Ubuntu Script
├── script-tools/full/ # Various tools
├── script-notify-checkmk/full/ # CheckMK Notifications
└── Ydea-Toolkit/full/ # Ydea integration

```text

**Example Output:**

```text

=======================================================================================
    INTEGRITY CHECK RESULTS
=======================================================================================

GENERAL SUMMARY:
  Verified scripts: 451
  Valid scripts: 387
  Script with errors: 64
  Error rate: 14.19%
  Corruption threshold: 15%

DETAIL BY TYPE:
  Bash/Shell
    Total: 416
    Valid: 352
    Errors: 64 (15.4%)

[STATUS] WARNING - Errors detected but below threshold

```text

---

## Recommended Workflow

### MANDATORY RULE - Script Validation

#### Bash/Shell Script

**ALWAYS when creating or editing a Bash/Shell script:**
1. Test with `wsl bash -n <file_path>`
2. Verify that `$LASTEXITCODE -eq 0`
3. If exit code ≠ 0, correct the errors and test again
4. Repeat until you get exit code 0
5. Only then consider the file completed

**PowerShell command to use:**

```powershell
wsl bash -n "path/to/script.sh"; echo "EXIT CODE: $LASTEXITCODE"

```text

**Never proceed without exit code 0!**

#### PowerShell Script (.ps1)

**ALWAYS when creating or editing a PowerShell script:**
1. Valid with PSParser
2. Verify that error count = 0
3. If errors exist, correct and retest
4. Repeat until you get 0 errors
5. Only then consider the file completed

**Validation command to use:**

```powershell
$errors = $null; $null = [System.Management.Automation.PSParser]::Tokenize((Get-Content "path/to/script.ps1" -Raw), [ref]$errors); if ($errors.Count -eq 0) { Write-Host "Syntax OK" -ForegroundColor Green } else { Write-Host "ERRORS:" -ForegroundColor Red; $errors }; Write-Host "EXIT CODE: $LASTEXITCODE"

```text

**Common PowerShell Errors:**
- `%` character not escaped in strings → Use `$($variable)%`
- Regex anchor `\z` → Prefer `$` (more compatible)
- Superscripts/quotes not closed correctly

**Never proceed if PSParser reports errors!**

### � MANDATORY RULE - Cleaning Temporary Scripts on Remote Hosts

**Scripts created on remote hosts (via WSL/SSH) to perform punctual actions → MUST be deleted when the job is finished.**

- **DO NOT leave temporary scripts** in `/tmp/`, `/root/`, `/home/`, or any other remote host directory
- **ALWAYS delete** the script as soon as the task is completed (or failed)
- **Automatic deletion**: Include `rm -f /tmp/script.py` in the same SSH command where you run the script
- This applies to: Python scripts, bash, `.py` files, `.sh` and any other ad-hoc created files

**Corrected pattern (execute and delete in one go):**

```bash
# CORRECT - run and delete
ssh host 'python3 /tmp/fix.py; rm -f /tmp/fix.py'

# CORRECT - via base64 (leaves no files)
ssh host 'echo <base64> | base64 -d | python3'

# WRONG - script left on host
ssh host 'python3 /tmp/fix.py'
# ... job completed ...
# (no cleaning)
```

**The base64 method is preferred** because it never creates temporary files on the host.
If you absolutely have to create a file → delete it immediately afterwards with `rm -f`.

### � DEPLOYMENT RULE - Path Script Repository

** IMPORTANT: Repository already cloned on all machines **

**Local repository path:**
- **ALL machines (servers and hosts) have git clone in `/opt/checkmk-tools/`**
- Automatically updated repository (automatic git pull)
- Prefer local execution when available (more convenient/faster)
- **WARNING: Local clone is READ-ONLY** - any changes are overwritten by automatic git pull
- **NEVER edit files in `/opt/checkmk-tools/`** - changes are systematically lost

**Order of priority:**
1. **Local (if available)**: `/opt/checkmk-tools/script-tools/full/script-name.sh` (most convenient)
2. **GitHub raw**: `https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/...` (works equally well)

**Local execution examples:**

```bash
# Direct execution from local repo
/opt/checkmk-tools/script-tools/full/installation/install-agent-interactive.sh

# Cron job - use local repo
0 3 * * * /opt/checkmk-tools/script-tools/full/backup_restore/cleanup-checkmk-retention.sh >> /var/log/script.log 2>&1

# With explicit bash
bash /opt/checkmk-tools/script-tools/full/script-name.sh

```text

**Examples running from GitHub (fallback or remote hosts):**

```bash
# Cron job - direct execution from GitHub
0 3 * * * curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash >> /var/log/script.log 2>&1

# Remote manual execution
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/script-name.sh | bash

```text

**Local path benefits:**
- Faster (no download)
- Works offline
- Same code on all servers (git pull auto)

**GitHub raw (curl/wget) benefits:**
- Works equally well
- Always latest GitHub version
- Useful for remote or bootstrap hosts

** MANDATORY WORKFLOW TEST - Local Repository**

**FUNDAMENTAL RULE (to ALWAYS be followed during tests):**

1. **BEFORE any remote host testing**:
   - Check for `/opt/checkmk-tools/`
   - If it does NOT exist → clone it manually
   - If it exists → update it with `git pull`
   - ALWAYS use local path for testing (NO GitHub raw)

2. **Correct test workflow:**

```bash
# STEP 1: Verify + create/update local repo
wsl -d kali-linux ssh <host> "[ -d /opt/checkmk-tools ] && echo 'REPO EXISTS' || echo 'REPO MISSING'"

# If REPO MISSING → clone
wsl -d kali-linux ssh <host> "git clone https://github.com/Coverup20/checkmk-tools.git /opt/checkmk-tools"

# If REPO EXISTS → update
wsl -d kali-linux ssh <host> "cd /opt/checkmk-tools && git pull"

# STEP 2: Run tests from LOCAL repo (NOT from GitHub!)
wsl -d kali-linux ssh <host> "/opt/checkmk-tools/script-check-ns7/full/check-sos-ns7.py"

# ADVANTAGES:
# - No GitHub cache issues
# - Post-commit guaranteed version
# - Faster (no download)
```

3. **Test with remote launcher:**

```bash
# Update repo
wsl -d kali-linux ssh <host> "cd /opt/checkmk-tools && git pull"

# Test launcher from local repo
wsl -d kali-linux ssh <host> "/opt/checkmk-tools/script-check-ns7/remote/rcheck-sos-ns7.py"

# Launcher downloads full/ from GitHub (normal behavior)
# But launcher itself comes from updated local repo
```

** WHEN to use GitHub raw: **
- **NEVER** for testing during development (cache 5 min!)
- Only for initial bootstrap (host without repo)
- For documentation examples only

**IMPORTANT RULE: Repository Changes**
- Changes ONLY on local VSCode (Windows)
- Commit and push from VSCode
- Manual/automatic Git pull deploys to all servers
- **NEVER edit files in `/opt/checkmk-tools/` on remote servers**
- Local changes are lost on next git pull

### Before every major commit:

1. Run `.\script-ps-tools\check-integrity.ps1` to check the status
2. If errors >15%, investigate before committing
3. Verify that all .sh scripts are executable

### After massive changes:

1. Run `.\script-ps-tools\check-integrity.ps1 -Detailed` to see all errors
2. Consider whether you need to repair corrupt scripts
3. Use `.\script-ps-tools\repair-corrupted-scripts.ps1` if available

### Periodic monitoring:

- **Weekly**: `.\script-ps-tools\check-integrity.ps1 -ExportReport` for history
- **Monthly**: Analyze corruption trends over time

---

## Repository Backup Tools

### backup-simple.ps1 - Full Backup with Integrity Check

**When to use:**
- Automatic scheduled backups (scheduled task)
- Complete periodic backups with validation
- When `check-integrity.ps1` has not been run recently

**Features:**
- Full integrity check of all scripts (PS1, Bash, Python)
- Syntax validation with PSParser and `bash -n`
- Automatic blocking if corruption >15% (error propagation protection)
- Detailed error report via email
- Local + network backup
- Automatic retention policy (20 backups)

**Commands:**

```powershell
# Interactive mode
.\script-ps-tools\backup-simple.ps1

# Automatic mode (scheduled task)
.\script-ps-tools\backup-simple.ps1 -Unattended
```

**Execution time:** ~2-5 minutes (depends on script number)

---

### backup-quick.ps1 - Fast Backup without Integrity Check

**When to use:**
- During Python conversion workflow (after each completed category)
- Fast post-commit backups when integrity is already verified
- Situations where speed is a priority

**Features:**
- Immediate backup without syntax validation
- Local + network backup
- Automatic retention policy (20 backups)
- Report via email (without health section)
- Assumes `check-integrity.ps1` has been run separately

**Commands:**

```powershell
# Interactive mode
.\script-ps-tools\backup-quick.ps1

# Automatic mode (Python workflow)
.\script-ps-tools\backup-quick.ps1 -Unattended
```

**Execution time:** ~30-60 seconds

---

### Backup Script Comparison

| Feature | backup-simple.ps1 | backup-quick.ps1 |
|----------------|-----------------------|------------------|
| Integrity check |  Yes |  No |
| Syntax validation |  PSParser + bash -n |  No |
| Corruption block >15% |  Yes |  No |
| Local backup |  Yes |  Yes |
| Network Backup |  Yes |  Yes |
| Retention policy |  Yes |  Yes |
| Email reports |  With integrity |  Without integrity |
| Execution time | 2-5 min | 30-60 sec |
| Recommended use | Periodic tasks | Conversion Workflow |

---

### Recommended Workflow

**Python conversion (full category):**
```powershell
#1. Convert all category scripts
#2. Test and deploy everyone
#3. Fast backup
.\script-ps-tools\backup-quick.ps1 -Unattended
```

**Full periodic backup:**
```powershell
# Scheduled task (e.g. every night)
.\script-ps-tools\backup-simple.ps1 -Unattended
```

**On-demand integrity check:**
```powershell
# Manual control without backup
.\script-ps-tools\check-integrity.ps1 -Detailed
```

---

## Related Tools

- **check-integrity.ps1**: Integrity check without backup
- **repair-corrupted-scripts.ps1**: Automatically repair corrupted scripts
- **WSL**: Required for Bash validation (`bash -n`)

---

## Agent CheckMK - Installation/Update

** IMPORTANT: Always use the dedicated CheckMK agent script**

### Script to use:

```bash
# On remote CheckMK servers
/opt/checkmk-tools/script-tools/full/installation/install-agent-interactive.sh

# From GitHub (if repo not cloned)
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/installation/install-agent-interactive.sh | bash

```text

### What the script does:

- Detect OS automatically (Debian/Ubuntu/RHEL/OpenWrt)
- Download correct agent from CheckMK version server
- **Automatically disable `cmk-agent-ctl-daemon.service`** (due to port 6556 conflicts)
- Configure plain TCP socket on port 6556
- Properly handles systemd/xinetd/procd
- Optional: Configure FRPC for tunnels

### Common problem:

**DO NOT just use `dpkg -i check-mk-agent.deb`** because:
- Leave `cmk-agent-ctl-daemon` active which conflicts
- Does not configure the TCP socket correctly
- Causes "Address in use (os error 98)" error

### Fix if already installed manually:

```bash
# Disable problematic daemon
systemctl disable --now cmk-agent-ctl-daemon.service
systemctl reset-failed cmk-agent-ctl-daemon.service

# The agent continues to run via check-mk-agent.socket

```text

---

## Bash Script Conversion → Python - Best Practices

** PYTHON-FIRST POLICY (from February 13, 2026):**

- **ALL new scripts MUST be written in Python**
- Python is the official language for new check/tool/automation
- Bash only for minimal wrappers or justified exceptional cases
- Existing bash scripts should be gradually converted to Python
- Remote launchers: ALWAYS pure Python (urllib + exec), NO bash+curl

**Reasons:**

- Superior parsing robustness and error handling
- Type hints for security and maintainability
- Easier and more complete testing
- Portability and codebase consistency
- Single language means single expertise to maintain

** COMPLETE WORKFLOW for converting existing scripts:**

### 1. Conversion Strategy

**When to convert bash → Python:**
- Script with complex parsing (command output, regex, structured text)
- Script with complex conditional logic
- Need for robust error handling
- Scripts that benefit from type hints and modularity
- Scripts intended to evolve (more features over time)

**Python Advantages:**
- More robust parsing (regex, split, strip vs sed/awk/grep)
- Elegant error handling (try/except vs if/then)
- Type hints for security and documentation
- Modularity with documented functions (docstring)
- Easier testing (unit tests, mocks)
- Rich standard library (subprocess, urllib, json, etc.)

### 2. CheckMK Local Check Python Script Template

```python
#!/usr/bin/env python3
"""
check_service_name.py - CheckMK Local Check for <description>

<Detailed feature description>

Version: 1.0.0
"""

import subprocess
import sys
import re
from typing import Tuple, List, Optional

VERSION = "1.0.0"
SERVICE = "ServiceName"


def run_command(cmd: List[str]) -> Tuple[int, str, str]:
    """
    Execute a shell command and return exit code, stdout, stderr.
    
    Args:
        cmd: Command as list of strings
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def main() -> int:
    """
    Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)
    """
    # Check logic here
    # Output format: <STATE> <SERVICE> - <message>
    # STATE: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN
    
    print(f"0 {SERVICE} - OK message")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 3. Pattern CheckMK Output

**Required local check format:**

```text
<STATE> <SERVICE_NAME> - <message>
```

**State codes:**

- `0` = OK (green)
- `1` = WARNING (yellow)
- `2` = CRITICAL (red)
- `3` = UNKNOWN (orange)

**Exit code script:**

- ALWAYS `0` for local checks (CheckMK ignores exit code, reads only first output field)

### 4. Deploy Directly from Local Repo (NO Launcher)

 **DEPRECATED LAUNCHERS** - No longer create `remote/rssh_*.py` scripts

 **CURRENT POLICY: Direct deployment of `full/` script from `/opt/checkmk-tools/`**

**Reason:**
- The `/opt/checkmk-tools/` repo is already present on all hosts (automatic git pull every minute)
- Direct deployment = no HTTP downloads at runtime, works offline
- Fewer files to maintain, less complexity
- No double steps (launcher → download → exec)

**Deployment method:**

```bash
# Update local repo
cd /opt/checkmk-tools && git pull

# Copy full/ script to local checks directory (WITHOUT extension)
cp script-check-<category>/full/check_service_name.py /usr/lib/check_mk_agent/local/check_service_name
chmod +x /usr/lib/check_mk_agent/local/check_service_name

# Immediate test
/usr/lib/check_mk_agent/local/check_service_name
```

**Deployed file name:**
- WITHOUT `.py` extension (CheckMK runs all executable files)
- Use the check name directly: `check_nethvoice_trunks`, `check_fail2ban_status`, etc.
- No more `rssh_` prefix

### 5. Complete Workflow Conversion/New Script

**MANDATORY Steps (ALWAYS follow):**

```bash
#1. Create full Python script (full/)
vim script-check-ubuntu/full/check_service_name.py
# Implement functionality with template above

#2. Valid Python syntax
python -m py_compile script-check-ubuntu/full/check_service_name.py
# EXIT CODE must be 0

#3. Make executable and add to git
git add script-check-ubuntu/full/check_service_name.py
git update-index --chmod=+x script-check-ubuntu/full/check_service_name.py

#4. Check permissions (must show 100755)
git ls-files -s script-check-ubuntu/full/check_service_name.py

#5. Commit & Push
git commit -m "feat(ubuntu): check_service_name v1.0.0 - description"
git push

#6. Deploy to remote host (update repo + copy directly)
# HOST WITH SSH KEY (vps-01, vps-02):
wsl -d kali-linux ssh <host> "cd /opt/checkmk-tools && git pull && cp script-check-ubuntu/full/check_service_name.py /usr/lib/check_mk_agent/local/check_service_name && chmod +x /usr/lib/check_mk_agent/local/check_service_name"

# HOST WITH PASSWORD (all others): give the commands to paste:
# cd /opt/checkmk-tools && git pull
# cp script-check-ubuntu/full/check_service_name.py /usr/lib/check_mk_agent/local/check_service_name
# chmod +x /usr/lib/check_mk_agent/local/check_service_name

# 7. Test local check
wsl -d kali-linux ssh <host> "/usr/lib/check_mk_agent/local/check_service_name"

#8. Check CheckMK agent output
wsl -d kali-linux ssh <host> "check_mk_agent 2>/dev/null | grep ServiceName"
# Must show ONLY ONE line with output check
```

 **DO NOT create `remote/` folder or `rssh_*.py` file** - they are no longer needed.

### 6. Naming Convention

**Files in repository:**

- `script-check-<category>/full/check_service_name.py` → Full Python script (only file to create)
- `script-check-<category>/full/check_service_name.sh` → OLD bash script (deprecated, do not create new)
- `script-check-<category>/remote/` → DO NOT create this folder/file again

**Files deployed on host (local checks):**

- `/usr/lib/check_mk_agent/local/check_service_name` → Script deployed WITHOUT `.py` extension
- Name same as `full/` file without `.py` (e.g. `check_nethvoice_trunks`)
- CheckMK runs all executable files in the directory

### 7. Gradual Migration

**When converting an existing bash script:**

1. Keep original bash version (`.sh`) in repository during transition
2. Create new Python version (`.py`) in `full/`
3. Test Python scripts directly on pilot hosts
4. If all OK → replace the deployed file in `/usr/lib/check_mk_agent/local/` with the Python version
5. OPTIONAL: Remove `.sh` from repository after transition period

**NEVER delete bash scripts without full Python testing!**
 **DO NOT create `remote/rssh_*` launcher** - direct deployment from local repo.

### 8. Mandatory Testing

**Test checklist before declaring conversion complete:**

- Python syntax validation (py_compile)
- Full script execution on remote host
- CheckMK compatible output format (`<STATE> <SERVICE> - <msg>`)
- Check appears in `check_mk_agent` output
- NO duplicates (only 1 instance of the check in the output agent)
- Behavior identical to the bash version (same state codes, same messages)

** BACKUP AT THE END OF THE CATEGORY:**

- **MANDATORY BACKUP**: At the end of the conversion **entire category/folder**
- Example: After completing ALL scripts from `script-check-ubuntu/` → `.\script-ps-tools\backup-quick.ps1 -Unattended`
- DO NOT run backups after every single script
- Perform backups only when complete category is tested and deployed
- `script-ps-tools\backup-quick.ps1` is optimized for conversion workflow (NO integrity check)
- ℹ Integrity check performed separately with `.\script-ps-tools\check-integrity.ps1` when needed

### 9. Complete Real World Example

**Case study: check_fail2ban_status.sh → check_fail2ban_status.py**

**Commit History:**

- `c0e26d5`: Create `check_fail2ban_status.py` (complete script)
- `64bfdee`: Creating `rssh_fail2ban_status_py.sh` (bash launcher - deprecated)
- `f108044`: Refactor `rssh_fail2ban_status.py` (pure Python launcher)

**Final Paths:**

- Repository: `script-check-ubuntu/full/check_fail2ban_status.py` (full script)
- Repository: `script-check-ubuntu/remote/rssh_fail2ban_status.py` (Python launcher)
- Deployed: `/usr/lib/check_mk_agent/local/rssh_fail2ban_status` (launcher without .py)

**Production output:**

```text
0 Fail2ban - running, no banned IPs
```

---

## Python Style - Nethesis Standard

Reference style from `NethServer/nethsecurity` (`packages/ns-api/files/`).
Apply this style to ALL new Python scripts in this project.

### Structure (mandatory)

```python
#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# <One-line module description>

import os
import sys
import json
import subprocess

## Useful

def utility_function():
    ...

## Check (or ## APIs for rpcd scripts)

def check():
    ...

check()
```

### Rules

**Entrypoint:**
- No `if __name__ == "__main__"` — code runs at module level
- For CheckMK local checks: call the main function directly at bottom
- For rpcd scripts: `sys.argv[1]` / `sys.argv[2]` dispatch, zero argparse

**Functions:**
- Flat functions only — no classes ever
- Short variable names for local scope: `u`, `r`, `t`, `p`, `rc`
- `snake_case` everywhere
- Prefix `ns_` on UCI sections created by the script

**Error handling:**
- Bare `except:` is acceptable in utility functions (silently swallow)
- For CheckMK checks: print the CRITICAL/UNKNOWN line and return, do not raise
- No logging module — output via print or return value only

**subprocess:**
- Always `subprocess.run([...], capture_output=True, text=True, timeout=N)`
- Never `shell=True`
- Check `returncode` explicitly

**Return / output format:**
- rpcd scripts: `{"result": "success"}` / `{"id": name}` / `{"items": [...]}`
- rpcd errors: `utils.generic_error("snake_case_message")`
- CheckMK checks: `print(f"<STATE> <SERVICE> - <message>")` then return

**Type hints:** never

**Docstrings:** only on non-obvious utility functions, nowhere else

**Sections:** use `## Utils` and `## Check` (or `## APIs`) as block separators

**Imports:** stdlib first, then third-party/platform libs — no blank lines between groups

### CheckMK local check template (Nethesis style)

```python
#!/usr/bin/python3
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#

# Check <service> status

import sys
import subprocess

SERVICE = "ServiceName"

## Useful

def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 1, "", str(e)

## Check

def check():
    rc, out, err = run(["systemctl", "is-active", "myservice"])
    if rc != 0:
        print(f"2 {SERVICE} - CRITICAL: service not running")
        return
    print(f"0 {SERVICE} - OK: running")

check()
```

---

## SSH Remote Access - VPS and Local Servers

### WSL SSH setup

**Environment configured:**
- WSL: **Kali Linux** on Windows (`wsl -d kali-linux bash -c "command"`)
- SSH Keys: `~/.ssh/checkmk` (passphrase protected)
- SSH Config: `~/.ssh/config` with host alias
- SSH ControlMaster: Reuse connections (passphrase 1 time, then 1 min active)

**ADJUST COMMAND FORMAT - When the user asks for "commands to paste":**

- Pass the command **naked**, without wrapper `wsl -d kali-linux ssh ...`
- The user pastes it directly into the already opened remote terminal
- WRONG: `wsl -d kali-linux ssh -tt -o ControlMaster=no -J sos -p 2333 root@45.33.235.86 "apt-get install -y git"`
- FIXED: `apt-get install -y git`
- Use `wsl -d kali-linux ssh ...` wrapper ONLY when running from VS Code terminal standalone

** RULE OF PRACTICE - SSH password (no “continuous pause”):**

- Use `ssh -tt` when expecting prompts (password/confirm)
- If a `password for ...:`/`[sudo] password for ...:` prompt actually appears → stop only until the password is entered
- Don't force `sudo`/`sudo -v` “by default”: use `sudo` only when needed and when the user is actually doing it (or requests it)

** CRITICAL RULE - Remote SSH Command Timeout:**
- **ISSUE**: Agent SSH runs too fast and thinks user has aborted (^C), but in reality command was still processing
- **SOLUTION**: Use GENEROUS timeouts for remote commands
- **Recommended timeouts**:
  - Simple commands (ls, cat, echo): `timeout: 10000` (10 sec)
  - Normal SSH commands (script execution): `timeout: 30000` (30 sec)
  - Complex SSH commands (check_mk_agent, git operations): `timeout: 60000` (60 sec)
  - Backup/restore/massive operations: `timeout: 120000` (2 min)
- **NEVER use timeout < 10000** for SSH commands
- **WAIT for completion** even if it seems slow - the command is working
- **DO NOT assume** that ^C in the output means user abort - it may be tool timeout too short

** CRITICAL RULE - DO NOT issue a second SSH command before the first one outputs:**
- **NEVER** launch a new SSH command while the previous one is still waiting for password or output
- **NEVER** use `get_terminal_output` immediately after and then run a second command "because the first one didn't respond"
- **ALWAYS** use `terminal_last_command` to read the output of the current command
- **DO NOT** issue an alternative "simpler" command if the first one does not respond immediately - WAIT

**CRITICAL RULE - ALWAYS read the output before speaking:**
- **BEFORE saying anything** after a command → check exit code in context
- **If exit code = 0** → call `terminal_last_command` immediately and read the output
- **Only if exit code = unknown / command still running** → wait or ask
- **NEVER** say "enter password" or "wait for completion" if exit code is already 0
- **NEVER** reissue a command if the previous one already has exit code 0 — the output is already available
- **If password is wrong once** (output "Permission denied, please try again") → SSH command waits for second password → continue monitoring with `terminal_last_command` until it exits, DO NOT abandon

** GENERAL RULE - Host with PASSWORD authentication (checkmk-z1plus, ns-lab00, laboratory, srv-monitoring, etc.):**
- **NEVER** attempt standalone SSH connections via `run_in_terminal` on hosts with passwords
  → the tool cannot enter the password → always fails with `^C` or timeout
- **IF first attempt `run_in_terminal` on host-password fails** (output `^C` or empty):
  → DO NOT try again
  → IMMEDIATELY issue the commands to paste into the user's terminal
- **EXCEPTION**: checkmk-vps-01 and checkmk-vps-02 use SSH key → run_in_terminal works
- **CRITICAL NOTE**: Having the host alias in `~/.ssh/config` does NOT mean passwordless access!
  → The WSL config defines connection parameters, it does NOT automatically authenticate
  → If the host uses passwords, the tool goes to `^C` regardless of the configured alias
- **Host classification by auth method**:
  - **SSH KEY** (run_in_terminal OK): checkmk-vps-01, checkmk-vps-02, ubntmarzio
    → checkmk-vps-01/02: key ~/.ssh/checkmk (passphrase) - ALWAYS use via WSL
    → Command: `wsl -d kali-linux bash -c "ssh checkmk-vps-02 'cmd'"`
    → ControlMaster 30m active in WSL: after the first connection (passphrase), all subsequent ones are autonomous
    → If the socket has expired (>30min), ask the user to reopen: `wsl -d kali-linux ssh checkmk-vps-02`
    → ubntmarzio: key ~/.ssh/copilot_ubntmarzio (ed25519, NO passphrase, installed 2026-03-28) - autonomous always
  - **SSH KEY** (run_in_terminal OK): srv-monitoring
    → Key: ~/.ssh/copilot_srv_monitoring (ed25519, installed 2026-03-10)
    → Command: `wsl -d kali-linux bash -c "ssh srv-monitoring 'cmd'"` (NO -tt!)
    → Completely autonomous access, zero passwords
  - **PASSWORD** (give commands to paste): checkmk-z1plus, checkmk-testfrp, nodo-proxmox, ns-lab00, box-lab00, rl94ns8, rl94ns81, nsec8-stable, laboratory, marziodemo, fwlab, redteam

**Available hosts:**

```bash
# VPS CheckMK (key: ~/.ssh/checkmk + passphrase)
checkmk-vps-01 # monitor.nethlab.it (CheckMK 2.4.0p19.cre) - PRODUCTION
                  # rclone configured inside the OMD site (not root)
                  # Path: /opt/omd/sites/monitoring/.config/rclone/rclone.conf
                  # Commands: omd on monitoring -c "rclone ..."
checkmk-vps-02 # monitor01.nethlab.it - CRITICAL TESTS / STAGING

# CheckMK local servers (password authentication)
checkmk-z1plus #192.168.10.128 (local)
checkmk-testfrp #192.168.10.126 (user: admin_nethesis)

# Other local servers (password authentication)
proxmox-node #10.155.100.20:22 (root, Proxmox VE)
ns-lab00 #192.168.10.100:2222 (root, NethServer 7)
box-lab00 # 192.168.10.132:22 (root) - Host share \\192.168.10.132\usbshare
rl94ns8 #10.155.100.40:22 (root, NethServer 8)
                  # Modules: samba1, mail2, webtop1, webtop3
                  # Full node for NS8 fortnightly report testing (AD + Mail + WebTop)
rl94ns81 #10.155.100.41:22 (root, NethServer 8)
                  # Modules: webtop1 (with Postgres active)
                  # WebTop node for testing email shares
nsec8-stable #10.155.100.100:22 (root, NethSecurity 8)
                  # CheckMK agent installed with: install-checkmk-agent-persistent-nsec8.sh
                  # Path: /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh
lab #10.155.100.1:2222 (root, NethSecurity 8)
                  # ROCKSOLID Mode validated - resistant to major upgrades
marziodemo # 10.155.100.61:22 (root, Demo environment)
ubntmarzio # 10.155.100.108:22 (user: marzio) - SSH KEY (self-access OK, NO sudo without password)
                  # Key: ~/.ssh/copilot_ubntmarzio (ed25519, installed 2026-03-28)
                  # Command: ssh ubntmarzio 'cmd' (alias in ~/.ssh/config)
srv-monitoring #45.33.235.86:2333 (root, Monitoring)
                  # ALWAYS USE root@45.33.235.86 - NEVER admin-nethesis or other users!
                  # DO NOT use sudo (already logged in as root - sudo is not needed)
# OMD installed: site 'monitoring' in /omd/sites/monitoring/
                  # rclone configured: /opt/omd/sites/monitoring/.config/rclone/rclone.conf (remote 'do', bucket 'testmonbck')
                  # Local backups in: /var/backups/checkmk/
                  # Cloud push: checkmk-cloud-backup-push@monitoring.timer (every minute)
                  # OMD commands as root: su - monitoring -c "command"
                  # Public firewall 45.33.235.86 port 2333 → DNAT → 127.0.0.1:2222 internal
                  # fail2ban active on firewall - DO NOT make multiple connection attempts
                  # Firewall whitelist only IP 159.65.203.113 (alias sos) - MANDATORY jump via sos
                  # PASSWORD authentication (not SSH key) - DO NOT install SSH keys
                  # Direct access command (from WSL):
                  # wsl -d kali-linux ssh srv-monitoring (use alias ~/.ssh/config in WSL)
                  # Config WSL ~/.ssh/config entry REQUIRED:
                  # Host srv-monitoring
                  # HostName 45.33.235.86
                  # Port 2333
                  # User root
                  # ProxyJump sus
                  # ControlMaster auto
                  # ControlPath ~/.ssh/sockets/%r@%h:%p
                  # ControlPersist 60m
                  # Correct command: wsl -d kali-linux bash -c "ssh srv-monitoring 'cmd'" (NO -tt!)
                  # First connection asks for password, then socket active for 60 minutes (ControlPersist 60m)
                  #
                  # RULE - srv-monitoring: RUN SELF with run_in_terminal
                  # → The ControlMaster socket works, we ran commands several times on our own
                  # → Basic command: wsl -d kali-linux bash -c "ssh srv-monitoring 'cmd'"
                  # → DO NOT use -tt flag (causes ^C), use without -tt
                  # → For rclone with su - monitoring: escape backslashes for spaces in -c
                  # FIXED: wsl -d kali-linux bash -c "ssh srv-monitoring 'su - monitoring -c rclone\ ls\ do:testmonbck/...'"
                  # WRONG: wsl -d kali-linux bash -c "ssh srv-monitoring 'su - monitoring -c \"rclone ls ...\"'"
                  # → If socket has expired → retry executing anyway, don't delegate to user
                  # → Recommended timeout: 60000ms (60 sec)
                  # Don't use more than one block per operation (avoid unnecessary back-and-forth)

# Other servers
fwlab #192.168.5.117:2222 (root)
redteam # redteam.security.nethesis.it (root)

```text

### Remote Access Workflow

** IMPORTANT - Test Environment:**
- **checkmk-vps-02** (monitor01.nethlab.it) is dedicated to **CRITICAL TESTS**
- **ALWAYS** use vps-02 to test:
  - New disaster recovery scripts
  - Changes to backup/restore scripts
  - CheckMK upgrade with critical changes
  - Test procedures that could compromise the system
- **DO NOT test directly on vps-01 (production)**

**1. SSH Single Command:**

```powershell
# From PowerShell → run command on VPS (with generous timeout)
wsl -d kali-linux ssh checkmk-vps-01 "omd version"
# timeout: 30000 (30 sec) - normal SSH command

wsl -d kali-linux ssh checkmk-vps-02 "omd sites"
# timeout: 30000 (30 sec)

# Complex command (check_mk_agent, git pull)
wsl -d kali-linux ssh ns-lab00 "check_mk_agent"
# timeout: 60000 (60 sec) - complex command, long output

wsl -d kali-linux ssh ns-lab00 "cd /opt/checkmk-tools && git pull"
# timeout: 60000 (60 sec) - remote git operation
```

**2. Script execution from GitHub:**

```powershell
# Direct download and execution of scripts from the repository
wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash"

# With parameters
wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/script.sh | bash -s -- arg1 arg2"

```text

**3. Check Remote CheckMK Status:**

```powershell
# Quick check on all VPS
wsl -d kali-linux ssh checkmk-vps-01 "omd status"
wsl -d kali-linux ssh checkmk-vps-02 "omd status"

# Verify backup
wsl -d kali-linux ssh checkmk-vps-01 "ls -lh /opt/omd/sites/monitoring/var/check_mk/notify-backup/"
```text

**4. Deploy script on VPS:**

```powershell
# DO NOT copy files, always run from GitHub!
# WRONG: scp script.sh checkmk-vps-01:/usr/local/bin/
# FIXED: Run from GitHub with curl

wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash"

```text

### Security Notes

- **Passphrase**: Keys require passphrase with each command
  - Not a problem: enter passphrase when prompted
  - Protects unauthorized access

- **StrictHostKeyChecking no**: Disabled for automation
  - OK for lab/indoor environment
  - Evaluate rehabilitation for production

### Common Use Cases

**Remote health check:**

```powershell
# Run integrity check on VPS
wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash -n"

```text

**Check logs:**

```powershell
wsl -d kali-linux ssh checkmk-vps-01 "tail -100 /omd/sites/monitoring/var/log/notify.log"

```text

**System information collection:**

```powershell
wsl -d kali-linux ssh checkmk-vps-01 "df -h && free -h && uptime"

```text

### Path Keys and Config

```bash
# WSL paths
~/.ssh/checkmk # VPS private key (with passphrase)
~/.ssh/config # SSH configuration
~/.ssh/known_hosts # Verified hosts

# Original Windows paths (backup)
C:\Users\Marzio\.ssh\checkmk

```text

---

## Cloud Backup - rclone on CheckMK

** IMPORTANT - Configuring rclone on checkmk-vps-01:**
- rclone is configured **inside the OMD site**, NOT as root user
- Path config: `/opt/omd/sites/monitoring/.config/rclone/rclone.conf`
- Remote configured: `do` (DigitalOcean Spaces)
- Bucket: `testmonbck`
- Structure: `checkmk-backups/job00-daily/`, `checkmk-backups/job01-weekly/`, `checkmk-backups/monitoring-minimal/`

**Correct commands for rclone access:**

```bash
# WRONG (incorrect command)
ssh checkmk-vps-01 'rclone ls do:testmonbck'
ssh checkmk-vps-01 'omd on monitoring -c "rclone ..."'

# CORRECT (su - monitoring -c)
ssh checkmk-vps-01 'su - monitoring -c "rclone ls do:testmonbck"'

# List of latest backups
ssh checkmk-vps-01 'su - monitoring -c "rclone ls do:testmonbck"' | tail -20

# Specific folder list
ssh checkmk-vps-01 'su - monitoring -c "rclone ls do:testmonbck/checkmk-backups/job00-daily/"'

# Check bucket space
ssh checkmk-vps-01 'su - monitoring -c "rclone size do:testmonbck"'

# Specific backup download
ssh checkmk-vps-01 'su - monitoring -c "rclone copy do:testmonbck/checkmk-backups/job00-daily/file.tar.gz /tmp/"'

```text

**Backups available:**
- **job00-daily**: Complete daily backups (~1.2 MB)
- **job01-weekly**: Complete weekly backups with history (~378 MB)
- **monitoring-minimal**: Ultra-minimal backups (~115 KB)

**Automatic backup script:**
- Script: `/opt/checkmk-tools/script-tools/full/backup_restore/checkmk_rclone_space_dyn.sh`
- Run by: site monitoring (not root)
- Cron: Configured within the OMD site

---

## � ABSOLUTE RULES - CheckMK Active/Passive Checks

** LESSON LEARNED MARCH 23, 2026 — COST: COMPLETE SITE RESTORE**

### NEVER do these things without explicit user confirmation:

- **NEVER** `ENABLE_SVC_CHECK` or `DISABLE_SVC_CHECK` on any service
- **NEVER** `DISABLE_SVC_CHECK` on `Check_MK` or `Check_MK Discovery` → causes massive crash on ALL services
- **NEVER** interpret "remove active check" as `DISABLE_SVC_CHECK` — they are DIFFERENT things:
  - "Remove active check" = `active_checks_enabled=0` + `passive_checks_enabled=1` (service receives push)
  - "Disable check" = `DISABLE_SVC_CHECK` → check is NEVER executed/updated → stale
- **NEVER** use `ENABLE_SVC_CHECK` to "fix" stali → causes active override on passive services → breaks everything
- **NEVER** `STOP_EXECUTING_SVC_CHECKS` or `STOP_EXECUTING_HOST_CHECKS` globally
- **NEVER** modify the nagios pipe (`/tmp/run/nagios.cmd`) with bulk commands without explicit approval

### If there are states:

- **DIAGNOSE FIRST** — why doesn't the collector spin?
- Verify that `Check_MK` and `Check_MK Discovery` are `active_checks_enabled=1`
- If the collector runs but the services are off → wait for the next cycle (max 1-2 min)
- If the problem persists → `cmk --check <host>` as monitoring user (NOT pipe nagios)
- **NEVER** iterate with enable/disable/enable/disable → causes flapping and makes everything worse
- **STOP and ask user** before taking any corrective action

---

## � ACCIDENTS AND TROUBLESHOOTING

### January 30, 2026 - Update Windows + VSCode Crash

**INITIAL PROBLEM:**
- Microsoft Windows update caused errors when starting VSCode
- Major error: `EPIPE: broken pipe, write` on internal processes
- Stack trace shows crash in `console.value`, `Writable.write`, socket communication

**WHAT HAS BEEN DONE (AND WORSEN):**
1. Attempted to reset VSCode cache
2. Attempted multiple reboots
3. **Changed login mode to "basic" - THIS BROKE EVERYTHING**
4. Changes to internal configurations
5. Update Windows removed (LATE)
6. Situation got worse instead of better
7. **Thorough Uninstall with Revo Uninstaller + Reinstall VSCode** - Did NOT solve
8. Reset cache post-reinstall - did NOT solve
9. Re-enabled github.gitAuthentication - did NOT fix
10. Restart Windows Explorer - NOT fixed
11. Recreated VSCode registry keys (Applications\Code.exe, DefaultIcon) - did NOT solve

**CURRENT STATUS (30/01/2026 ~19:00):**
- VSCode doesn't start or shows anything
- Last damage not resolved
- Full recovery required
- **CRITICAL PATTERN**:
  - Start-Process from PowerShell → VSCode START
  - Click on Code.exe with mouse → IT DOES NOT START
  - Click on the Start menu shortcut → IT DOES NOT START
  - Command `code .` from terminal → START
  - Any user MANUAL action → FAILS
  - Any action via COMMAND → WORKS
- **VSCode SPECIFIC problem** - other exe (notepad, etc.) work normally with double click
- **NOT general Windows problem** - limited to Code.exe only

**SOLUTION FOUND (01/30/2026 ~7.15pm):**
- VSCode starts correctly with:
  ```powershell
  cd C:\Users\Marzio\Desktop\CheckMK\checkmk-tools
  queues .
  ```

- Important to `cd` into the workspace directory BEFORE running `code .`
- Don't launch `code` without parameters or from a different directory
- **Desktop/start menu link DOES NOT work** - always launch from terminal
- **NO SOLUTION FOUND** to restore normal operation
- Issue caused by Revo Uninstaller deleting critical registry keys
- Recreating registry keys did NOT solve - deeper problem
- **TEMPORARY WORKAROUND**: Open PowerShell and use `code .`

**ROOT CAUSE (01/30/2026 ~7.45pm):**

- Diagnostics with `Code.exe --verbose` reveals:

  ```text
  Sending some foreground love to the running instance: 17752
  Sent env to running instance. Terminating...
  ```

- **VSCode connects to hidden/corrupted zombie instance** instead of opening new window
- When launched from link, VSCode detects existing instance (PID 17752) and sends command to it
- But that window is hidden or corrupted by the Windows update
- `code .` works with workspace because it forces opening in that specific context
- Solution: kill ALL VSCode processes before reopening from the connection

**ROOT CAUSE (01/30/2026 ~7.45pm):**

- Diagnostics with `Code.exe --verbose` reveals:

  ```text
  Sending some foreground love to the running instance: 17752
  Sent env to running instance. Terminating...
  ```

- **Real issue: VSCode opened as ADMINISTRATOR**
- Windows prevents opening multiple VSCode Administrator instances
- Attempt to open from shortcut/Start menu → error "Another instance of Code is already running as administrator"
- `code .` from the integrated terminal works because it uses the same admin instance that is already open
- The Windows update may have forced VSCode to always run as admin
- **Solution to test**: Close VSCode admin, reopen without elevated privileges

** FINAL SOLUTION (30/01/2026 ~10.30 pm) - PROBLEM SOLVED:**

**Real ROOT cause:**

- **Environment variable `ELECTRON_RUN_AS_NODE` present in the system**

- **Environment variable `ELECTRON_RUN_AS_NODE` present in the system**
- This variable (even if set to "0") causes Electron/VSCode to malfunction
- The Windows update may have introduced or reactivated it
- Symptoms: VSCode starts from CLI but NOT from GUI (double click/Start menu)

**Permanent fix (persistent):**

**1. Check variable in cmd.exe:**

```cmd
set ELECTRON_RUN_AS_NODE

```text

If it shows something like `ELECTRON_RUN_AS_NODE=0` or other value → **must be removed completely**

**2A. Removal via GUI (recommended):**
```text

1. Win + R → run: SystemPropertiesAdvanced
2. "Advanced" tab → "Environment variables..." button
3. Search ELECTRON_RUN_AS_NODE in:
   - "User variables" (top section)
   - "System variables" (bottom section)
4. If present → Select → "Delete" button
5. OK on all windows
6. Logout/Login Windows (or restart)

```text

**2B. Removal via CLI (fast):**

```cmd
# Open cmd.exe as Administrator and run:
reg delete "HKCU\Environment" /v ELECTRON_RUN_AS_NODE /f
reg delete "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v ELECTRON_RUN_AS_NODE /f

```text

Then **logout/login** (or restart) Windows.

**3. Check after logout/login:**

```cmd
set ELECTRON_RUN_AS_NODE

```text

Must show:

```text

Environment variable ELECTRON_RUN_AS_NODE not defined

```text

**4. VSCode final check:**

```cmd
"C:\Program Files\Microsoft VS Code\Code.exe" --version
"C:\Program Files\Microsoft VS Code\Code.exe" --disable-extensions

```text

Expected:
- `--version` **MUST NOT show** strange output like "v22.x.x"
- `--disable-extensions` starts VSCode correctly
- Log "Extension host ... exited with code: 0" is normal with extensions disabled

**5. Normal startup:**

```cmd
"C:\Program Files\Microsoft VS Code\Code.exe"

```text

 Double click on Code.exe, shortcut Start menu, everything **works correctly**

**6. VSCode reinstallation notes (if necessary):**
- Always use: **System Installer x64** → `VSCodeSetup-x64-<version>.exe`
- Avoid: `VSCodeUserSetup-...` (User Installer), especially after Windows feature update

**7. Settings recovery (optional):**
If you had renamed `%APPDATA%\Code` (e.g. `Code.old`):

```powershell
# Close VSCode completely
# Rename for testing:
Rename-Item "$env:APPDATA\Code" "$env:APPDATA\Code.new"
Rename-Item "$env:APPDATA\Code.old" "$env:APPDATA\Code"
# Start VSCode
# If problems return, rollback:
# Rename-Item "$env:APPDATA\Code" "$env:APPDATA\Code.problem"
# Rename-Item "$env:APPDATA\Code.new" "$env:APPDATA\Code"

```text

**CRITICAL CHECKPOINT:**
- **Variable ELECTRON_RUN_AS_NODE = poison** for VSCode/Electron
- Always check with `set ELECTRON_RUN_AS_NODE` in case of VSCode problems
- Remove it COMPLETELY (don't just set it to "0")
- Windows logout/login **required** after removal

**LESSONS LEARNED:**
- `EPIPE: broken pipe` errors are **transient** - DO NOT require reboot
- Stack traces with path `Microsoft%20VS%20Code/resources.../` indicate problems **internal VSCode**
- First action: **remove Windows update IMMEDIATELY** (not after several attempts)
- Second action: **minimal cache reset** (not aggressive changes)
- **NEVER** modify internal configurations without complete backup
- Create **System Restore Point BEFORE** aggressive troubleshooting

**VSCode EMERGENCY RESTORATION PROCEDURES:**

**Step 1 - Soft cache reset (ALWAYS try first):**

```powershell
# Close VSCode
taskkill /F /IM Code.exe

# Clear volatile cache only
Remove-Item -Recurse -Force "$env:APPDATA\Code\Cache\*" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:APPDATA\Code\CachedData\*" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:APPDATA\Code\logs\*" -ErrorAction SilentlyContinue

# Restart
queues

```text

**Step 2 - Reset extensions (if Step 1 fails):**

```powershell
# Backup extension list
code --list-extensions > "$env:USERPROFILE\Desktop\vscode-extensions-backup.txt"

# Disable all extensions
code --disable-extensions

```text

**Step 3 - Clean Reinstall (Last Resort):**

```powershell
# Backup user configurations
Copy-Item -Recurse "$env:APPDATA\Code\User" "$env:USERPROFILE\Desktop\VSCode-User-Backup"

# Uninstall VSCode (keep user data)
# Reinstall stable version from https://code.visualstudio.com/

# Restore configurations
Copy-Item -Recurse "$env:USERPROFILE\Desktop\VSCode-User-Backup\*" "$env:APPDATA\Code\User"

```text

**CRITICAL RULE FOR THE FUTURE:**
- `EPIPE`, `broken pipe`, socket errors = **IGNORE AND CONTINUE**
- They are not critical, they are internal IPC communications that reset themselves
- Restart VSCode window (Ctrl+R) sufficient if really necessary
- **DO NOT** aggressively troubleshoot transient errors

**CRITICAL BACKUP PATH:**
- Settings: `$env:APPDATA\Code\User\settings.json`
- Keybindings: `$env:APPDATA\Code\User\keybindings.json`
- Extensions list: `code --list-extensions`
- Workspace: `.vscode/` inside each project

---

## CHECKPOINT - ROCKSOLID NethSecurity 8 system

### CURRENT STATUS (2026-02-10): SYSTEM DECOMMITED

**ATTENTION:**
- **ROCKSOLID system removed from nsec8-stable and lab** (February 10, 2026)
- **DO NOT run install-checkmk-agent-persistent-nsec8.sh** on nsec8-stable (10.155.100.100) and lab (10.155.100.1)
- CheckMK Agent and FRP remain up and running
- Repository /opt/checkmk-tools still present (git auto-sync working)
- Removed: /opt/checkmk-backups/, /etc/checkmk-post-upgrade.sh, autocheck rc.local, sysupgrade.conf protections

**Components removed:**
- Critical binary backups (/opt/checkmk-backups/binaries/)
- Post-upgrade script (/etc/checkmk-post-upgrade.sh)
- Autocheck on startup (rocksolid-startup-check.sh)
- sysupgrade.conf protections (CheckMK, FRP, QEMU-GA entries)
- FRP Marker (/etc/.frp-installed)

**Components retained:**
- CheckMK Agent (port 6556) - working
- FRP Client + tunnel configuration
- QEMU Guest Agent
- Repository /opt/checkmk-tools + auto-sync git (cron every minute)

---

### Implementation Complete (2026-02-04) - HISTORY

**Goal achieved:**
- Removed ALL static/hardcoded URLs from installation scripts
- Dynamic download of packages from OpenWrt/NethSecurity repositories
- Post major-upgrade self-healing system
- Complete validation on host production

**Validated and production-ready scripts:**

1. **install-checkmk-agent-persistent-nsec8.sh** (commit b29a2cf)
   - Path: `script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh`
   - Function: Full Installation CheckMK Agent + FRP Client + QEMU-GA + Auto Git Sync
   - Fixes implemented:
     - Dynamic package download via `download_openwrt_package()`
     - Pattern fix: `grep "${package_name}_"` (fixes packet detection)
     - Dependencies chain: libbfd → ar → objdump → binutils with `--force-depends`
     - Binary corruption management (AR corrupted during upgrade)
   - Test: nsec8-stable, lab (from GitHub)

2. **rocksolid-startup-check.sh** (commit ea67364)
   - Path: `script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh`
   - Function: Verification and auto-remediation at system startup
   - Fixes implemented:
     - Logic reordering: backup restore → corruption check → dependencies install
     - Git auto-install: download git + git-http from OpenWrt if missing
     - Pattern fix identical to install script
     - Check AFTER backup restore (not before)
   - Test: nsec8-stable, lab (from GitHub)

**Validated hosts (production):**

| Hosts | IP | OS | Status | Packages |
|------|----|----|--------|----------|
| **nsec8-stable** | 10.155.100.100:22 | NethSecurity 8.7.1 |  ROCKSOLID | ar 2.40-1, git 2.43.2-1, libbfd 2.40-1 |
| **laboratory** | 10.155.100.1:2222 | NethSecurity 8.7.1 |  ROCKSOLID | ar 2.40-1, git 2.43.2-1, libbfd 2.40-1 |

**Active components:**
- CheckMK Agent 2.4.0p20 (port 6556)
- FRP Client (tunnel to monitor.nethlab.it:7000)
- Auto Git Sync (cron every minute, /opt/checkmk-tools)
- Rocksolid startup check (rc.local, log: /var/log/rocksolid-startup.log)
- 12 local checks deployed

**Major upgrade protections:**
- Critical files in `/etc/sysupgrade.conf`
- Binaries backed up in `/opt/checkmk-backups/binaries/`
- Nginx configuration (`/etc/nginx/`) protected
- Self-recovery script: `/etc/checkmk-post-upgrade.sh`

### Technical Details

**Dynamic Package Download:**

```bash
download_openwrt_package() {
    local package_name="$1"
    local repo_url="$2"
    local output_path="$3"

    # Download Packages.gz index
    wget -q -O /tmp/Packages.gz "$repo_url/Packages.gz"

    # Parse package filename (fix: grep "${package_name}_" not "/$package_name")
    local package_file=$(gunzip -c /tmp/Packages.gz | grep "^Filename:" | grep "${package_name}_" | head -1 | awk '{print $2}')

    # Download package
    wget -q -O "$output_path" "$repo_url/$package_file"
}

```text

**Dependencies Chain (circular dependency fix):**

```bash
# Order matters: libbfd first (shared library), then ar (uses libbfd)
opkg install --force-depends /tmp/libbfd.ipk
opkg install --force-depends /tmp/ar.ipk
opkg install --force-depends /tmp/objdump.ipk
opkg install --force-depends /tmp/binutils.ipk

```text

**Rocksolid Logic (fixed order):**

```bash
# STEP 1: Restore backups FIRST
for backup in /opt/checkmk-backups/binaries/*.backup; do
cp -p "$backup" "$dest" 2>/dev/null || true
done

# STEP 2: Check corruption AFTER restore (not before!)
if [ -x /usr/bin/ar ]; then
    if ! /usr/bin/ar --version >/dev/null 2>&1; then
        BINARIES_CORRUPTED=1
    fi
fi

# STEP 3: Install dependencies if still corrupted
if [ $BINARIES_CORRUPTED -eq 1 ]; then
    download_openwrt_package "libbfd" "$REPO_BASE" "/tmp/libbfd.ipk"
    opkg install --force-depends /tmp/libbfd.ipk
    download_openwrt_package "ar" "$REPO_BASE" "/tmp/ar.ipk"
    opkg install --force-depends /tmp/ar.ipk
fi

```text

### Testing Workflow Validated

**Mandatory workflow followed:**
1. Edit script (dynamic download, pattern fix, logic reorder, git auto-install)
2. Syntax test: `wsl bash -n script.sh` (exit code 0)
3. Check executable: `git ls-files -s` (100755)
4. Commit + push: b29a2cf, ea67364, 68661c1, 67f3cbc
5. Test on nsec8-stable: `curl -fsSL https://raw.githubusercontent.com/.../script.sh | bash`
6. Lab testing: `curl -fsSL https://raw.githubusercontent.com/.../script.sh | bash`
7. Output validation: ar/git/libbfd correct versions installed

**Real tests performed:**
- Post major upgrade scenario (corrupt ar, missing git)
- Fresh install on clean system
- Re-install on an already configured system (idempotence)
- Running from GitHub (not local repo)

### Lessons Learned

**Pattern Matching:**
- `grep "/$package_name"` → Can't find "package_name_version.ipk"
- `grep "${package_name}_"` → Fixed for Packages.gz format

**Circular Dependencies:**
- `opkg install binutils` → "cannot find dependency ar"
- Install chain: libbfd → ar → objdump → binutils with `--force-depends`

**Backup Restore Timing:**
- Check corruption BEFORE backup restore → Missing post-upgrade binaries never detected
- Restore backups FIRST, THEN check corruption → Detects problems even if binary present but corrupt

**Testing:**
- Test only 1 of 3 modified scripts → Untested scripts fail in production
- Test ALL scripts modified in the session → 100% coverage
- Test from local repo → May be bad
- Test from GitHub raw URL → Guarantees production source

**Git Auto-Install:**
- Git can be removed during major upgrades
- Auto-sync repository requires working git
- Rocksolid must auto-install git if missing
- Required: git + git-http (dependency)

### Production-Ready system

**Final status:**
- Both hosts (nsec8-stable, laboratory) ROCKSOLID mode active
- All critical tracks protected and self-repairable
- CheckMK Agent, FRP Client, QEMU-GA operational
- Auto Git Sync working (repository updated every minute)
- System resilient to NethSecurity/OpenWrt major upgrades
- Zero hardcoded URLs - all dynamic from upstream repositories

**Upcoming major upgrades:**
- System auto-repairs corrupt binaries (ar, tar, gzip, libbfd)
- System auto-installs git if removed
- System checks and restarts critical services (CheckMK, FRP)
- Detailed log in `/var/log/rocksolid-startup.log`
- **Zero manual intervention required**

---

**Last update**: 2026-02-04

---

## Ydea-Toolkit - CheckMK integration on srv-monitoring

### Path script (CheckMK notification scripts, without extension)

```bash
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_la
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_ag
```

### Manual notification test

```bash
su -monitoring -c"
  cd /omd/sites/monitoring/local/share/check_mk/notifications/ && \
  NOTIFY_WHAT=PROBLEM \
  NOTIFY_HOSTNAME=ns8.ad.studiopaci.info \
  NOTIFY_SERVICEDESC=CPU \
  NOTIFY_SERVICESTATE=CRITICAL \
  NOTIFY_SERVICEOUTPUT='CPU load 95%' \
  NOTIFY_NOTIFICATIONTYPE=PROBLEM \
  python3 ydea_la
"
# Check cache
cat /opt/ydea-toolkit/cache/ydea_checkmk_tickets.json
```

### Ydea Cache (correct path post fix installer commit b8f2090)

```text
/opt/ydea-toolkit/cache/ydea_checkmk_tickets.json
/opt/ydea-toolkit/cache/ydea_checkmk_flapping.json
/opt/ydea-toolkit/cache/ydea_cache.lock
```

### Quick manual fix on already installed hosts

```bash
mkdir -p /opt/ydea-toolkit/cache
echo '{}' > /opt/ydea-toolkit/cache/ydea_checkmk_tickets.json
echo '{}' > /opt/ydea-toolkit/cache/ydea_checkmk_flapping.json
touch /opt/ydea-toolkit/cache/ydea_cache.lock
chmod 666 /opt/ydea-toolkit/cache/*.json /opt/ydea-toolkit/cache/*.lock
chmod 777 /opt/ydea-toolkit/cache
chmod 640 /opt/ydea-toolkit/.env.la /opt/ydea-toolkit/.env.ag
chown monitoring:monitoring /opt/ydea-toolkit/.env.la /opt/ydea-toolkit/.env.ag
```

### Notes

- API key `Y_KEY_8c814108a0345fdeace7fb9c637fb6c9` → **expired** (February 2026) - wait for new key
- Log: `tail -f /var/log/ydea_health.log` and `tail -f /var/log/ydea_cache_validator.log`