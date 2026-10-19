# CheckMK — GitHub ecosystem (research 2026-09-01)

Public GitHub search for third-party repos dedicated to CheckMK, for comparison/inspiration against `checkmk-tools`. Does not include internal Coverup20 repos (checkmk-tools, ns8-checkmk-agent, ns8-checkmk-container, private CheckMK repo).

## Official (Checkmk GmbH)

| Repo | ★ | Description |
|---|---|---|
| [Checkmk/checkmk](https://github.com/Checkmk/checkmk) | 2353 | Core product (Python) |
| [Checkmk/ansible-collection-checkmk.general](https://github.com/Checkmk/ansible-collection-checkmk.general) | 179 | Official Ansible collection |
| [Checkmk/grafana-checkmk-datasource](https://github.com/Checkmk/grafana-checkmk-datasource) | 102 | Grafana datasource |
| [Checkmk/ansible-checkmk](https://github.com/Checkmk/ansible-checkmk) | 57 | Ansible integration |
| [Checkmk/checkmk-docs](https://github.com/Checkmk/checkmk-docs) | 43 | Official user manual |
| [Checkmk/checkmk_kube_agent](https://github.com/Checkmk/checkmk_kube_agent) | 23 | Kubernetes agent |

## Notifications (direct overlap with checkmk-tools' Telegram/notify stack)

| Repo | ★ | Description |
|---|---|---|
| [filipnet/checkmk-telegram-notify](https://github.com/filipnet/checkmk-telegram-notify) | 73 | Telegram alerts, bash |
| [deexno/checkmk-telegram-plus](https://github.com/deexno/checkmk-telegram-plus) | 29 | Interactive Telegram bot (host/service queries, not just push) |
| [rileymichael/checkmk-notify-teams](https://github.com/rileymichael/checkmk-notify-teams) | 21 | Microsoft Teams alerts |

## LLM / MCP — direct comparison with our setup ([[cmk_mcp_servers]])

| Repo | ★ | Description |
|---|---|---|
| [chexma/vibeMK](https://github.com/chexma/vibeMK) | 16 | MCP server to manage CheckMK via LLM — see analysis below |

## Device special agents / plugins

| Repo | ★ | Description |
|---|---|---|
| [bashclub/checkmk-opnsense-agent](https://github.com/bashclub/checkmk-opnsense-agent) | 103 | OPNsense special agent |
| [bashclub/check-unifi-controller](https://github.com/bashclub/check-unifi-controller) | 47 | Unifi special agent |
| [WagnerAG/checkmk_fortigate](https://github.com/WagnerAG/checkmk_fortigate) | 15 | Fortigate special agent (FW/switch/AP) |
| [bashclub/check-zfs-replication](https://github.com/bashclub/check-zfs-replication) | 17 | ZFS replication check |
| [edvler/check_mk_proxmox-qemu-backup](https://github.com/edvler/check_mk_proxmox-qemu-backup) | 18 | Proxmox QEMU VM backup check |

## Check collections / generic tooling

| Repo | ★ | Description |
|---|---|---|
| [kuhn-ruess/cmdbsyncer](https://github.com/kuhn-ruess/cmdbsyncer) | 69 | Rule sync between CheckMK, Netbox, PRTG, Ansible etc. |
| [hweidner/check-mk-goodies](https://github.com/hweidner/check-mk-goodies) | 62 | Various Linux checks (Perl) |
| [elabit/robotmk](https://github.com/elabit/robotmk) | 59 | Robot Framework integration |
| [kuhn-ruess/Checkmk-Checks](https://github.com/kuhn-ruess/Checkmk-Checks) | 51 | Custom check collection |
| [brennerm/check-mk-web-api](https://github.com/brennerm/check-mk-web-api) | 53 | Python library for the Web API |
| [chrisss404/check-mk-arm](https://github.com/chrisss404/check-mk-arm) | 187 | CheckMK build for Raspberry Pi |
| [jiuka/checkmk_template](https://github.com/jiuka/checkmk_template) | 31 | Official template for new extensions |
| [HenriWahl/checkmk-agent-plugin-yum](https://github.com/HenriWahl/checkmk-agent-plugin-yum) | 31 | RPM/yum update check plugin |

## Adjacent (not CheckMK but same monitoring space)

| Repo | ★ | Description |
|---|---|---|
| [HenriWahl/Nagstamon](https://github.com/HenriWahl/Nagstamon) | 459 | Desktop status monitor (Nagios/CheckMK/...) |
| [inexio/thola](https://github.com/inexio/thola) | 297 | Network monitoring tool via SNMP |
| [ConSol/sakuli](https://github.com/ConSol/sakuli) | 123 | End-to-end testing/monitoring UI |

---

## Detailed report — official repos + notifications (scan 2026-09-01)

### Checkmk/checkmk (core, 2.4k★, 556 forks, 57 open PRs)
The product itself. Agent-based/agentless monitoring, web UI, multi-tenant on Pro/Ultimate editions. Multi-language stack (Python, Rust, C++, Go, JS), built with Bazel, 109k commits on master. GPLv2 license for the Community edition (CRE); Pro/Ultimate/Ultimate+MT are commercial, plus a SaaS offering (Checkmk Cloud). Packaged for RedHat/SUSE/Debian/Ubuntu (RPM/DEB), Docker for all editions, physical/virtual appliances for the paid editions. No action needed — this is the upstream the whole stack depends on.

### Checkmk/ansible-collection-checkmk.general (179★, 84 forks, 6.3k commits)
Official Ansible collection, but **community-maintained, "as-is", no commercial support**. Covers nearly all the config-as-code we're missing: modules for host, folder, rule, downtime, users, contact/host/service groups, discovery, activation, bakery, LDAP, notifications, passwords, roles, sites, tag groups, time periods; dynamic inventory + 20+ lookup plugins. 8 open issues, 7 open PRs, CI on GitHub Actions for every module/role. Installed via `ansible-galaxy`. **Relevant**: if we ever need to automate CheckMK provisioning/config beyond the current scripts, this collection already covers ~90% of the ground — worth evaluating before writing anything new.

### Checkmk/grafana-checkmk-datasource (102★, 464 commits)
Official Grafana plugin to query CheckMK as a datasource and visualize metrics in dashboards. TypeScript/React stack (standard Grafana plugin architecture), Webpack build, Jest tests. Apache-2.0 license. 21 open issues, few PRs — active development but with a backlog. Requires CheckMK ≥2.3.0 and Grafana ≥10.4.18. Installable from the Grafana Marketplace or `grafana-cli`. We don't have Grafana in the current stack, but if it's ever introduced this is the official option, no need to evaluate alternatives.

### Checkmk/checkmk-docs (43★, 6.5k commits, 5 open issues)
This is the full source of the official manual (not just excerpts), in AsciiDoc/Asciidoctor, auto-published to docs.checkmk.com on every push. Maintainers prefer issues over direct PRs due to multiple languages, different branches, and specific AsciiDoc macros. Useful only as documentation reference, not as reusable code.

### filipnet/checkmk-telegram-notify (73★, 31 forks, 58 commits, 0 open issues)
**Direct comparison with our Telegram script.** Pure bash plugin in the CheckMK notification framework: CheckMK invokes the script with bot token + chat ID, the script formats and sends via the Bot API. Notable features we may not cover:
- **Telegram thread/topic support** (routes notifications to specific threads of a group, combining group ID and thread ID with `:`)
- **IP masking** (v4/v6), configurable via regex before sending, for privacy
- flexible targeting: group ID, chat ID, or per-user attributes

Compatible with CheckMK 1.6.0p18→2.4.0p4. BSD-3-Clause license. Stable (0 issues), unclear if still actively maintained. **Concrete takeaway**: IP masking and thread support are two features that (as far as I recall) are missing from our Telegram script — worth checking.

### deexno/checkmk-telegram-plus (29★, 4 forks, 138 commits, 0 open issues)
Goes beyond push notifications: an **interactive Telegram bot** with a Flask + SQLite webapp for state, optional OpenAI integration for "smart" notifications, run as a systemd service in a venv. Bot commands: host status, service list/detail (with metrics), aggregated problem view, graph export, manual recheck, acknowledge. Authenticates to CheckMK via an automation user (local Web API). Apache-2.0 license, one-liner installer (`curl | sudo bash`). **Relevant**: does on the Telegram side what our MCP servers (`cmk-us`/`cmk-sp`/etc) do on the Claude side — interactive CheckMK queries, but with Telegram as the interface instead of an LLM. Potentially reusable idea: acknowledge/recheck from chat without going through Claude.

### rileymichael/checkmk-notify-teams (21★, 11 forks, 7 commits, 0 issues — **archived 2024-12-26, read-only**)
Minimal shell script in the CheckMK notification framework, sends to a Teams webhook. Supports CheckMK 1.x/2.x, MIT license. Only 7 commits, archived repo: a working but abandoned solution, to be treated as a reference/idea, not a live dependency.

---

## Deep dive — core version check + ansible-collection evaluation (2026-09-01)

### Core version: aligned with the latest release ✅
Most recent tag on `Checkmk/checkmk`: **v2.5.0p12** (they don't use GitHub Releases, only tags — no "Releases" page published).

Verified via `omd version` on the 4 live sites:

| Site | Version |
|---|---|
| srv-monitoring-sp | 2.5.0p12.community |
| srv-monitoring-us | 2.5.0p12.community |
| checkmk-vps-01 | 2.5.0p12.community |
| checkmk-vps-02 | 2.5.0p12.community |

**All 4 sites are exactly on the latest patch published upstream.** No action needed.

### ansible-collection.general changelog — what's changing in recent releases
Relevant recent entries (CHANGELOG.rst, v7.8.0→v8.4.0):
- **v8.4.0** (current): idempotency fix on `contact_group`/`host_group`/`service_group` when `title` is missing; REST API errors from lookup modules now report the Checkmk detail instead of just the generic status code.
- **v8.1.0**: security fix — MKP management tasks no longer print `download_password` in clear text in the loop label.
- **v8.0.0 (breaking)**: `user` module — `auth_type` no longer defaults to `password`; playbooks that create local users without setting it explicitly need updating.
- **v7.8.0**: `discovery` — added support for **Checkmk 3.0**.
- ⚠️ **Note for the future**: a recent minor change states that *"Checkmk 3.0 removes the GET variants of the monitoring collection endpoints"* of the REST API — when 3.0 lands, any of our scripts (including those behind `cmk_rest_api`/`cmk_ydea`/CISO tooling) that do a `GET` on a *monitoring collection* endpoint will need checking. Not an issue today (we're on 2.5.x), but it's a known change already in the upstream changelog — worth keeping in mind when planning the 3.0 upgrade.

### Evaluation: ansible-collection.general vs. our current toolchain

**What we already cover today via MCP** (`cmk_host_create/delete`, `cmk_user_create/delete/password`, `cmk_downtime/downtime_remove`, `cmk_host_groups`, `cmk_discover_host`, `cmk_activate_changes`) + direct Python scripts against the REST API in `script-tools/full/`.

**What the collection offers that we don't cover with anything today:**
- `folder` module — folder structure management
- `rule` module — ruleset creation/editing (today done manually from the UI)
- dedicated `contact_group` (we only have host_groups)
- `tag_group`, `time_period` — no equivalent
- `notification_rule`, `password` (password store), `role`, `site` — advanced config, 100% manual from the UI today
- **Dynamic inventory + 20+ lookup plugins** — potentially useful if Ansible were ever used for other tasks (agent deployment, patching) and pulling the host list from Checkmk instead of maintaining it by hand

**Practical assessment:**
- Not "as-is"/community-maintained in the bad sense of the term — solid CI, curated changelog, breaking changes explicitly flagged. Reliable to use.
- **Not worth replacing what already works** (MCP + direct REST scripts) — that would just be a second way of doing the same thing, plus an extra dependency layer (Ansible + collection) to maintain.
- **Makes sense only for the real gaps**: if the need arises to manage `rule`/`folder`/`tag_group`/`time_period` in an automated/idempotent way (e.g. provisioning a new site from scratch, or replicating config across the 4 sites), this is the right tool — it's config-as-code work not currently done with anything else, not a duplication.
- **Not a priority right now**: nothing in the current fleet signals a need for it. Keep as a reference for if/when repeatable multi-site provisioning becomes necessary.

---

## Minor/niche finds (scan 2026-09-01)

Broader search beyond the top-starred repos: small but interesting projects, some brand new (updated the same day as the search).

### 🤖 AI / Claude — the most relevant for our stack
- [madic-creates/claude-alert-analyzer](https://github.com/madic-creates/claude-alert-analyzer) — receives webhooks from Alertmanager and CheckMK, gathers diagnostic context and uses **Claude** for root-cause analysis, notifies via ntfy. Same pattern as what's already built with Claude Ops on z1-00 + MCP servers, but published as a standalone project — worth comparing.
- [chexma/claude_code_checkmk_plugin_skill](https://github.com/chexma/claude_code_checkmk_plugin_skill) — a Claude Code skill for CheckMK (same author as vibeMK).
- [oposs/cmk-oposs-plugin](https://github.com/oposs/cmk-oposs-plugin) — a Claude Code skill for building/packaging CheckMK 2.3.x plugins.

Three "Claude Code + CheckMK" skills found in the same scan: a sign this is an active trend right now, not an isolated case.

### 🐛 Exotic notifications
- [Berghmans/cmk_discord](https://github.com/Berghmans/cmk_discord) (11★) — Discord notifications
- [bashclub/check_mk_matrix_notifications](https://github.com/bashclub/check_mk_matrix_notifications) (9★) — Matrix notifications

### 🏠 Homelab
- [aschmidtlev/ha-cmk](https://github.com/aschmidtlev/ha-cmk) — Home Assistant integration
- [chrisss404/check-mk-arm](https://github.com/chrisss404/check-mk-arm) (187★) — CheckMK on Raspberry Pi
- [BenediktSeidl/nixos-check_mk_agent-overlay](https://github.com/BenediktSeidl/nixos-check_mk_agent-overlay) — NixOS overlay for the agent

### ☸️ Brand new from the official org
- [Checkmk/cmk-rustik](https://github.com/Checkmk/cmk-rustik) — in-cluster Kubernetes agent written in Rust, 1★, updated the same day — not mature yet, worth watching.

### 🔌 Niche special agents (the `oposs` shop, all published on 08/31)
`cmk-oposs_bgp_mon` (BGP), `cmk-oposs_ceph` (Ceph cluster), `cmk-oposs_zpool_iostat` (ZFS I/O), `cmk-oposs_smart_error` (disk SMART), `cmk-oposs_pbs` (Proxmox Backup Server via REST API).

### 🏢 Enterprise niche
- [CLiX-1/cmk_plugin_microsoft_365](https://github.com/CLiX-1/cmk_plugin_microsoft_365) and [cmk_plugin_ms_entra](https://github.com/CLiX-1/cmk_plugin_ms_entra) — M365/Entra special agents
- [inettgmbh/checkmk-proxmox_backup_server](https://github.com/inettgmbh/checkmk-proxmox_backup_server) (14★) — alternative to `cmk-oposs_pbs`

### 🎈 The most useless, and therefore the best
- [deexno/CheckMK_DSL_check](https://github.com/deexno/CheckMK_DSL_check) — displays speedtest data inside CheckMK.

---

## Analysis: chexma/vibeMK

**What it does:** an MCP server exposing CheckMK in natural language to an LLM client (e.g. Claude Desktop) — the same functional goal as our `cmk-us`/`cmk-sp`/`cmk-vps-01`/`cmk-vps-02` servers ([[cmk_mcp_servers]]).

**Stack:** Python 3.8+, type-checked (mypy), formatted with black, tested with pytest. Modular architecture: CheckMK REST API layer, MCP (protocol) module, feature handlers, configuration/type management.

**Functional coverage (from the exposed tools):**
- Monitoring: real-time host/service status, performance metrics, active problems
- Maintenance: downtime, acknowledge
- Configuration: folders, rules, time periods, host groups, users, tags
- Analysis: metric comparison, ruleset analysis/optimization

This last point (config-as-code + ruleset analysis) is broader than what we cover today: our servers are geared toward reading/operations (status, problems, stale, downtime, list_hosts — 6 tools per host, see [[cmk_mcp_servers]]), not creating rules/folders/users via LLM.

**Maturity:** Alpha stage, stated as "under active development", 16★/9 forks, 2 open issues, explicit liability disclaimer — treat as a proof-of-concept, not a production reference. GPLv3 license.

**Takeaway:** if `cmk_mcp_server.py` is ever extended toward configuration operations (not just reading), it's worth looking at how vibeMK structures its handlers before designing from scratch.
