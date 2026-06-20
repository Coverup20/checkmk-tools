# Q&A Troubleshooting - checkmk-tools

## 2026-06-16 - PING service rules lost after cmk-update-config on srv-monitoring-us

**Q:** Le regole WATO per il servizio PING (max_check_attempts, retry_interval) create nel folder "Main" vengono perse dopo un `cmk-update-config`. Come verificare se le regole sono attive e come prevenirne la perdita?

**A:** Le regole create via WATO vengono registrate nell'audit log (`wato_audit.log`) ma possono essere perse se:
1. Vengono create in una sessione WATO
2. Vengono attivate (snapshot + activate-changes)
3. Successivamente un `cmk-update-config` (eseguito da system/user `-`) rigenera la configurazione

**Verifica se le regole sono attive:**
```bash
# 1. Controlla se la regola esiste nel rules.mk attuale
grep "<rule_id>" /omd/sites/monitoring/etc/check_mk/conf.d/wato/rules.mk

# 2. Controlla se la regola è nell'audit log
grep "<rule_id>" /omd/sites/monitoring/var/check_mk/wato/log/wato_audit.log

# 3. Controlla se la regola è in uno snapshot
tar xzf /omd/sites/monitoring/var/check_mk/wato/snapshots/wato-snapshot-*.tar
tar xzf check_mk.tar.gz
grep -r "<rule_id>" .

# 4. Verifica la configurazione Nagios effettiva
su - monitoring -c "cmk -N <hostname>" | grep -A 10 "define service {"
```

**Prevenzione:** Dopo aver creato regole WATO, verificare immediatamente con `cmk -N <host>` che appaiano nella configurazione Nagios generata. Se il `cmk-update-config` le sovrascrive, ricrearle e riattivarle.

**Sintomo chiave:** `config-generation.mk` mostra un numero di pending changes > 0 anche dopo l'attivazione.

## 2026-06-16 - Aggiunto notification_interval=480 a regola notifica Marca_Tempi

**Q:** Come limitare le notifiche ripetute per un host group in Checkmk senza modificare le regole di notifica via WATO?

**A:** Aggiungere manualmente `notification_interval` (in minuti) alla regola di notifica nel file `notifications.mk`.

```bash
# Backup
cp notifications.mk notifications.mk.bak.$(date +%Y-%m-%d_%H%M%S)
chown monitoring:monitoring notifications.mk.bak.*

# Modifica con Python (sed non gestisce bene le virgolette nidificate)
python3 << 'PYEOF'
with open('notifications.mk', 'r') as f:
    content = f.read()
old = "{...regola esistente...}"
new = "{...regola con notification_interval: 480...}"
content = content.replace(old, new)
with open('notifications.mk', 'w') as f:
    f.write(content)
PYEOF

# Attivazione
su - monitoring -c "cmk -U"    # genera configurazione
su - monitoring -c "cmk -O"    # ricarica core
```

**Valore:** `notification_interval=480` = 8 ore. Con notification_interval=480, un host che va DOWN riceve max 1 notifica iniziale + 1 ripetuta ogni 8 ore + 1 recovery. Con 3 DOWN/giorno → max 6 notifiche (3 DOWN + 3 UP).

**Differenza tra notification_interval e altri parametri:**
- `notification_interval`: controlla le NOTIFICHE RIPETUTE mentre il problema persiste
- `max_check_attempts`: controlla quanti SOFT check prima di HARD state
- `retry_interval`: controlla ogni quanto ripetere i SOFT check

## 2026-06-16 - Comparative audit di alert time-clock su srv-monitoring-us

**Q:** Come condurre un audit comparativo read-only degli alert Checkmk prima/dopo un cambio configurazione, analizzando Nagios archives, WATO audit log, notification log e configurazione effettiva?

**A:** Workflow completo per audit read-only:

1. **Trova il timestamp del cambio configurazione** → WATO audit log (`wato_audit.log`), cercare `edit-rule` con `max_check_attempts` o `PING`
2. **Verifica configurazione effettiva** → `cmk -N <host>` per vedere i parametri Nagios reali; `rules.mk` per le regole WATO
3. **Analizza eventi Nagios** → Cercare `HOST ALERT`, `SERVICE ALERT`, `NOTIFICATION` negli archivi (`var/nagios/archive/`)
4. **Conteggio per periodi** → Usare `awk -F'[][]' '$2 >= <timestamp_start> && $2 < <timestamp_end>'` per filtrare per timestamp
5. **Classificazione HARD vs SOFT** → `grep "HARD\|SOFT"` per distinguere stati reali da transienti
6. **Correlazione PING + host DOWN** → Eventi entro 5 minuti = stesso incidente
7. **Verifica regole notifica** → `notifications.mk` per capire amplificazione notifiche

**Comandi chiave:**
```bash
# Estrai eventi per periodo
awk -F'[][]' '$2 >= 1779148800 && $2 < 1779753600' /tmp/events.txt | grep "HOST ALERT"

# Conteggio per host
grep -oP "marcatempo-\w+" events.txt | sort | uniq -c | sort -rn

# Verifica regole notifica
cat /omd/sites/monitoring/etc/check_mk/conf.d/wato/notifications.mk
```

## 2026-06-13 - Pacchetti check-mk-raw half-configured (iF) bloccano apt su srv-monitoring-us

**Q:** upgrade_checkmk.py installa il .deb ma la post-installation fallisce, lasciando il pacchetto in stato `iF` (half-configured) che blocca dpkg/apt. Come prevenirlo?

**A:** Il problema si verifica quando `dpkg -i` installa un pacchetto `check-mk-raw-*` la cui post-installation cerca di creare un `update-alternatives` verso `/omd/versions/X.Y.ZpN.cre` che non esiste (perché la versione OMD è stata già rimossa). Un singolo pacchetto `iF` blocca TUTTE le successive operazioni apt, incluso `apt-get autoremove`.

**Fix nello script `upgrade_checkmk.py` v1.5.0:**

1. **`cleanup_half_configured_packages()`**: nuova funzione che scansiona `dpkg -l` per pacchetti `check-mk-*` in stato `iF` e li rimuove con `dpkg --remove --force-depends`
2. **Chiamata pre-install**: eseguita prima di `dpkg -i` — pulisce eventuali `iF` preesistenti
3. **Chiamata post-failure**: eseguita dopo un fallimento di `dpkg -i` — rimuove il pacchetto `iF` prima del retry con `apt-get -f install`
4. **`apt-get install -f -y` prima di `autoremove`**: risolve dipendenze residue prima della pulizia finale

**Comando manuale per pulire pacchetti iF esistenti:**
```bash
dpkg --remove --force-depends check-mk-raw-2.4.0p23 check-mk-raw-2.4.0p25 check-mk-raw-2.4.0p26 check-mk-raw-2.4.0p27
dpkg --purge check-mk-raw-2.4.0p23 check-mk-raw-2.4.0p25 check-mk-raw-2.4.0p26 check-mk-raw-2.4.0p27
apt-get -f install -y
apt-get autoremove -y
```

**Verifica:**
```bash
dpkg -l | grep check-mk  # nessun pacchetto in stato iF
```

---

## File creati su srv-monitoring-sp devono essere monitoring:monitoring

**Q:** Quando creo file su srv-monitoring-sp (retention.dat backup, script temporanei, ecc.) con quale owner devono essere?

**A:** SEMPRE `monitoring:monitoring` — MAI `root:root`.

Se il file è `root:root` Nagios/CheckMK non riesce a leggerlo/scriverlo e il sistema si incrista.

**Pattern corretto:**
```bash
# Dopo aver scritto un file come root
chown monitoring:monitoring /omd/sites/monitoring/var/nagios/retention.dat.backup_*

# Quando si copia un file
scp file.py srv-monitoring-sp:/omd/sites/monitoring/fix.py
ssh srv-monitoring-sp "chown monitoring:monitoring /omd/sites/monitoring/fix.py"
```

**File critici che devono essere monitoring:monitoring:**
- `retention.dat` e qualsiasi backup
- Qualsiasi script in `/omd/sites/monitoring/`
- File temporanei usati da `su - monitoring -c`

---

## 2026-06-20 - Fail-safe logging pattern for notification scripts

**Q:** How do you prevent a logging failure from blocking email or Telegram delivery in Checkmk notification scripts?

**A:** Use a three-layer fail-safe logging strategy:

1. **Handler-level**: Replace `logging.FileHandler` with a custom `_SafeFileHandler` that wraps `emit()` in try/except and falls back to a single sanitized stderr line. This prevents any single handler from crashing the logging framework.

2. **Call-site-level**: Route all lifecycle records through `_safe_log()` which wraps the LOG call in try/except. Never call `LOG.*` directly in business-logic functions that run before or during delivery.

3. **No global monkeypatch**: Do NOT patch `logging.Logger._log`. The handler-level and call-site-level protections are sufficient. A global patch cannot be removed safely in multi-module contexts.

Python 3.13's `Handler.handle()` does NOT catch `emit()` exceptions (the try/except was removed). Therefore every handler MUST be self-protecting.

**Key verification test**: Add a handler that raises `OSError(28)` on every `emit()` and verify:
- delivery still proceeds (rc preserved)
- `_safe_log()` catches the exception and writes a fallback to stderr
- existing `LOG.info()` calls in functions like `log_decision()`, `evaluate_rate_limit()`, and `read_state()` are protected by `_SafeFileHandler`

## 2026-06-20 - JSON state retention for notification scripts

**Q:** How is JSON state-file growth bounded in M@il-20 and Telegram-20?

**A:** Three mechanisms work together:

1. **Pruning order bug**: Originally `_cleanup_stale_records()` ran AFTER `write_state()`, so cleaned records were never persisted. Fix: run cleanup BEFORE write.

2. **Retention defaults** (configurable via `state_retention`):
   - `stale_host_days`: 30 — remove hosts with no transitions and expired suppression
   - `max_transitions_per_category`: 500 — cap transition arrays after age-based pruning
   - `cleanup_interval_seconds`: 3600 — rate-limit full stale-host scans

3. **Oversized-file handling**: If the state file exceeds 10 MB, a warning is logged but loading proceeds normally. Valid oversized JSON is parsed successfully. Corrupted files follow the existing recovery path (empty dict returned).

**Atomic write pattern**: Temporary file created in the same directory via `tempfile.mkstemp(dir=str(state_path.parent))`, then `os.replace()` for atomic rename. If write fails, original file is preserved and temp file is cleaned up.

---

## ABSOLUTE RULE - MAI usare ENABLE/DISABLE_HOST_SVC_CHECKS sul nagios pipe

**Q:** Come si gestisce un overload di check o servizi stale sui client?

**A:** MAI toccare il nagios command pipe con `ENABLE_HOST_SVC_CHECKS` o `DISABLE_HOST_SVC_CHECKS`.

**Causa dell'errore:** questi comandi disabilitano/abilitano TUTTI i servizi dell'host inclusi quelli passivi → causa errore "ERROR - you did an active check on this service - please disable active checks" su tutti i servizi passivi.

**La regola è già documentata in `.github/copilot-instructions.md` sezione "ABSOLUTE RULES - CheckMK Active/Passive Checks":**
- NEVER `ENABLE_SVC_CHECK` o `DISABLE_SVC_CHECK`
- Per stale: usare SOLO `cmk --check <host>` come utente monitoring
- Per overload: aumentare check interval in rules.mk, NON disabilitare check

**Se si incappa nell'errore "active check":**
1. Modificare chirurgicamente `retention.dat` rimuovendo le righe `plugin_output=ERROR...active check`
2. Se retention.dat è compromesso: `omd stop && rm retention.dat && omd start`
3. Il sistema riparte pulito in ~10 minuti

**Costo di questa lezione:** 2 site restore (marzo 2026 + giugno 2026)

**CAUSA RADICE giugno 2026:** tentativo di gestire overload check con DISABLE/ENABLE_HOST_SVC_CHECKS → errori active check su 476 servizi passivi → retention.dat corrotto → omd stop/rm retention.dat/omd start non risolve perché Nagios rigenera retention.dat dal primo check cycle che contiene ancora gli errori.

**SOLUZIONE DEFINITIVA per errori active check su servizi passivi (metodo empirico ma efficace):**

1. **Identifica il folder WATO** a cui appartengono gli host affetti (es. `/clients`)
2. **Cancella tutti gli host affetti** dal folder WATO — via CLI (`cmk --delete-host <host>`) o via interfaccia web — non cercare di fixare i singoli servizi
3. **Verifica la subnet** configurata nel folder di appartenenza — deve essere quella corretta raggiungibile dal server di monitoraggio
4. **Programma una nuova scansione** della subnet corretta (Setup → Dynamic host management o scan manuale)
5. Gli host vengono riscoperti puliti, senza storia di errori
6. La discovery automatica (periodic_discovery) completa il resto

**Perché funziona:** cancellando l'host si eliminano anche gli autochecks e tutti i check result in cache — riparte da zero pulito.

**Prerequisito:** gli host devono stare tutti nello stesso folder — è il motivo per cui organizzare i client per subnet/folder è importante.

- NON tentare di modificare retention.dat — viene rigenerato ad ogni check cycle
- NON usare cmk --check per "fixare" — non funziona se l'host è offline

**REGOLA ASSOLUTA — aggiunta a seguito di giugno 2026:**
- NEVER usare `DISABLE_HOST_SVC_CHECKS` o `ENABLE_HOST_SVC_CHECKS` per gestire il carico
- Per overload: aumentare check interval in rules.mk (`extra_service_conf['normal_check_interval']`)
- Per stale: aspettare il ciclo normale o usare `cmk --check <host>` SOLO se l'host è online
- Per client folder con molti host: intervallo 10 minuti, max_concurrent_checks=20 in nagios.cfg

---

## Check_MK Discovery crash: "not enough values to unpack (expected 2, got 1)"

**Q:** Il servizio Check_MK Discovery su un host crasha con "check failed - please submit a crash report! (Crash-ID: ...)" e il crash report mostra `ValueError: not enough values to unpack (expected 2, got 1)` in `_utils.py:61 from_vs()`.

**A:** Il problema è un `mode` malformato nella regola `periodic_discovery` in `rules.mk`. Invece di `(0, {...})` (identificatore numerico + flags), il mode contiene un UUID come identificatore: `('95a56ffc-...', {...})`.

**Fix via CLI (senza WATO):**
```bash
# 1. Backup
cp rules.mk rules.mk.backup_$(date +%Y%m%d_%H%M%S)

# 2. Sostituisci l'UUID con 0 nel mode
sed -i "s/('<UUID>', {'update_host_labels': ...})/(0, {'update_host_labels': ...})/" rules.mk

# 3. Verifica sintassi Python
su - monitoring -c "PYTHONDONTWRITEBYTECODE=1 python3 -B -c \"
with open('etc/check_mk/conf.d/wato/rules.mk') as f:
    compile(f.read(), 'rules.mk', 'exec')
    print('SYNTAX OK')
\""

# 4. Ricarica configurazione
su - monitoring -c "cmk -O"

# 5. Test
su - monitoring -c "cmk --check-discovery <hostname>"
```

**Causa:** Bug in CheckMK 2.5.0p3 — il WATO salva l'UUID come identificatore del mode invece di un valore numerico (0=discover all, 1=tabula rasa, 2=discover+labels). Il codice `from_vs()` in `_utils.py` fa `_ident, flags = mode` e fallisce perché riceve una tupla annidata invece del formato atteso.

---

## Come aggiornare stato servizio UNKNOWN/CRASH dopo un fix

**Q:** Dopo aver fixato un crash (es. Check_MK Discovery), il servizio rimane in stato UNKNOWN nell'interfaccia. Come si aggiorna?

**A:** Il fix impedisce che il crash si ripeta, ma lo stato passato va aggiornato forzando un risultato via nagios command pipe.

**Metodo 1 — PROCESS_SERVICE_CHECK_RESULT via nagios.cmd (funziona sempre):**
```bash
# Sostituisci hostname, servizio, stato (0=OK) e output
NOW=$(date +%s)
echo "[$NOW] PROCESS_SERVICE_CHECK_RESULT;fw.studiopaci.info;Check_MK Discovery;0;Services: all up to date, Host labels: all up to date" > /omd/sites/monitoring/tmp/run/nagios.cmd
```

**Metodo 2 — Acknowledge via WATO:**
- Vai sul servizio → pulsante "Acknowledge" → conferma
- Più semplice ma non aggiorna lo stato — nasconde solo l'allarme

**Note:**
- `PROCESS_SERVICE_CHECK_RESULT` è l'unico comando nagios pipe sicuro — NON usare `ENABLE/DISABLE_SVC_CHECK`
- Nagios processa il pipe entro pochi secondi — logga `SERVICE ALERT: ...;OK;HARD;1;...`
- Dopo il fix, verificare con: `su - monitoring -c "PYTHONDONTWRITEBYTECODE=1 python3 -B -c 'import socket; s=socket.socket(socket.AF_UNIX); s.connect(\"/omd/sites/monitoring/tmp/run/live\"); s.send(b\"GET services\\nFilter: host_name = <host>\\nFilter: description = <service>\\nColumns: state plugin_output\\n\\n\"); s.shutdown(socket.SHUT_WR); print(s.makefile().read().strip())'"`

---

## Backup su srv-monitoring-sp — SEMPRE monitoring:monitoring

**Q:** Dopo aver creato backup di file di configurazione su srv-monitoring-sp, il servizio CheckMK crasha o non funziona. Perché?

**A:** I file creati come root in `/omd/sites/monitoring/etc/` hanno owner `root:root`, ma Nagios/CheckMK gira come utente `monitoring`. Se un file di configurazione o un backup ha permessi sbagliati, CheckMK non riesce a leggerlo.

**REGOLA ASSOLUTA:**
- Ogni file creato in `/omd/sites/monitoring/` deve essere `monitoring:monitoring`
- DOPO ogni backup → `chown monitoring:monitoring /path/to/backup/file`
- Verificare sempre con `ls -la` dopo aver creato file
- Il file originale (`rules.mk`) era già `monitoring:monitoring` per fortuna — ma il backup no

---

## 2026-06-18 - Diagnosi alert Virtual memory (Committed_AS) su srv-monitoring-us

**Q:** Il servizio CheckMK "Memory" su srv-monitoring-us va in WARNING/CRITICAL per "Committed: XX% virtual memory". Cosa significa e come si diagnostica?

**A:** L'alert misura **Committed_AS** da `/proc/meminfo` — NON è RAM né swap. Committed_AS è la quantità di spazio di indirizzi virtuali che il kernel ha promesso ai processi. Su un server di monitoring, il core Nagios fork periodicamente figli per eseguire check. Ogni figlio eredita via fork il VSZ del padre (~1.5 GiB). Durante i picchi di check execution, `Committed_AS` può superare il 100% di RAM+swap anche se il sistema ha MemAvailable >60% e swap inutilizzato.

**Sintomi:**
- Servizio Memory mostra WARNING/CRITICAL per `Committed: >100%`
- RAM e swap sono ampiamente disponibili (MemAvailable >50%, swap <1% used)
- Committed_AS oscilla violentemente (es. 4 GiB → 19 GiB → 6 GiB in minuti)
- Figli Nagios con VSX 1.5 GiB appaiono/scompaiono sincronizzati coi check

**Diagnosi:**
```bash
# 1. Verificare se è un falso positivo da fork
ssh srv-monitoring-us "awk '/Committed_AS/{printf \"%.1f GiB\\n\", \$2/1024/1024}' /proc/meminfo"
ssh srv-monitoring-us "pgrep -P \$(pgrep -f 'bin/nagios' | head -1) | wc -l"

# 2. Verificare stato reale della memoria
ssh srv-monitoring-us "free -h; echo '---'; grep MemAvailable /proc/meminfo"

# 3. Vedere cronologia alert
ssh srv-monitoring-us "grep 'Memory.*ALERT' /omd/sites/monitoring/var/log/nagios.log | tail -10"
```

**Soluzione:**
- Aumentare le soglie CheckMK: WARN al 200%, CRIT al 300% del total (RAM+swap)
- Oppure ignorare l'alert se non ci sono sintomi reali (swap usage, OOM killer, RSS elevata)
- `vm.overcommit_memory` e `vm.swappiness` NON vanno modificati
- Swap NON va aumentato
- Nessun processo leaky — è normale comportamento del fork model di Nagios

---

## 2026-06-17 - Definizione ed applicazione delle soglie di service e host flap su srv-monitoring-us

**Q:** Come modificare le soglie di flapping per servizi ed host in modo che siano persistenti ed applicate al core Nagios?

**A:** Modificare le opzioni all'interno di `/omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg` da utente `monitoring`, assicurandosi di preservare l'owner `monitoring:monitoring`, quindi eseguire il reload del Core.

**Modifica dei parametri per servizi ed host:**
```bash
# 1. Backup chirurgico prima delle modifiche
TS=$(date +%Y-%m-%d_%H%M%S)
cp /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg.bak.$TS
chown monitoring:monitoring /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg.bak.$TS

# 2. Modifica delle righe di service flapping da 20/40 a 10/25
sed -i "s/^low_service_flap_threshold=.*/low_service_flap_threshold=10.0/" /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg
sed -i "s/^high_service_flap_threshold=.*/high_service_flap_threshold=25.0/" /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg

# 3. Modifica delle righe di host flapping da 20/40 a 10/25
sed -i "s/^low_host_flap_threshold=.*/low_host_flap_threshold=10.0/" /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg
sed -i "s/^high_host_flap_threshold=.*/high_host_flap_threshold=25.0/" /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg

# 4. Rigenerazione ed attivazione configurazione core Nagios
su - monitoring -c "cmk -O"
```

**Verifica:**
```bash
grep -E "threshold" /omd/sites/monitoring/etc/nagios/nagios.d/flapping.cfg
```

---

## 2026-06-17 - Threshold flapping data-driven su srv-monitoring-us (90gg di log)

**Q:** Quali soglie di flapping usare su srv-monitoring-us basate sui dati reali di 90 giorni?

**A:** Dopo analisi di 3048 eventi START e 3040 eventi STOP nei log Nagios:

| | Cluster globale (~50%) | Cluster custom (~50%) |
|---|---|---|
| START host | ~43.2% | ~23% |
| STOP host | ~17.4% | ~3.8% |
| START service | ~43.2% | ~20.3% |
| STOP service | ~17.4% | ~3.8% |

**Scelta finale: LOW=15.0, HIGH=30.0 per host e service.**

- 30% dimezza il gap dai 40 precedenti — cattura flapping ~13 punti % prima
- 15% è vicino ai 17.4 dove già si ferma il cluster globale — non allunga lo stato
- 15 punti di banda = stessa ampiezza dei default storici Nagios (5/20)
- Simmetrico host/service per semplicità

**Config applicata su:** checkmk-vps-02-c (test) e srv-monitoring-us (prod)

**Comandi:**
```bash
sed -i "s/^low_service_flap_threshold=.*/low_service_flap_threshold=15.0/" flapping.cfg
sed -i "s/^high_service_flap_threshold=.*/high_service_flap_threshold=30.0/" flapping.cfg
sed -i "s/^low_host_flap_threshold=.*/low_host_flap_threshold=15.0/" flapping.cfg
sed -i "s/^high_host_flap_threshold=.*/high_host_flap_threshold=30.0/" flapping.cfg
chown monitoring:monitoring flapping.cfg
su - monitoring -c "cmk -O"
```

**Verifica attiva:**
```bash
grep -E "threshold" /omd/sites/monitoring/tmp/nagios/nagios.cfg
```

---

## 2026-06-18 - Analisi 90gg marcatempo: flap mai partito, regole PING speciali e notification_interval assenti

**Q:** Dopo aver cambiato le soglie flap da 20/40 a 15/30 su srv-monitoring-us, l'analisi dei log mostra zero eventi flap e nessuna riduzione delle notifiche. Perché?

**A:** Tre cause identificate:

### 1. Flap non si attiva perché i marcatempo non flappano abbastanza

Nonostante Colibri abbia 338 HARD DOWN in 55gg (~6/giorno), gli eventi DOWN sono distribuiti su intervalli di ore, non minuti. La percentuale di cambio stato nella finestra di 20 check (~100 minuti per host check) raramente supera la soglia. Eventi flap erano stati registrati ad aprile-maggio con vecchie soglie 20/40, con percentuali del 20-23% (appena sopra). A giugno non ci sono state finestre di instabilità sufficientemente rapide.

### 2. Regole PING speciali per farmacia/palazzetto NON ATTIVE

Create in WATO il 2026-06-12 (audit log: `extra_service_conf:max_check_attempts` value=3, `extra_service_conf:retry_interval` value=2.0), mai attivate nel Nagios runtime. Tutti i PING mostrano `max_check_attempts=1, check_interval=1, retry_interval=1` in LiveStatus.

**Causa:** Le regole erano nel WATO database ma sono state perse dalla `rules.mk` attiva a causa del noto bug `cmk-update-config` (documentato 2026-06-16).

### 3. notification_interval NON presente nelle regole notifica

Nonostante la modifica documentata in qa-troubleshooting (aggiunta `notification_interval=480`), il file `notifications.mk` attualmente NON contiene `notification_interval` in nessuna regola. Le notifiche ripetute vengono generate a ogni ciclo di notifica (default 1 minuto) finché il problema persiste.

### 4. Flap nei log Nagios usa STARTED/STOPPED, non START/STOP

```bash
# CORRETTO — i log Nagios usano STARTED e STOPPED
grep "HOST FLAPPING ALERT.*marcatempo.*STARTED\|STOPPED" /omd/sites/monitoring/var/log/nagios.log

# ERRATO — nessun match
grep "HOST FLAPPING ALERT.*marcatempo.*START\|STOP" /omd/sites/monitoring/var/log/nagios.log
```

Esempio di linea reale:
```
[1776974920] HOST FLAPPING ALERT: marcatempo-colibri;STARTED; Host appears to have started flapping (22.0% change > 20.0% threshold)
[1776977610] HOST FLAPPING ALERT: marcatempo-colibri;STOPPED; Host appears to have stopped flapping (3.9% change < 5.0% threshold)
```

### Verifica regole non attive

```bash
# LiveStatus mostra max_check_attempts=1 per TUTTI i PING
echo "GET services
Columns: host_name description max_check_attempts retry_interval
Filter: host_name = marcatempo-farmacia
Filter: description = PING
" | nc -U /omd/sites/monitoring/tmp/run/live
# Output: marcatempo-farmacia;PING;1;1  ← dovrebbe essere 3;2

# Verifica notification_interval nelle regole
grep "notification_interval" /omd/sites/monitoring/etc/check_mk/conf.d/wato/notifications.mk
# Nessun output = assente
```

### Verifica soglie flap attuali nel runtime

```bash
grep -E "threshold" /omd/sites/monitoring/tmp/nagios/nagios.cfg
# Deve mostrare 15.0 e 30.0, NON 10.0 e 25.0
```

---

## 2026-06-18 - Python cache cleanup su tutti i repo

**Q:** Come pulire tutti gli artefatti Python cache (`__pycache__/`, `*.pyc`, `*.pyo`) dai repository locali e verificare che non vengano ricreati?

**A:** Workflow completo in 8 fasi:

**Fase 1 — Verifica repo:**
```bash
for PATH in "/mnt/c/Users/Marzio/.copilot" \
  "/mnt/c/Users/Marzio/Desktop/CheckMK/checkmk-tools" \
  "/mnt/c/Users/Marzio/Desktop/CheckMK/copilot-tools" \
  "/mnt/c/Users/Marzio/Desktop/CheckMK/ns8-checkmk-agent" \
  "/mnt/c/Users/Marzio/Desktop/CheckMK/ns8-checkmk-container" \
  "/mnt/c/Users/Marzio/Desktop/alexa-chatgpt-skill" \
  "/mnt/c/Users/Marzio/Desktop/CheckMK"; do
  echo "--- $PATH ---"
  [ -d "$PATH" ] && echo "EXISTS" || echo "MISSING"
  git -C "$PATH" rev-parse --show-toplevel 2>/dev/null && \
    echo "BRANCH: $(git -C "$PATH" branch --show-current)" && \
    echo "STATUS:" && git -C "$PATH" status --short || echo "NOT A GIT REPO"
done
```

**Fase 2 — Inventario read-only:**
```bash
find "$REPO" \
  \( -path "$REPO/.git" -o -path "$REPO/.venv" -o -path "$REPO/venv" -o \
     -path "$REPO/env" -o -path "$REPO/.tox" -o -path "$REPO/.nox" -o \
     -path "$REPO/node_modules" \) -prune \
  -o \( -type d -name '__pycache__' -o -type f \( -name '*.pyc' -o -name '*.pyo' \) \) -print
```

**Fase 3 — Rimozione:**
```bash
find "$REPO" \( ...prune... \) -o -type d -name '__pycache__' -print | while read d; do rm -rf "$d"; done
```

**Fase 4 — `.gitignore`:**
```gitignore
__pycache__/
*.py[cod]
*$py.class
```

**Fase 5 — Baseline:**
```bash
date '+%Y-%m-%d %H:%M:%S %Z'
# Salvare report in /tmp/python-cache-baseline-<timestamp>.txt
```

**Fase 6 — Test ricorrenza:**
```bash
# Test A: safe invocation
PYTHONDONTWRITEBYTECODE=1 python3 -B -c "print('ok')"

# Test B: in-memory compile
PYTHONDONTWRITEBYTECODE=1 python3 -B -c "compile(open('script.py').read(), 'script.py', 'exec')"
```

**Comandi shell utili:**
```bash
export PATH="/usr/bin:/usr/local/bin:/bin:/usr/sbin:$PATH"  # se PATH è corrotto
git -C "$REPO" check-ignore -v -- "$REL_PATH"              # verificare se ignorato
git -C "$REPO" ls-files --error-unmatch -- "$REL_PATH"      # verificare se tracked
```
