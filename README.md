#  CheckMK Tools Collection

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CheckMK](https://img.shields.io/badge/CheckMK-Compatible-green.svg)](https://checkmk.com/)
[![PowerShell](https://img.shields.io/badge/PowerShell-5.1+-blue.svg)](https://github.com/PowerShell/PowerShell)
[![Bash](https://img.shields.io/badge/Bash-4.0+-green.svg)](https://www.gnu.org/software/bash/)
[![Language](https://img.shields.io/badge/Lingua-Italiano%20-green.svg)](https://github.com/Coverup20/checkmk-tools)

Collezione completa di script per il monitoraggio e la gestione di infrastrutture con CheckMK. Include script di check per diverse piattaforme, sistemi di notifica personalizzati, tool di deployment automatizzato, backup cloud, e automazione completa.

>  **Nota**: Questo repository è principalmente in italiano. Documentazione e commenti sono in lingua italiana.

---

##  Indice

- **Caratteristiche Principali**
- **Struttura Repository**
- **Script di Check**
  - Windows
  - NethServer 7
  - NethServer 8
  - Ubuntu/Linux
  - Proxmox
- **Script di Notifica**
- **Tool di Deploy**
- **Automazione e Backup**
- **Installazione**
- **Documentazione**
- **Contributi**

---

##  Caratteristiche Principali

###  Multi-Piattaforma

- **Windows**: PowerShell scripts per Windows Server (AD, IIS, Ransomware Detection)
- **Linux**: Bash scripts per NethServer, Ubuntu, Proxmox
- **Container**: Monitoraggio Podman/Docker su NethServer 8

###  Auto-Update Pattern

- **Remote Wrappers**: Script che si auto-aggiornano da GitHub
- **Cache Intelligente**: Sistema di caching con timeout configurabile (60s default)
- **Fallback Resiliente**: Usa cache obsoleta se GitHub non raggiungibile

### � ROCKSOLID Mode - Agent Resistente agli Upgrade

- **NethSecurity 8**: Installazione agent CheckMK + FRP resistente ai major upgrade
- **Auto-Recovery**: Script di avvio che ripristina servizi automaticamente
- **Backup Binari**: Protezione `tar`, `ar`, `gzip` da corruzione
- **FRP Dual-Format**: Supporto FRP v0.x e v1.x con rilevamento automatico
- **Protezioni Totali**: 13 file critici protetti in `/etc/sysupgrade.conf`
- **Validazione Completa**: Testato su NethSecurity 8.7.1 + CheckMK 2.4.0p20

### � Deploy Automatizzato

- **Smart Deploy**: Sistema ibrido per deployment multi-host
- **Backup Automatico**: Snapshot pre-deployment con rollback
- **Validazione**: Test sintassi e funzionalità pre-deployment
- **Interactive Menu**: Deploy interattivo con selezione script per OS

###  Nethesis Branding per CheckMK

- **Rebranding completo**: Logo, colori e CSS per tema facelift di CheckMK
- **Multi-server**: Deploy su tutti i server con un solo script
- **Asset statici**: SVG con logo embedded in `nethesis-brand/`
- **Idempotente**: Sicuro da rieseguire, non rompe la configurazione esistente

###  Backup Cloud Automatizzato

- **rclone Integration**: Backup CheckMK su cloud storage (S3, DigitalOcean Spaces, ecc.)
- **Retention Intelligente**: Gestione automatica retention locale e remota
- **Rename Automatico**: Timestamp automatico per backup completati
- **Monitoring Timer**: Check ogni minuto per nuovi backup
- **Auto-Install Dipendenze**: Installazione automatica rclone e dipendenze

###  Auto-Upgrade CheckMK

- **Upgrade Automatico**: Setup wizard per upgrade CheckMK via crontab
- **Always Latest**: Scarica sempre ultima versione script da GitHub
- **Compatibilità Universale**: Supporto bash 3.2+ con metodo download-to-temp
- **Configurazione Interattiva**: Wizard step-by-step per configurazione completa

###  Notifiche Avanzate

- **Email Real IP**: Notifiche con IP reale anche dietro proxy FRP
- **Telegram Integration**: Notifiche Telegram con detection automatica scenario
- **HTML + Grafici**: Email HTML con grafici performance inclusi

---

##  Struttura Repository

```text

checkmk-tools/
├── script-check-windows/          # Script check per Windows
│   ├── nopolling/
│   │   └── ransomware_detection/  #  Rilevamento ransomware real-time
│   └── polling/
│
├── script-check-ns7/              # Script check per NethServer 7
│   ├── doc/                       # Documentazione
│   ├── full/                      # Script completi standalone
│   └── (remote rimosso)           # Solo script full (launcher remoti dismessi)
│
├── script-check-ns8/              # Script check per NethServer 8
│   ├── doc/                       # Documentazione
│   ├── full/                      # Script completi (Podman, Webtop, Tomcat)
│   └── (remote rimosso)           # Solo script full
│
├── script-check-nsec8/            # Script check per NethSecurity 8
│   ├── doc/                       # Documentazione
│   ├── full/                      # Script completi
│   └── (remote rimosso)           # Check Python puri in full/
│
├── script-check-ubuntu/           # Script check per Ubuntu/Linux
│   ├── doc/                       # Documentazione
│   ├── full/                      # Script completi (SSH, Fail2ban, Disk)
│   ├── (remote rimosso)           # Solo script full
│   └── deploy-ssh-checks.sh       # Deploy automatico check SSH
│
├── script-check-proxmox/          # Script check per Proxmox VE
│   ├── doc/                       # Documentazione
│   ├── full/                      # Script completi API Proxmox
│   └── (remote rimosso)           # Solo script full
│
├── script-notify-checkmk/         # Script notifica personalizzati
│   ├── doc/                       # Documentazione
│   ├── full/                      # Script notifica completi
│   │   ├── mail_realip*           # Email con IP reale + grafici
│   │   ├── telegram_*             # Notifiche Telegram
│   │   ├── ydea_*                 # Integrazione Ydea ticketing
│   │   └── dump_env               # Utility debug environment
│   └── (remote rimosso)           # Solo script full
│
├── script-tools/                  # Tool deployment e utility
│   ├── doc/                       # Documentazione
│   ├── full/                      # Tool completi
│   │   ├── smart-deploy-hybrid.sh     # Deploy intelligente multi-host
│   │   ├── deploy-monitoring-scripts.sh  #  Deploy interattivo OS-aware
│   │   ├── deploy-plain-agent*.sh     # Deploy agent CheckMK
│   │   ├── install-frpc*.sh           # Installazione FRP client
│   │   ├── install-agent-interactive.sh  # Installazione agent interattiva
│   │   ├── checkmk-tuning-interactive*.sh  # Tuning CheckMK
│   │   ├── checkmk-optimize.sh        # Ottimizzazione CheckMK
│   │   ├── scan-nmap*.sh              # Scanner rete interattivo
│   │   ├── auto-git-sync.sh           #  Sync automatico repository
│   │   ├── checkmk_rclone_space_dyn.sh #  Backup cloud con rclone
│   │   ├── setup-auto-upgrade-checkmk.sh #  Setup auto-upgrade CheckMK
│   │   ├── upgrade-checkmk.sh         # Upgrade CheckMK
│   │   └── increase-swap.sh           # Gestione swap
│   ├── (remote rimosso)           # Launcher remoti dismessi
│   ├── auto-git-sync.service      # Systemd service per sync
│   └── install-auto-git-sync.sh   # Installazione sync automatico
│
├── install/                       # Installazione e bootstrap
│   ├── bootstrap-installer.sh     # Bootstrap installer CheckMK
│   ├── make-bootstrap-iso.sh      # Creazione ISO bootstrap
│   ├── install-cmk8/              # Guide installazione CheckMK 8
│   ├── checkmk-installer/         # Installer CheckMK personalizzato
│   └── Agent-FRPC/                # Installer Agent + FRPC combinato
│
├── fix/                           # Script fix e correzioni
│   ├── full/                      # Script fix completi
│   └── (remote rimosso)           # Solo script full
│
├── Ydea-Toolkit/                  #  Integrazione Ydea Ticketing
│   ├── doc/                       # Documentazione completa
│   ├── full/                      # Script completi integrazione
│   │   ├── ydea-toolkit.sh        #  Toolkit principale
│   │   ├── ydea-monitoring-integration.sh  # Integrazione CheckMK
│   │   ├── create-monitoring-ticket.sh     # Creazione ticket
│   │   ├── ydea-discover-sla-ids.sh        # Discovery SLA
│   │   ├── install-ydea-checkmk-integration.sh  # Installazione
│   │   └── test-*.sh              # Script test
│   ├── (remote rimosso)           # Solo script full
│   ├── config/                    # File configurazione
│   ├── README.md                  # Guida principale
│   └── README-*.md                # Guide specifiche
│
├── nethesis-brand/                #  Asset branding Nethesis per CheckMK
│   ├── checkmk_logo.svg           # Logo login (290px, bordo verde)
│   ├── icon_checkmk_logo.svg      # Icona N sidebar 40px
│   ├── icon_checkmk_logo_min.svg  # Icona N sidebar 28px
│   ├── nethesis_color.png         # Logo originale colore (sorgente)
│   ├── nethesis_n_icon.png        # Favicon N originale (sorgente)
│   └── theme.css                  # CSS override colori Nethesis
│
├── deploy-nethesis-brand.sh       #  Deploy branding su tutti i server CheckMK
│
├── tools/                         # Utility Python
│   ├── fix_bash_syntax_corruption.py  # Fix corruzione sintassi
│   └── fix_mojibake_cp437.py          # Fix encoding CP437
│
├── test script/                   # Script test e verifica
│
├── *.ps1                          # Script automazione PowerShell
│   ├── backup-*.ps1               # Sistema backup automatico
│   ├── setup-*.ps1                # Setup automazione e configurazione
│   └── quick-*.ps1                # Utility quick-access
│
└── Root Scripts/                  # Script bash root directory
    ├── launcher.sh                # Launcher principale
    ├── deploy-from-repo.sh        # Deploy da repository
    ├── diagnose-auto-git-sync.sh  # Diagnostica sync automatico
    ├── debug-monitor.sh           # Debug monitoring
    ├── update-deployed-launchers.sh  # Aggiorna launcher deployati
    ├── distributed-monitoring-setup.sh  # Setup monitoring distribuito
    └── .copilot-context.md        #  Context file per AI (auto-sync, preferenze)

```text

>  **Nota importante**: Il file `.copilot-context.md` contiene informazioni critiche sull'architettura del sistema auto-sync e preferenze per assistenti AI. Leggerlo prima di modificare file o eseguire comandi.

---

##  Script di Check

### Windows

**Directory**: `script-check-windows/`

####  Ransomware Detection

Script avanzato per rilevamento tempestivo attività ransomware su share di rete.

**Features**:
-  Detection multi-pattern (estensioni sospette, ransom note, velocità I/O)
-  Canary files monitoring
-  Timeout protection per share lente/bloccate
-  Auto-update da GitHub
-  Metriche dettagliate per share

**Files**:
- `check_ransomware_activity.ps1` - Script principale (737 righe)
- `rcheck_ransomware_activity.ps1` - Remote wrapper con auto-update
- `ransomware_config.json` - Configurazione
- `test_ransomware_detection.ps1` - Test suite completo

**Documentazione**: [README-Ransomware-Detection.md](script-check-windows/README-Ransomware-Detection.md)

**Quick Start**:

```powershell
# Deploy su Windows Server
Copy-Item check_ransomware_activity.ps1, ransomware_config.json `
    -Destination "C:\ProgramData\checkmk\agent\local\"

# Configurazione
notepad C:\ProgramData\checkmk\agent\local\ransomware_config.json

# Test manuale
.\check_ransomware_activity.ps1 -VerboseLog

```text

---

### NethServer 7

**Directory**: `script-check-ns7/`

Monitoraggio completo per NethServer 7 (CentOS 7 based).

**Struttura**:
- `full/` - Script completi standalone
- `doc/` - Documentazione specifica

#### Script Disponibili

| Script | Descrizione | Metriche |
|--------|-------------|----------|
| `check_cockpit_sessions.sh` | Sessioni attive Cockpit | Sessioni, warning/crit |
| `check_dovecot_sessions.sh` | Sessioni IMAP/POP3 | Connessioni attive |
| `check_dovecot_maxuserconn.sh` | Max conn per utente | Peak connections |
| `check_dovecot_status.sh` | Stato servizio Dovecot | Service status |
| `check_dovecot_vsz.sh` | Memoria VSZ Dovecot | MB utilizzati |
| `check_postfix_status.sh` | Stato servizio Postfix | Service status |
| `check_postfix_process.sh` | Processi Postfix attivi | Process count |
| `check_postfix_queue.sh` | Coda email | Messaggi in coda |
| `check_webtop_status.sh` | Stato Webtop5 | Service status |
| `check_webtop_maxmemory.sh` | Memoria massima Webtop | MB allocated |
| `check_webtop_https.sh` | Stato HTTPS Webtop | Certificate expiry |
| `check_ssh_root_logins.sh` | Login root SSH | Failed attempts |
| `check_ssh_root_sessions.sh` | Sessioni root attive | Active sessions |
| `check_ssh_failures.sh` | Tentativi SSH falliti | Failed count |
| `check-sos-ns7.sh` | Report sosreport NS7 | Report generation |
| `check-sosid-ns7.sh` | ID caso sosreport | Case tracking |
| `check-pkg-install.sh` | Pacchetti installati | Package count |
| `check_ransomware_ns7.sh` | Rilevamento ransomware NS7 | File sospetti |
| `check_fail2ban_status.sh` | Stato Fail2ban | Service status |
| `check_ssh_all_sessions.sh` | Tutte sessioni SSH | Session count |

**Pattern attuale**: Solo script completi in `full/` (launcher remoti dismessi).

---

### NethServer 8

**Directory**: `script-check-ns8/`

Monitoraggio per NethServer 8 (Podman/Container based).

**Struttura**:
- `full/` - Script completi per monitoraggio container e servizi
- `doc/` - Documentazione

#### Script Disponibili

| Script | Descrizione | Funzionalità |
|--------|-------------|-------------|
| `monitor_podman_events.sh` | Monitor eventi Podman real-time | Container start/stop/die |
| `check_podman_events.sh` | Check eventi Podman | Event detection |
| `check_ns8_containers.sh` | Stato container NS8 | Container health |
| `check_ns8_services.sh` | Stato servizi NS8 | Service monitoring |
| `check_ns8_webtop.sh` | Monitoraggio Webtop NS8 | Webtop status |
| `check_ns8_tomcat8.sh` | Monitoraggio Tomcat8 NS8 | Tomcat status |
| `check-sos.sh` | Generazione report SOS NS8 | Diagnostic report |

**Note**: NethServer 8 usa architettura container-based, gli script sono ottimizzati per Podman.

---

### Ubuntu/Linux

**Directory**: `script-check-ubuntu/`

Script check generici per distribuzioni Ubuntu/Debian.

**Struttura**:
- `full/` - Script completi per Ubuntu/Debian
- `doc/` - Documentazione
- `deploy-ssh-checks.sh` - Deploy automatico check SSH

#### Script Disponibili

| Script | Descrizione | Metriche |
|--------|-------------|----------|
| `check_ssh_root_logins.sh` | Login root SSH | Failed attempts |
| `check_ssh_root_sessions.sh` | Sessioni root attive | Active sessions |
| `check_ssh_all_sessions.sh` | Tutte le sessioni SSH | Total sessions |
| `check_fail2ban_status.sh` | Stato Fail2ban | Ban count, status |
| `check_disk_space.sh` | Spazio disco | Disk usage |
| `mk_logwatch` | Monitoraggio log | Log parsing |

**Deploy Quick Start**:

```bash
# Deploy automatico check SSH
./deploy-ssh-checks.sh

```text

---

### NethSecurity 8

**Directory**: `script-check-nsec8/`

Monitoraggio per NethSecurity 8 (Firewall NethServer 8 based).

**Struttura**:
- `full/` - Script completi per NethSecurity
- `doc/` - Documentazione specifica

**Note**: NethSecurity 8 è la distribuzione firewall basata su NethServer 8, include monitoraggio specifico per servizi firewall.

---

### Proxmox

**Directory**: `script-check-proxmox/`

Monitoraggio Proxmox Virtual Environment tramite API.

#### Script Disponibili

| Script | Descrizione | API Endpoint |
|--------|-------------|--------------|
| `check-proxmox-vm-status.sh` | Stato VM (running/stopped) | `/api2/json/nodes/*/qemu` |
| `check-proxmox-vm-snapshot-status.sh` | Stato snapshot VM | `/api2/json/nodes/*/qemu/*/snapshot` |
| `proxmox_vm_api.sh` | Test connessione API Proxmox | API authentication |
| `proxmox_vm_disks.sh` | Monitoraggio dischi VM | Disk usage |
| `proxmox_vm_monitor.sh` | Monitor generale VM | CPU, RAM, Disk |

**Esecuzione**: usare direttamente gli script in `full/`.

**Requisiti**:
- Token API Proxmox configurato
- `curl` e `jq` installati
- Permessi lettura su API Proxmox

---

##  Script di Notifica

**Directory**: `script-notify-checkmk/`

Sistema avanzato di notifiche CheckMK con supporto FRP (Fast Reverse Proxy) e integrazione Ydea ticketing.

**Struttura**:
- `full/` - Script notifica completi
- `doc/` - Documentazione e guide test

### Features Principali

####  Real IP Detection

Estrae IP reale anche dietro proxy FRP per notifiche accurate:

```python
# Detection automatica scenario
if 'NOTIFY_HOSTLABEL_real_ip' in os.environ:
    real_ip = os.environ['NOTIFY_HOSTLABEL_real_ip']
    # Usa real_ip invece di HOSTADDRESS

```text

####  Grafici Integrati

Email HTML con grafici performance inclusi automaticamente:
- CPU usage
- Memory utilization  
- Disk I/O
- Network traffic

####  Multi-Channel

- **Email**: `mail_realip*` - Varie versioni (HTML, hybrid, safe)
- **Telegram**: `telegram_realip` - Bot Telegram con formattazione

### Script Disponibili

| Script | Descrizione | Features |
|--------|-------------|----------|
| `mail_realip_hybrid` | Email HTML + Real IP + Grafici |  Consigliato |
| `mail_realip_hybrid_v24` | Versione CheckMK 2.4+ | Latest version |
| `mail_realip_hybrid_safe` | Versione con fallback | Extra safety |
| `mail_realip` | Email base Real IP | Minimal |
| `mail_realip_html` | Email HTML Real IP | No graphs |
| `telegram_realip` | Telegram Real IP | Bot integration |
| `telegram_selfmon` | Telegram self-monitoring | Self-check |
| `ydea_ag` | Integrazione Ydea AG | Ticketing AG |
| `ydea_la` | Integrazione Ydea LA | Ticketing LA |
| `mail_ydea_down` | Email notifica host down Ydea | Host down |
| `dump_env` | Dump environment variables |  Debug |

### Deployment

```bash
# 1. Backup configurazione esistente
./backup_and_deploy.sh --backup-only

# 2. Test dry-run
./backup_and_deploy.sh --dry-run

# 3. Deploy effettivo
./backup_and_deploy.sh

# 4. Verifica
su - $(cat /etc/omd/site)
ls -la local/share/check_mk/notifications/

```text

**Documentazione**: [TESTING_GUIDE.md](script-notify-checkmk/TESTING_GUIDE.md)

---

##  Tool di Deploy

**Directory**: `script-tools/`

Utility per deployment automatizzato CheckMK Agent, script e gestione infrastruttura.

**Struttura**:
- `full/` - Tool completi per deployment e gestione
- `remote/` - Remote wrapper
- `doc/` - Documentazione tool
- `auto-git-sync.service` - Systemd service per sync automatico
- `install-auto-git-sync.sh` - Installazione sync automatico repository

###  Deploy Monitoring Scripts

Script interattivo per deployment selettivo di monitoring scripts su host remoti.

**Features**:
-  Auto-detect sistema operativo (NS7/NS8/Proxmox/Ubuntu)
-  Menu interattivo con lista script disponibili
-  Deploy selettivo (singoli script o tutti)
-  Copia automatica in `/usr/lib/check_mk_agent/local/`
-  Usa repository locale `/opt/checkmk-tools`

**Installazione one-liner**:

```bash
# Download ed esecuzione diretta
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/deploy/deploy-monitoring-scripts.sh -o /tmp/deploy.sh && bash /tmp/deploy.sh

```text

**Uso manuale**:

```bash
# Se hai già il repository clonato
cd /opt/checkmk-tools
./script-tools/full/deploy/deploy-monitoring-scripts.sh

```text

**Esempio output**:

```text

========================================
  Deploy Monitoring Scripts
========================================

 Repository trovato: /opt/checkmk-tools
Sistema rilevato: NethServer 7

Script disponibili:
  1) rcheck_cockpit_sessions.sh
  2) rcheck_dovecot_status.sh
  3) rcheck_postfix_queue.sh
  [...]
  
Selezione (numeri separati da spazi, 'a' per tutti, 'q' per uscire): 1 3 5

```text

---

### Smart Deploy Hybrid

Sistema intelligente per deployment multi-host con auto-update.

**Features**:
-  Auto-download da GitHub con cache
-  Fallback su cache in caso di network issue
-  Timeout protection (30s default)
-  Logging dettagliato
-  Validazione sintassi pre-deploy

**Files**:
- `smart-deploy-hybrid.sh` - Deploy intelligente
- `README-Smart-Deploy.md` - Documentazione base
- `README-Smart-Deploy-Enhanced.md` - Funzionalità avanzate

**Esempio**:

```bash
# Deploy script su host remoto
./smart-deploy-hybrid.sh \
    --host ns7-server.local \
    --scripts check_cockpit_sessions,check_dovecot_status \
    --github-repo Coverup20/checkmk-tools

```text

### Deploy Agent CheckMK

Installazione e configurazione CheckMK Agent.

| Script | Descrizione |
|--------|-------------|
| `deploy-plain-agent.sh` | Deploy agent singolo host |
| `deploy-plain-agent-multi.sh` | Deploy multi-host da lista |
| `install-and-deploy-plain-agent.sh` | Install + deploy completo |

### Installazione FRP Client

| Script | Descrizione |
|--------|-------------|
| `install-frpc.sh` | Installazione FRP client base |
| `install-frpc2.sh` | Installazione FRP v2 |
| `install-frpc-dryrun.sh` | Test senza modifiche |

### Ottimizzazione e Tuning CheckMK

| Script | Descrizione |
|--------|-------------|
| `checkmk-tuning-interactive-v5.sh` | Tuning interattivo CheckMK (latest) |
| `checkmk-tuning-interactive*.sh` | Versioni precedenti tuning |
| `checkmk-optimize.sh` | Ottimizzazione automatica CheckMK |
| `install-checkmk-log-optimizer.sh` | Ottimizzatore log CheckMK |
| `upgrade-checkmk.sh` | Upgrade CheckMK automatizzato |

### Gestione Agent

| Script | Descrizione |
|--------|-------------|
| `install-agent-interactive.sh` | Installazione agent interattiva |
| `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh` |  **Installer ROCKSOLID** per NethSecurity 8 |
| `rocksolid-startup-check.sh` | Autocheck boot per protezione post-upgrade |
| `update-all-scripts.sh` | Aggiornamento script da repository |
| `update-scripts-from-repo.sh` | Update specifici script |

####  ROCKSOLID Mode - Installazione Resistente agli Upgrade

**Sistema avanzato di protezione per NethSecurity 8** che garantisce la sopravvivenza di CheckMK Agent e FRP Client durante i major upgrade di sistema.

**Caratteristiche**:
-  **Protezione Totale**: Aggiunge file critici a `/etc/sysupgrade.conf` (sopravvivono agli upgrade)
-  **Backup Binari**: Backup automatico di `tar`, `ar`, `gzip` (protegge da corruzione durante upgrade)
-  **Auto-Recovery**: Script di avvio che verifica e ripristina servizi automaticamente
-  **FRP Integration**: Supporto FRP v0.x e v1.x con rilevamento configurazione esistente
-  **Marker System**: File marker per rilevamento installazione FRP persistente
-  **Post-Upgrade Script**: Script automatico di verifica e ripristino post-upgrade

**Validato su**:
- NethSecurity 8.7.1 (OpenWrt 23.05.0)
- FRP Client v0.64.0 e legacy v0.x
- CheckMK Agent 2.4.0p20

**Installazione**:

```bash
# Download ed esecuzione diretta
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh | bash

# Opzionale: modalità interattiva
bash install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh

```text

**Post-Upgrade** (dopo major upgrade manuale):

```bash
/etc/checkmk-post-upgrade.sh

```text

**Documentazione completa**: [install-checkmk-agent-debtools-frp-nsec8c-rocksolid.md](script-tools/doc/install-checkmk-agent-debtools-frp-nsec8c-rocksolid.md)

### Automazione Repository

| Script | Descrizione |
|--------|-------------|
| `auto-git-sync.sh` | Sync automatico repository |
| `install-auto-git-sync.sh` | Installazione sync come servizio |

### Network Scanner

| Script | Descrizione |
|--------|-------------|
| `scan-nmap-interattivo-verbose.sh` | Scanner Nmap interattivo |
| `scan-nmap-interattivo-verbose-multi-options.sh` | Scanner con opzioni avanzate |

### Sistema e Utility

| Script | Descrizione |
|--------|-------------|
| `increase-swap.sh` | Gestione e aumento swap |
| `setup-auto-updates.sh` | Setup aggiornamenti automatici |
| `setup-auto-upgrade-checkmk.sh` | Setup upgrade automatico CheckMK |
| `smart-wrapper-template.sh` | Template per wrapper intelligenti |
| `smart-wrapper-example.sh` | Esempio wrapper con cache |

---

##  Ydea Toolkit - Integrazione Ticketing

**Directory**: `Ydea-Toolkit/`

Integrazione completa tra CheckMK e sistema di ticketing Ydea per creazione automatica ticket di monitoraggio.

**Struttura**:
- `full/` - Script completi integrazione
- `remote/` - Remote wrapper
- `config/` - File configurazione
- `doc/` - Documentazione dettagliata

### Features Principali

####  Funzionalità Core

-  **Creazione ticket automatica** da eventi CheckMK
-  **Discovery SLA** automatico da contratti
-  **Monitoring ticket** aperti e in corso
-  **Health monitor** stato integrazione
-  **Toolkit completo** per gestione API Ydea

### Script Disponibili

#### Integrazione CheckMK

| Script | Descrizione |
|--------|-------------|
| `ydea-monitoring-integration.sh` |  Integrazione completa CheckMK-Ydea |
| `install-ydea-checkmk-integration.sh` | Installazione automatica integrazione |
| `ydea-health-monitor.sh` | Monitor stato integrazione |
| `ydea-ticket-monitor.sh` | Monitor ticket aperti |

#### Gestione Ticket

| Script | Descrizione |
|--------|-------------|
| `create-monitoring-ticket.sh` | Creazione ticket da eventi |
| `create-ticket-ita.sh` | Creazione ticket in italiano |
| `get-ticket-by-id.sh` | Recupera ticket per ID |
| `get-full-ticket.sh` | Dettagli completi ticket |
| `search-ticket-by-code.sh` | Ricerca ticket per codice |

#### Discovery e Analisi

| Script | Descrizione |
|--------|-------------|
| `ydea-discover-sla-ids.sh` | Discovery automatico SLA da contratti |
| `search-sla-in-contracts.sh` | Ricerca SLA nei contratti |
| `analyze-custom-attributes.sh` | Analisi attributi custom |
| `analyze-ticket-data.sh` | Analisi dati ticket |

#### API e Testing

| Script | Descrizione |
|--------|-------------|
| `ydea-toolkit.sh` |  Toolkit principale API Ydea |
| `explore-ydea-api.sh` | Esplora API Ydea |
| `explore-anagrafica.sh` | Esplora anagrafica clienti |
| `quick-test-ydea-api.sh` | Test rapido API |
| `test-ydea-integration.sh` | Test integrazione completa |
| `test-ticket-with-contract.sh` | Test ticket con contratto |

### Quick Start

```bash
# 1. Installazione integrazione
cd Ydea-Toolkit/full
./install-ydea-checkmk-integration.sh

# 2. Configurazione (modifica con le tue credenziali)
cp .env.example .env
vim .env

# 3. Discovery SLA automatico
./ydea-discover-sla-ids.sh

# 4. Test creazione ticket
./create-monitoring-ticket.sh \
    --host "server01" \
    --service "CPU Load" \
    --state "CRITICAL" \
    --output "CPU al 95%"

# 5. Monitor health integrazione
./ydea-health-monitor.sh

```text

### Documentazione

-  **[README.md](Ydea-Toolkit/README.md)** - Guida principale
-  **[README-CHECKMK-INTEGRATION.md](Ydea-Toolkit/doc/README-CHECKMK-INTEGRATION.md)** - Guida integrazione completa CheckMK-Ydea

>  **Nota**: Documentazione consolidata da 17 a 2 file essenziali per facilità navigazione (Febbraio 2026)

### Configurazione

**File richiesti**:
- `.env` - Credenziali API Ydea e configurazione SLA
- `premium-mon-config.json` - Mapping Premium_Mon (contratto + SLA)

**Variabili ambiente**:

```bash
YDEA_ID="il_tuo_id_azienda"
YDEA_API_KEY="la_tua_api_key"
YDEA_CONTRATTO_ID="171734"  # Contratto che applica SLA automaticamente

```text

**SLA Contract-Based**: Dal Febbraio 2026, il sistema usa `contrattoId` per applicare automaticamente SLA Premium_Mon. Non serve più specificare esplicitamente `serviceLevelAgreement` - il contratto gestisce tutto.

---

##  Directory Utility

### Install - Installazione e Bootstrap

**Directory**: `install/`

Script per installazione e bootstrap CheckMK e componenti.

| Script/Directory | Descrizione |
|------------------|-------------|
| `bootstrap-installer.sh` | Bootstrap installer CheckMK |
| `make-bootstrap-iso.sh` | Creazione ISO bootstrap |
| `install-cmk8/` | Guide installazione CheckMK 8 |
| `checkmk-installer/` | Installer personalizzato CheckMK |
| `Agent-FRPC/` | Installer combinato Agent + FRPC |

### Fix - Correzioni e Riparazioni

**Directory**: `fix/`

Script per correzione problemi comuni.

**Struttura**:
- `full/` - Script fix completi
- `remote/` - Remote wrapper

### Tools - Utility Python

**Directory**: `tools/`

Utility Python per fix avanzati.

| Script | Descrizione |
|--------|-------------|
| `fix_bash_syntax_corruption.py` | Fix corruzione sintassi bash |
| `fix_mojibake_cp437.py` | Fix encoding CP437 (mojibake) |

### Root Scripts

**Directory root**

Script bash utility nella root del repository.

| Script | Descrizione |
|--------|-------------|
| `launcher.sh` | Launcher principale script |
| `launcher_remote_script.sh` | Launcher per script remoti |
| `deploy-from-repo.sh` | Deploy da repository |
| `rdeploy-from-repo.sh` | Remote deploy |
| `diagnose-auto-git-sync.sh` | Diagnostica sync automatico |
| `rdiagnose-auto-git-sync.sh` | Remote diagnostica |
| `debug-monitor.sh` | Debug monitoring |
| `update-deployed-launchers.sh` | Aggiorna launcher deployati |
| `update-remote-urls.ps1` | Aggiorna URL remoti |
| `distributed-monitoring-setup.sh` | Setup monitoring distribuito |
| `check-distributed-monitoring-prerequisites.sh` | Verifica prerequisiti |
| `update-crontab-frequency.sh` | Aggiorna frequenza crontab |
| `test-log-events.sh` | Test eventi log |

---

##  Automazione e Backup

### Script PowerShell Root Directory

Sistema automatizzato per backup e sync del repository.

#### Backup Automatico

| Script | Descrizione | Frequenza |
|--------|-------------|-----------|
| `quick-backup.ps1` | Backup rapido modifiche | Hourly |
| `backup-sync.ps1` | Backup + sync remoti | Daily |
| `backup-sync-complete.ps1` | Backup completo + multi-remote | Weekly |
| `backup-existing-config.ps1` | Backup configurazioni | On-demand |

#### Setup Automazione

| Script | Descrizione |
|--------|-------------|
| `setup-automation.ps1` | Wizard setup task schedulati |
| `setup-backup-automation.ps1` | Setup backup automatico |
| `create_backup_task.ps1` | Creazione task Windows |
| `check_task.ps1` | Verifica task esistenti |

#### Configurazione Git

| Script | Descrizione |
|--------|-------------|
| `setup-additional-remotes.ps1` | Aggiungi remote repository |
| `fix-gitlab-credentials.ps1` | Fix credenziali GitLab |
| `git-credential-fix.ps1` | Fix credenziali Git generiche |

**Quick Start Automazione**:

```powershell
# 1. Setup backup automatico
.\setup-automation.ps1

# Scegli opzione:
# 1. Backup ogni ora (quick)
# 2. Backup giornaliero mattina (9:00)
# 3. Backup giornaliero sera (22:00)
# 4. Backup settimanale (Lunedì 8:00)

# 2. Verifica task creato
.\check_task.ps1

# 3. Test manuale
.\quick-backup.ps1

```text

---

##  Installazione

### Requisiti Base

#### Windows

- PowerShell 5.1 o superiore
- CheckMK Agent Windows installato
- .NET Framework 4.5+

#### Linux

- Bash 4.0+
- CheckMK Agent installato
- `curl`, `jq` (per alcuni script)
- Python 3 (per script notifica)

### Installazione Script Check

#### Windows

```powershell
# 1. Clone repository
git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools

# 2. Deploy script desiderato
$scriptPath = "script-check-windows\nopolling\ransomware_detection"
Copy-Item "$scriptPath\rcheck_ransomware_activity.ps1" `
    -Destination "C:\ProgramData\checkmk\agent\local\"

Copy-Item "$scriptPath\ransomware_config.json" `
    -Destination "C:\ProgramData\checkmk\agent\local\"

# 3. Test
& "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe" test | 
    Select-String -Pattern "Ransomware"

```text

#### Linux (NethServer / Ubuntu)

```bash
# 1. Clone repository
git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools

# 2. Deploy con smart-deploy
cd script-tools
./smart-deploy-hybrid.sh \
    --local \
    --script ../script-check-ns7/nopolling/check_cockpit_sessions.sh

# Oppure copia manuale
sudo cp script-check-ns7/nopolling/rcheck_cockpit_sessions.sh \
    /usr/lib/check_mk_agent/local/

sudo chmod +x /usr/lib/check_mk_agent/local/rcheck_cockpit_sessions.sh

# 3. Test
check_mk_agent | grep -A5 "cockpit"

```text

### Installazione Script Notifica

```bash
# Su server CheckMK (come root)
cd /tmp
git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools/script-notify-checkmk

# Backup + Deploy automatico
./backup_and_deploy.sh

# Oppure manuale
omd stop
cp mail_realip_hybrid /omd/sites/SITENAME/local/share/check_mk/notifications/
chmod +x /omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_hybrid
omd start

# Configura in Web GUI
# Setup -> Notifications -> New Rule -> Notification Method: mail_realip_hybrid

```text

---

##  Documentazione

### README Specifici

Ogni categoria ha la sua documentazione dettagliata:

-  **Windows**: [script-check-windows/README.md](script-check-windows/README.md)
  -  **Ransomware**: [README-Ransomware-Detection.md](script-check-windows/README-Ransomware-Detection.md)

-  **Notifiche**: [script-notify-checkmk/TESTING_GUIDE.md](script-notify-checkmk/TESTING_GUIDE.md)

-  **Deploy Tools**: 
  - [script-tools/README-Smart-Deploy.md](script-tools/README-Smart-Deploy.md)
  - [script-tools/README-Smart-Deploy-Enhanced.md](script-tools/README-Smart-Deploy-Enhanced.md)

-  **Soluzioni Complete**: [SOLUZIONE-COMPLETA.md](SOLUZIONE-COMPLETA.md)

### Guide Installazione

-  **CheckMK 8**: [script-tools/full/installation/install-cmk8/](script-tools/full/installation/install-cmk8/)

### Configurazioni

-  **Host Labels**: [checkmk-host-labels-config.md](checkmk-host-labels-config.md)

---

##  Testing

### Test Windows

```powershell
# Test singolo script
cd script-check-windows\nopolling\ransomware_detection
.\test_ransomware_detection.ps1 -TestScenario All

# Test manuale con debug
.\check_ransomware_activity.ps1 -VerboseLog

# Test via CheckMK Agent
& "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe" test

```text

### Test Linux

```bash
# Test singolo script
/usr/lib/check_mk_agent/local/check_cockpit_sessions

# Test output CheckMK
check_mk_agent | head -50

# Test con debug
bash -x /usr/lib/check_mk_agent/local/rcheck_cockpit_sessions.sh

```text

### Test Notifiche

```bash
# Test detection FRP
cd script-notify-checkmk
python3 -c "
import os
os.environ['NOTIFY_HOSTLABEL_real_ip'] = '192.168.1.100'
os.environ['NOTIFY_HOSTADDRESS'] = '127.0.0.1:5000'
exec(open('mail_realip_hybrid').read())
"

```text

---

##  Contributi

### Come Contribuire

1. **Fork** il repository
2. **Crea branch** per la tua feature: `git checkout -b feature/AmazingFeature`
3. **Commit** modifiche: `git commit -m 'Add AmazingFeature'`
4. **Push** al branch: `git push origin feature/AmazingFeature`
5. **Open Pull Request**

### Standard Codice

#### PowerShell

- Usa `CmdletBinding()` per script avanzati
- Parameter validation con `[Parameter()]`
- Help comments con `.SYNOPSIS`, `.DESCRIPTION`, `.EXAMPLE`
- Error handling con `try/catch`
- Output CheckMK format: `<<<local>>>` + status lines

#### Bash

- Usa `#!/bin/bash` shebang
- Set `-euo pipefail` per error handling
- Funzioni con naming chiaro
- Commenti per logica complessa
- Output CheckMK format standard

#### Convenzioni Naming

**Files**:
- Check scripts: `check_<name>.{ps1|sh}`
- Remote wrappers: `rcheck_<name>.{ps1|sh}`
- Test scripts: `test_<name>.{ps1|sh}`
- Config files: `<name>_config.json`

**CheckMK Services**:
- Format: `<Category>_<Name>`
- Esempi: `Ransomware_Detection`, `Cockpit_Sessions`

**Metriche**:
- Snake case: `suspicious_files=10`
- Unit suffixes: `memory_mb=512`, `time_seconds=30`

---

##  Statistiche Repository

### Script Count

| Categoria | Script Full | Remote Wrappers | Total |
|-----------|-------------|-----------------|-------|
| Windows | 2+ | 2+ | 4+ |
| NethServer 7 | 20 | 20+ | 40+ |
| NethServer 8 | 7 | 7+ | 14+ |
| NethSecurity 8 | 3+ | 3+ | 6+ |
| Ubuntu/Linux | 6 | 6+ | 12+ |
| Proxmox | 5 | 5+ | 10+ |
| **Totale Check** | **43+** | **43+** | **86+** |

| Categoria | Scripts | Descrizione |
|-----------|---------|-------------|
| Notifiche | 11+ | Email + Telegram + Ydea |
| Deploy Tools | 28+ | Smart deploy, agent install, tuning |
| Ydea Toolkit | 30+ | Integrazione ticketing completa |
| Install/Bootstrap | 5+ | Installer e bootstrap |
| Fix/Tools | 3+ | Utility correzione |
| Root Scripts | 12+ | Launcher, deploy, diagnostica |
| Test | 10+ | Test suite e validazione |

### Lingue

-  **PowerShell**: ~25% (Windows scripts, automazione)
-  **Bash**: ~65% (Linux scripts, deploy, tools)
-  **Python**: ~10% (Notifiche CheckMK, utility)

### Copertura Piattaforme

-  **Windows Server** (PowerShell scripts)
-  **NethServer 7** (CentOS 7 based)
-  **NethServer 8** (Container/Podman based)
-  **NethSecurity 8** (Firewall)
-  **Ubuntu/Debian** (Script generici Linux)
-  **Proxmox VE** (Virtualizzazione)
-  **CheckMK** (Notifiche, tuning, deploy)
-  **Ydea** (Sistema ticketing)

---

##  Troubleshooting

### Windows

**Problema**: Script non appare in CheckMK

```powershell
# Verifica permessi
Get-Acl "C:\ProgramData\checkmk\agent\local\*.ps1"

# Verifica execution policy
Get-ExecutionPolicy

# Test manuale
& "C:\Program Files (x86)\checkmk\service\check_mk_agent.exe" test

```text

**Problema**: Errore timeout share di rete

```powershell
# Check ransomware_config.json
# Aumenta timeout se necessario (default 30s)

```text

### Linux

**Problema**: Script non eseguibile

```bash
sudo chmod +x /usr/lib/check_mk_agent/local/*.sh

```text

**Problema**: Cache script non aggiorna

```bash
# Rimuovi cache manuale
rm -f /var/cache/checkmk-scripts/*
rm -f /tmp/*_cache.sh

# Forza re-download
/usr/lib/check_mk_agent/local/rcheck_script.sh

```text

**Problema**: Script notifica non funziona

```bash
# Verifica permessi
ls -la /omd/sites/SITENAME/local/share/check_mk/notifications/

# Test manuale (come site user)
su - SITENAME
cd local/share/check_mk/notifications
python3 -c "exec(open('./mail_realip_hybrid').read())"

```text

---

##  Sicurezza

### Best Practices

-  Non committare credenziali in config files
-  Usa variabili ambiente per token/password
-  Limita permessi file (600 per config sensibili)
-  Valida input utente
-  Usa HTTPS per comunicazioni API
-  Timeout per operazioni di rete
-  Log eventi di sicurezza rilevanti

### Credenziali

File `.gitignore` include:

```text

*.json
*.config
*.key
*.token
*_password.txt

```text

Usare sempre:

```bash
# Linux
export API_TOKEN="your-token"

# Windows
$env:API_TOKEN = "your-token"

```text

---

## � Sistema Auto-Sync

Il repository utilizza un sistema di **sincronizzazione automatica** sui server CheckMK:

### Architettura

```text

GitHub (Coverup20/checkmk-tools)
    ↓ [auto-git-sync.service - ogni 5-15 minuti]
/opt/checkmk-tools/ (sui server)
    ↓ [esecuzione script]
Produzione

```text

### Workflow Modifiche

1. **Modifica locale** (Windows/Workstation)
2. **Commit + Push** a GitHub
3. **Attendi auto-sync** (5-15 minuti) o forzalo: `sudo bash /opt/checkmk-tools/script-tools/full/sync_update/auto-git-sync.sh`
4. **Script aggiornati** in `/opt/checkmk-tools/`
5. **Test in produzione**

 **Importante**: Non modificare mai direttamente file in `/opt/checkmk-tools/` - verranno sovrascritti dal sync!

### Verifica Sync

```bash
# Stato servizio
sudo systemctl status auto-git-sync.service

# Log recenti
sudo journalctl -u auto-git-sync.service -n 50

# Forzare sync manuale
sudo bash /opt/checkmk-tools/script-tools/full/sync_update/auto-git-sync.sh

```text

**Documentazione completa**: [.copilot-context.md](.copilot-context.md)

---

##  Backup Cloud CheckMK

Script completo per backup automatizzato CheckMK su cloud storage con rclone.

### Features

-  **Multi-Cloud**: Supporto S3, DigitalOcean Spaces, Google Drive, Dropbox, ecc.
-  **Auto-Install**: Installazione automatica rclone e dipendenze
-  **Retention Automatica**: Gestione locale e remota con giorni configurabili
-  **Rename Intelligente**: Timestamp automatico per backup `-complete`
-  **Monitoring Timer**: Systemd timer (ogni 1 minuto) per check automatici
-  **S3-Compatible**: Ottimizzato per S3/Spaces (no mkdir, path auto-create)

### Quick Start

```bash
# Setup interattivo
cd /opt/checkmk-tools/script-tools/full
./checkmk_rclone_space_dyn.sh setup

# Configurazione:
# - Site CheckMK: monitoring
# - Remote rclone: do:testmonbck (esempio DigitalOcean)
# - Retention locale: 30 giorni
# - Retention remota: 90 giorni

# Test manuale
./checkmk_rclone_space_dyn.sh run monitoring

# Check status
systemctl status checkmk-cloud-backup-push@monitoring.timer
journalctl -u checkmk-cloud-backup-push@monitoring.service -n 50

```text

### Configurazione rclone

Il script richiede rclone configurato. Esempio per DigitalOcean Spaces:

```bash
rclone config
# Scegli: s3
# Provider: DigitalOcean Spaces
# Endpoint: ams3.digitaloceanspaces.com
# Remote name: do

```text

**File**: `script-tools/full/backup_restore/checkmk_rclone_space_dyn.sh` (794 righe)

---

##  Auto-Upgrade CheckMK

Wizard interattivo per configurare upgrade automatico CheckMK via crontab.

### Features

-  **Always Latest**: Scarica sempre ultima versione upgrade script da GitHub
-  **Compatibilità Universale**: Supporto bash 3.2+ (download-to-temp)
-  **Wizard Interattivo**: Configurazione step-by-step guidata
-  **Crontab Safe**: Validazione e backup crontab automatico
-  **Multi-Site**: Supporto upgrade singolo site o tutti

### Quick Start

```bash
# Setup wizard
cd /opt/checkmk-tools/script-tools/full
./setup-auto-upgrade-checkmk.sh

# Seguire wizard:
# 1. Scegli site (o "tutti")
# 2. Conferma versione CheckMK
# 3. Imposta orario (es: 03:00)
# 4. Scegli frequenza (giornaliero/settimanale/mensile)
# 5. Conferma configurazione

# Verifica crontab
crontab -l

```text

**File**: `script-tools/full/upgrade_maintenance/setup-auto-upgrade-checkmk.sh` (270 righe)

---

## � Supporto

### Issue Reporting

Apri issue su GitHub con:
-  Sistema operativo e versione
-  Versione CheckMK
-  Script coinvolto
-  Messaggio errore completo
-  Log di debug (se disponibili)

### Community

-  Discussions GitHub
-  Email: coverup20@github.com

---

##  License

MIT License - Vedi [LICENSE](LICENSE) per dettagli.

---

##  Credits

Sviluppato con  per la community CheckMK.

### Autori Principali

- **Marzio** (@Coverup20) - Repository owner e maintainer

### Contributori

Grazie a tutti i contributori che hanno aiutato a migliorare questa collezione!

### Riconoscimenti

- [CheckMK](https://checkmk.com/) - Monitoring solution
- [NethServer](https://www.nethserver.org/) - Server platform
- CheckMK Community per patterns e best practices

---

##  Roadmap

###  Completato (v2.0)

- [x] **Ydea Toolkit**: Integrazione completa ticketing
- [x] **NethSecurity 8**: Monitoraggio firewall
- [x] **Ubuntu/Linux**: Script completi SSH, Fail2ban, Disk
- [x] **NS8 Enhanced**: Monitoraggio container, Webtop, Tomcat
- [x] **Deploy Tools**: Tuning interattivo, ottimizzazione
- [x] **Automazione**: Git sync automatico

### In Sviluppo

- [ ] **Script Windows**:
  - [ ] check_windows_updates.ps1
  - [ ] check_iis_sites.ps1
  - [ ] check_active_directory.ps1
  - [ ] check_windows_services_extended.ps1

- [ ] **Script Linux**:
  - [ ] check_lvm_snapshots.sh
  - [ ] check_systemd_failed.sh
  - [ ] check_cert_expiry.sh
  - [ ] check_docker_compose.sh

- [ ] **Notifiche**:
  - [ ] Slack integration
  - [ ] Microsoft Teams webhook
  - [ ] Discord notifications
  - [ ] PagerDuty integration

- [ ] **Ydea Enhanced**:
  - [ ] Auto-close ticket resolved
  - [ ] SLA tracking automatico
  - [ ] Report mensili automatici

### Pianificato

- [ ] Web dashboard per monitoring
- [ ] Ansible playbooks per deployment
- [ ] Container images per test
- [ ] CI/CD pipeline per validation

---

##  Changelog

### v2.2.0 (Current - Febbraio 2026)

-  **Ydea Toolkit Enhanced**: Sistema SLA contract-based con campo `contrattoId`
  - Applicazione automatica SLA "Premium_Mon" da contratto 171734
  - Eliminato bisogno di specificare esplicitamente `serviceLevelAgreement`
  - Testing completo con 6 ticket validati (tutti con SLA Premium_Mon)
  - Configurazione multi-utente (Alessandro Gaggiano, Lorenzo Angelini)
-  **Documentazione Consolidata**: Ydea-Toolkit da 17 a 2 file essenziali
  - README.md principale (overview e quick start)
  - README-CHECKMK-INTEGRATION.md (guida completa integrazione)
  - Rimossi file ridondanti e frammentati
  - Fix 61 warning markdownlint per qualità codice
-  **ROCKSOLID Mode Production**: Sistema completato e validato
  - Testato su 2 host production (nsec8-stable, laboratorio)
  - Dynamic package download da repository OpenWrt
  - Auto-recovery post major-upgrade funzionante
  - Git auto-install se rimosso durante upgrade
  - Zero URL statici/hardcoded negli script

### v2.1.0 (Gennaio 2026)

-  **ROCKSOLID Mode**: Sistema protezione completo per NethSecurity 8 agent CheckMK
  - Installazione resistente ai major upgrade con 13 file critici protetti
  - Auto-recovery automatico all'avvio (CheckMK Agent + FRP Client)
  - Supporto FRP v0.x e v1.x con rilevamento config esistente
  - Backup binari critici (`tar`, `ar`, `gzip`) protetti da corruzione
  - Script post-upgrade automatico per verifica e ripristino
  - Fix grep binary file detection su OpenWrt
  - Marker system per FRP detection persistente
  - Validato su NethSecurity 8.7.1 + CheckMK 2.4.0p20

### v2.0.0 (Gennaio 2026)

-  **Backup Cloud**: Sistema completo backup CheckMK su cloud con rclone (S3/Spaces)
-  **Auto-Upgrade CheckMK**: Wizard setup upgrade automatico via crontab
-  **Auto-Sync Enhanced**: Sistema sincronizzazione automatica con .copilot-context.md
-  **S3/Spaces Compatibility**: Fix compatibilità per cloud storage senza mkdir
-  **Unified Search**: Backup selection unificata file/directory per timestamp
-  **Preferenze Lingua**: Repository configurato per italiano 
-  **Ydea Toolkit completo**: Integrazione ticketing con 30+ script
-  **NethSecurity 8**: Supporto completo firewall NS8
-  **Ubuntu/Linux enhanced**: 6 script monitoraggio (SSH, Fail2ban, Disk)
-  **NS8 monitoring esteso**: Container, Webtop, Tomcat, servizi
-  **Deploy tools avanzati**: 28+ tool deployment e ottimizzazione
-  **CheckMK tuning**: Script interattivi ottimizzazione v2-v5
-  **Git sync automatico**: Automazione repository con systemd
-  **Directory riorganizzate**: Struttura full/doc standardizzata (remote dismesso)
-  **Documentazione completa**: 15+ README specifici

### v1.5.0

-  Aggiunto ransomware detection per Windows
-  Ridotto cache timeout wrapper (60s)
-  Migliorato error handling script notifica
-  Aggiornata documentazione completa

### v1.4.0

-  Sistema smart deploy enhanced
-  Pattern CheckMK ufficiali integrati
-  Avvio diretto da script completi in `full/`

### v1.3.0

-  Script notifica con Real IP + Grafici
-  Backup automatico pre-deployment
-  Testing guide completa

### v1.2.0

-  Monitoraggio NethServer 8 (Podman)
-  Script Proxmox VE
-  Deploy tools automatizzati

### v1.1.0

-  Collezione completa script NethServer 7
-  Sistema backup automatico
-  Setup automazione Windows

### v1.0.0

-  Release iniziale
-  Script base per CheckMK

---

** Se trovi utile questo repository, lascia una stella su GitHub!**

** Problemi? Apri una issue!**

** Vuoi contribuire? Le PR sono benvenute!**

---

*Ultimo aggiornamento: Gennaio 2026*
