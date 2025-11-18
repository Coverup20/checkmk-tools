# Installazione CheckMK Agent + FRPC su QNAP NAS

## 📋 Descrizione

Script per l'installazione automatica di CheckMK Agent e FRPC su sistemi QNAP NAS.

## ✅ Requisiti

- QNAP NAS con QTS 4.x/5.x o QuTS hero
- Accesso SSH attivo
- Utente root o admin
- Almeno 100MB di spazio disco

## 🚀 Installazione

### 1. Carica lo script sul NAS

```bash
# Via SCP
scp install-agent-frpc-qnap.sh admin@IP_QNAP:/tmp/

# Oppure scarica direttamente sul NAS
ssh admin@IP_QNAP
cd /tmp
wget https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/install-agent-frpc-qnap.sh
chmod +x install-agent-frpc-qnap.sh
```

### 2. Esegui l'installazione

```bash
sudo ./install-agent-frpc-qnap.sh
```

## ⚙️ Opzioni

```bash
# Installazione interattiva (default)
./install-agent-frpc-qnap.sh

# Disinstalla solo FRPC
./install-agent-frpc-qnap.sh --uninstall-frpc

# Disinstalla solo Agent
./install-agent-frpc-qnap.sh --uninstall-agent

# Disinstalla tutto
./install-agent-frpc-qnap.sh --uninstall

# Aiuto
./install-agent-frpc-qnap.sh --help
```

## 🔧 Gestione dipendenze

### Se `socat` non è disponibile

Lo script tenterà di installare automaticamente `socat`. Se fallisce, hai tre opzioni:

#### Opzione 1: Installa Entware (consigliato)

1. Apri **App Center** su QNAP
2. Cerca e installa **Entware**
3. Dopo l'installazione di Entware:
   ```bash
   opkg update
   opkg install socat
   ```
4. Riesegui lo script di installazione

#### Opzione 2: Scarica socat manualmente

```bash
# Per QNAP x86_64
cd /tmp
wget http://bin.entware.net/x86-64/other/socat
chmod +x socat
mv socat /usr/local/bin/
```

#### Opzione 3: Usa xinetd (alternativa)

Lo script chiederà automaticamente se vuoi usare xinetd al posto di socat:
```
Vuoi provare a usare xinetd al posto di socat? [s/N]: s
```

## 📂 Struttura installazione

```
/opt/checkmk/
├── bin/
│   └── check_mk_agent          # Agent CheckMK
├── log/
│   └── agent.log               # Log agent
├── start_agent.sh              # Script avvio
└── stop_agent.sh               # Script stop

/opt/frpc/
├── bin/
│   └── frpc                    # Client FRPC
├── conf/
│   └── frpc.toml              # Configurazione
├── log/
│   ├── frpc.log               # Log FRPC
│   └── startup.log            # Log startup
├── start_frpc.sh              # Script avvio
└── stop_frpc.sh               # Script stop

/etc/config/autorun.sh         # Autostart QNAP
```

## 🎮 Comandi utili

### CheckMK Agent

```bash
# Avvia agent
/opt/checkmk/start_agent.sh

# Ferma agent
/opt/checkmk/stop_agent.sh

# Test manuale
/usr/bin/check_mk_agent

# Verifica porta
nc localhost 6556

# Log agent
tail -f /opt/checkmk/log/agent.log
```

### FRPC Client

```bash
# Avvia FRPC
/opt/frpc/start_frpc.sh

# Ferma FRPC
/opt/frpc/stop_frpc.sh

# Verifica processo
ps aux | grep frpc

# Log FRPC
tail -f /opt/frpc/log/frpc.log

# Modifica configurazione
vi /opt/frpc/conf/frpc.toml
```

## 🔍 Troubleshooting

### Agent non risponde

```bash
# Verifica processo
ps aux | grep -E "socat|xinetd"

# Verifica porta
netstat -tlnp | grep 6556

# Restart manuale
/opt/checkmk/stop_agent.sh
/opt/checkmk/start_agent.sh

# Test locale
echo "exit" | nc localhost 6556
```

### FRPC non si connette

```bash
# Verifica log
tail -50 /opt/frpc/log/frpc.log

# Verifica configurazione
cat /opt/frpc/conf/frpc.toml

# Test connessione server
nc -zv SERVER_IP 7000

# Restart
/opt/frpc/stop_frpc.sh
/opt/frpc/start_frpc.sh
```

### Autostart non funziona

```bash
# Verifica autorun.sh
cat /etc/config/autorun.sh

# Verifica permessi
ls -la /etc/config/autorun.sh
chmod +x /etc/config/autorun.sh

# Test manuale autorun
/etc/config/autorun.sh
```

## 📝 Note

- I servizi si avviano automaticamente al boot tramite `/etc/config/autorun.sh`
- Il backup di `autorun.sh` viene creato automaticamente prima delle modifiche
- L'agent CheckMK ascolta sulla porta TCP **6556**
- FRPC si connette al server FRP specificato durante l'installazione
- I log vengono mantenuti per 7 giorni (FRPC) o illimitati (Agent)

## 🆘 Supporto

In caso di problemi:

1. Verifica i log in `/opt/checkmk/log/` e `/opt/frpc/log/`
2. Controlla che le porte non siano bloccate dal firewall QNAP
3. Verifica la configurazione in `/opt/frpc/conf/frpc.toml`
4. Consulta la documentazione CheckMK e FRP ufficiale

## 📄 Licenza

Script sviluppato per uso interno - Modificabile liberamente
