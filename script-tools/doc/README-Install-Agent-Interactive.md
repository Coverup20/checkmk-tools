#  Install Agent Interactive - Guida Utente
> **Categoria:** Operativo

Script interattivo per l'installazione/disinstallazione automatizzata di CheckMK Agent con opzione FRPC client.

##  Caratteristiche

-  **Installazione guidata** CheckMK Agent (plain TCP 6556)
-  **Supporto multi-distro**: Ubuntu, Debian, Rocky Linux, CentOS, RHEL, AlmaLinux, NethServer Enterprise, **OpenWrt/NethSec8**
-  **Installazione opzionale FRPC** con configurazione interattiva
-  **Disinstallazione completa** con opzioni separate per Agent e FRPC
-  **Rilevamento automatico** del sistema operativo
-  **Configurazione systemd/init.d** completa
-  **Output colorato** e user-friendly

##  Cosa fa lo script

### Parte 1: CheckMK Agent (sempre installato)
1. Rileva automaticamente il sistema operativo
2. Scarica il pacchetto CheckMK Agent corretto (DEB o RPM)
3. Installa l'agent
4. Disabilita TLS e configurazione standard
5. Crea socket systemd plain su porta 6556
6. Avvia e testa l'agent

### Parte 2: FRPC Client (opzionale)
1. Chiede se si vuole installare FRPC
2. Scarica e installa FRPC v0.64.0
3. Configurazione interattiva con richiesta di:
   - **Nome host** (default: hostname corrente)
   - **Server FRP remoto** (default: monitor.nethlab.it)
   - **Porta remota** (obbligatorio, es: 20001)
   - **Token di sicurezza** (default: conduit-reenact-talon-macarena-demotion-vaguely)
4. Genera file `/etc/frp/frpc.toml` con la configurazione
5. Crea servizio systemd per FRPC
6. Avvia e verifica il tunnel

##  Requisiti

- Sistema operativo supportato: 
  - **Debian-based**: Ubuntu, Debian
  - **RHEL-based**: Rocky Linux, CentOS, RHEL, AlmaLinux
  - **NethServer**: NethServer Enterprise (rilevato automaticamente)
  - **OpenWrt**: OpenWrt 23.05+, NethServer 8 Core (NethSec8)
- Accesso root o sudo
- Connessione internet
- CheckMK Server raggiungibile (per download pacchetti)

###  Nota su NethServer Enterprise
NethServer Enterprise viene **rilevato automaticamente** tramite il file `/etc/nethserver-release`. Lo script utilizzerà automaticamente i pacchetti RPM appropriati per l'installazione.

###  Nota su OpenWrt/NethSec8
OpenWrt e NethServer 8 Core vengono rilevati tramite `/etc/openwrt_release`. Lo script:
- Usa **opkg** come package manager
- Estrae manualmente il pacchetto DEB
- Configura **socat** come listener sulla porta 6556
- Crea servizio **init.d** con procd (non systemd)
- Supporta FRPC con servizio init.d dedicato

##  Utilizzo

###  Installazione

#### Metodo 1: Esecuzione diretta
```bash
sudo bash install-agent-interactive.sh
```

#### Metodo 2: Con permessi di esecuzione
```bash
chmod +x install-agent-interactive.sh
sudo ./install-agent-interactive.sh
```

###  Disinstallazione

#### Rimuovi solo FRPC Client
```bash
sudo ./install-agent-interactive.sh --uninstall-frpc
```

#### Rimuovi solo CheckMK Agent
```bash
sudo ./install-agent-interactive.sh --uninstall-agent
```

#### Rimuovi tutto (Agent + FRPC)
```bash
sudo ./install-agent-interactive.sh --uninstall
```

#### Mostra help
```bash
./install-agent-interactive.sh --help
```

###  Opzioni disponibili

| Opzione | Descrizione |
|---------|-------------|
| _(nessuna)_ | Installazione interattiva completa |
| `--uninstall-frpc` | Disinstalla solo FRPC client |
| `--uninstall-agent` | Disinstalla solo CheckMK Agent |
| `--uninstall` | Disinstalla tutto (con conferma) |
| `--help` o `-h` | Mostra messaggio di aiuto |

##  Esempio di Sessione Interattiva

```
╔════════════════════════════════════════════════════════════╗
║  Installazione Interattiva CheckMK Agent + FRPC          ║
║  Version: 1.0 - 2025-11-06                                ║
╚════════════════════════════════════════════════════════════╝

 Sistema rilevato: ubuntu 22.04 (deb)

═══ INSTALLAZIONE CHECKMK AGENT ═══
 Download agent da: https://monitoring.nethlab.it/monitoring/...
 Installazione pacchetto...
 Agent CheckMK installato

═══ CONFIGURAZIONE AGENT PLAIN ═══
 Disabilito TLS e socket standard...
 Creo unit systemd per agent plain...
 Ricarico systemd e avvio socket...
 Agent plain configurato su porta 6556

 Test agent locale:
<<<check_mk>>>
Version: 2.4.0p12
Hostname: myserver
AgentOS: linux

════════════════════════════════════════
Vuoi installare anche FRPC? [s/N]: s
════════════════════════════════════════

═══ INSTALLAZIONE FRPC CLIENT ═══
 Download FRPC v0.64.0...
 Estrazione...
 FRPC installato in /usr/local/bin/frpc

═══ CONFIGURAZIONE FRPC ═══
Inserisci le informazioni per la configurazione FRPC:

Nome host [default: myserver]: 
Server FRP remoto [default: monitor.nethlab.it]: 
Porta remota [es: 20001]: 20001
Token di sicurezza [default: conduit-reenact-talon-macarena-demotion-vaguely]: 

 Creazione file /etc/frp/frpc.toml...
 File di configurazione creato

 Configurazione FRPC:
   Server:       monitor.nethlab.it:7000
   Tunnel:       myserver
   Porta remota: 20001
   Porta locale: 6556

 Creazione servizio systemd...
 FRPC avviato con successo

╔════════════════════════════════════════════════════════════╗
║              INSTALLAZIONE COMPLETATA                     ║
╚════════════════════════════════════════════════════════════╝

 RIEPILOGO:
    CheckMK Agent installato (plain TCP 6556)
    Socket systemd attivo: check-mk-agent-plain.socket
    FRPC Client installato e configurato
    Tunnel attivo: monitor.nethlab.it:20001 → localhost:6556

 COMANDI UTILI:
   Test agent locale:    /usr/bin/check_mk_agent
   Status socket:        systemctl status check-mk-agent-plain.socket
   Status FRPC:          systemctl status frpc
   Log FRPC:             journalctl -u frpc -f
   Config FRPC:          /etc/frp/frpc.toml

 Installazione terminata con successo!
```

##  Configurazione FRPC Generata

Il file `/etc/frp/frpc.toml` viene creato automaticamente con questa struttura:

```toml
# Configurazione FRPC Client
# Generato il 2025-11-06

[common]
server_addr = "monitor.nethlab.it"
server_port = 7000
auth.method = "token"
auth.token  = "conduit-reenact-talon-macarena-demotion-vaguely"
tls.enable = true
log.to = "/var/log/frpc.log"
log.level = "debug"

[myserver]
type        = "tcp"
local_ip    = "127.0.0.1"
local_port  = 6556
remote_port = 20001
```

**Note sul formato:**
- Sezione `[common]` con parametri globali
- Sezione `[hostname]` per ogni tunnel
- Log level `debug` per troubleshooting completo
- Log salvato in `/var/log/frpc.log`

##  Verifica Post-Installazione

### CheckMK Agent
```bash
# Test locale dell'agent
/usr/bin/check_mk_agent

# Verifica socket systemd
systemctl status check-mk-agent-plain.socket

# Test da remoto (dal server CheckMK)
telnet <IP_HOST> 6556
```

### FRPC (se installato)
```bash
# Status servizio
systemctl status frpc

# Visualizza log in tempo reale
journalctl -u frpc -f

# Verifica file di configurazione
cat /etc/frp/frpc.toml

# Riavvio servizio
systemctl restart frpc
```

##  Gestione Servizi

### Riavvio Agent
```bash
systemctl restart check-mk-agent-plain.socket
```

### Riavvio FRPC
```bash
systemctl restart frpc
```

### Modifica configurazione FRPC
```bash
# Edita il file
nano /etc/frp/frpc.toml

# Riavvia per applicare modifiche
systemctl restart frpc
```

##  Esempi Disinstallazione

### Disinstalla solo FRPC (mantieni Agent)
```bash
sudo ./install-agent-interactive.sh --uninstall-frpc
```
**Output:**
```
╔════════════════════════════════════════════════════════════╗
║           DISINSTALLAZIONE FRPC CLIENT                    ║
╚════════════════════════════════════════════════════════════╝

  Rimozione FRPC in corso...

  Arresto servizio FRPC...
  Disabilito servizio FRPC...
  Rimozione file systemd...
  Rimozione eseguibile...
  Rimozione directory configurazione...
  Rimozione file log...

 FRPC disinstallato completamente
 File rimossi:
   • /usr/local/bin/frpc
   • /etc/frp/
   • /etc/systemd/system/frpc.service
   • /var/log/frpc.log
```

### Disinstalla solo Agent (mantieni FRPC)
```bash
sudo ./install-agent-interactive.sh --uninstall-agent
```
**Rimuove:**
- Pacchetto check-mk-agent
- Socket systemd plain
- Directory /etc/check_mk
- Plugin agent

### Disinstalla tutto
```bash
sudo ./install-agent-interactive.sh --uninstall
```
**Chiede conferma** prima di procedere con la rimozione completa di Agent e FRPC.

##  File di Configurazione

| File | Descrizione |
|------|-------------|
| `/etc/systemd/system/check-mk-agent-plain.socket` | Socket systemd agent plain |
| `/etc/systemd/system/check-mk-agent-plain@.service` | Service systemd agent plain |
| `/etc/frp/frpc.toml` | Configurazione FRPC client |
| `/etc/systemd/system/frpc.service` | Service systemd FRPC |
| `/var/log/frpc.log` | Log FRPC client |

##  Note Importanti

1. **Porta 6556**: L'agent CheckMK ascolta su questa porta (plain TCP, no TLS)
2. **Firewall**: Assicurati che la porta 6556 sia aperta se accedi da remoto direttamente
3. **FRPC Tunnel**: Se usi FRPC, il traffico passa attraverso il tunnel sicuro
4. **Token FRPC**: Il token di default è condiviso, usa un token personalizzato in produzione
5. **Aggiornamenti**: Lo script installa CheckMK Agent v2.4.0p12 e FRPC v0.64.0

##  Troubleshooting

### Agent non risponde
```bash
# Verifica socket attivo
systemctl status check-mk-agent-plain.socket

# Riavvia socket
systemctl restart check-mk-agent-plain.socket

# Test locale
/usr/bin/check_mk_agent
```

### FRPC non si connette
```bash
# Verifica log
journalctl -u frpc -n 50

# Testa connessione al server
telnet monitor.nethlab.it 7000

# Verifica configurazione
cat /etc/frp/frpc.toml

# Riavvia servizio
systemctl restart frpc
```

### Porta già in uso
```bash
# Verifica chi usa la porta 6556
ss -tulpn | grep 6556

# Ferma eventuale servizio conflittuale
systemctl stop check-mk-agent.socket
systemctl disable check-mk-agent.socket
```

##  Link Utili

- [Documentazione CheckMK Agent](https://docs.checkmk.com/latest/en/agent_linux.html)
- [FRP GitHub Repository](https://github.com/fatedier/frp)
- [FRP Documentation](https://gofrp.org/en/)

##  Autore

Script creato per semplificare il deployment di CheckMK Agent con supporto FRPC.

##  Licenza

Uso libero per scopi di monitoraggio CheckMK.

---

**Versione**: 1.2  
**Data**: 2025-11-07  
**Compatibilità**: Ubuntu, Debian, Rocky Linux, CentOS, RHEL, AlmaLinux, NethServer Enterprise, OpenWrt 23.05+, NethSec8
