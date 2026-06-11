# Q&A Troubleshooting - checkmk-tools

## File creati su srv-monitoring-sp devono essere monitoring:monitoring

**Q:** Quando creo file su srv-monitoring-sp (retention.dat backup, script temporanei, ecc.) con quale owner devono essere?

**A:** SEMPRE `monitoring:monitoring` — MAI `root:root`.

Se il file è `root:root` Nagios/CheckMK non riesce a leggerlo/scriverlo e il sistema si incriста.

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
