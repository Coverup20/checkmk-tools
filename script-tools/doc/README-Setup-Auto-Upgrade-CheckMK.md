# Setup Auto-Upgrade CheckMK - Configurazione Upgrade Automatici
> **Categoria:** Operativo

##  ATTENZIONE - Script Avanzato

Questo script configura upgrade **AUTOMATICI** di CheckMK tramite crontab. Si tratta di un'operazione potenzialmente rischiosa che deve essere configurata con attenzione.

## Descrizione

Script per pianificare upgrade automatici di CheckMK RAW Edition. Il sistema verificherà periodicamente la disponibilità di nuove versioni ed eseguirà l'upgrade in modo completamente automatico e non interattivo.

## Componenti

### 1. Script Full (Interattivo)
**Path:** `script-tools/full/upgrade_maintenance/setup-auto-upgrade-checkmk.sh`

Versione completa con interfaccia interattiva per configurare gli upgrade automatici.

### 2. Remote Launcher
**Path:** `script-tools/remote/rsetup-auto-upgrade-checkmk.sh`

Launcher che scarica ed esegue lo script completo direttamente da GitHub.

### 3. Script di Upgrade
**Dipendenza:** `script-tools/full/upgrade_maintenance/upgrade-checkmk.sh`

Script che esegue effettivamente l'upgrade di CheckMK (deve essere presente).

## Caratteristiche di Sicurezza

-  **Backup automatico** prima di ogni upgrade
-  **Upgrade non interattivo** completamente automatizzato
-  **Logging dettagliato** di tutte le operazioni
-  **Notifiche email** opzionali per successo/fallimento
-  **Verifica versione** - upgrade solo se disponibile nuova versione
-  **Riavvio automatico** del sito CheckMK dopo upgrade
-  **Backup crontab** prima di modifiche
-  **Gestione duplicati** nel crontab

## Prerequisiti

### Software Richiesto
- CheckMK RAW Edition installato
- Comando `omd` disponibile
- Permessi root (sudo)
- `curl`, `wget`, `dpkg` installati
- Script `upgrade-checkmk.sh` presente in `script-tools/full/upgrade_maintenance/`

### Opzionale
- `mailutils` per notifiche email

```bash
# Installa mailutils se vuoi le notifiche email
apt install mailutils
```

## Utilizzo

### Esecuzione Locale (Interattiva)

```bash
# Dalla cartella dello script
cd /path/to/script-tools/full
sudo bash setup-auto-upgrade-checkmk.sh
```

### Esecuzione Remota

```bash
# Download ed esecuzione in un comando
bash <(curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/remote/rsetup-auto-upgrade-checkmk.sh)
```

## Opzioni di Pianificazione

### 1. Settimanale (CONSIGLIATO)
- **Frequenza:** Ogni domenica
- **Orario default:** 02:00
- **Cron:** `0 2 * * 0`
- **Pro:** Bilancia sicurezza e aggiornamenti tempestivi

### 2. Mensile
- **Frequenza:** 1° giorno del mese
- **Orario default:** 02:00
- **Cron:** `0 2 1 * *`
- **Pro:** Massima stabilità, tempo per testare nuove versioni

### 3. Personalizzato
- **Frequenza:** Inserimento manuale
- **Formato:** `minuto ora giorno mese giornosettimana`
- **Esempio:** `0 3 1,15 * *` (1° e 15° del mese alle 03:00)

## Menu Interattivo

```
╔════════════════════════════════════════════════════════════════╗
║    Configurazione Upgrade Automatici CheckMK                  ║
╚════════════════════════════════════════════════════════════════╝

ATTENZIONE: Stai per configurare upgrade AUTOMATICI di CheckMK!

Considerazioni importanti:
  - Lo script farà backup automatico prima di ogni upgrade
  - L'upgrade sarà completamente non interattivo
  - Il sito CheckMK sarà riavviato durante l'upgrade
  - Gli upgrade avverranno SOLO se disponibile una nuova versione

Sei sicuro di voler procedere? [s/N]:

Seleziona la frequenza degli upgrade automatici:

  1) Settimanale  - Ogni domenica alle 02:00 (CONSIGLIATO)
  2) Mensile      - Il primo giorno del mese alle 02:00
  3) Personalizzato - Specifica orario e frequenza custom
  4) Annulla

Scelta [1-4]:
```

## File di Log

### Posizione
```
/var/log/auto-upgrade-checkmk.log
```

### Formato Log
```
[Sun Jan 12 02:00:01 2026] Starting CheckMK auto-upgrade
[INFO] Sito: mysite
[INFO] Versione corrente: 2.3.0p1
[INFO] Ultima versione:   2.3.0p2
Aggiornamento previsto: 2.3.0p1 -> 2.3.0p2
[INFO] Backup: /opt/omd/backups/mysite_pre-upgrade_20260112_020015.tar.gz
[INFO] Download: https://download.checkmk.com/checkmk/2.3.0p2/...
[INFO] Installazione pacchetto (.deb)
[INFO] Stop sito: mysite
[INFO] Upgrade sito (omd update) - modalità automatica
[INFO] Start sito: mysite
[INFO] Versione dopo upgrade: 2.3.0p2
[Sun Jan 12 02:08:45 2026] CheckMK upgrade completed successfully
```

### Monitoraggio Log
```bash
# Visualizzare gli ultimi upgrade
tail -f /var/log/auto-upgrade-checkmk.log

# Vedere le ultime 100 righe
tail -n 100 /var/log/auto-upgrade-checkmk.log

# Cercare errori
grep -i error /var/log/auto-upgrade-checkmk.log

# Vedere tutti gli upgrade completati
grep "upgrade completed successfully" /var/log/auto-upgrade-checkmk.log
```

## Notifiche Email

### Configurazione
Durante la configurazione, lo script chiede se vuoi ricevere notifiche email:

```bash
Vuoi ricevere notifiche email sui risultati degli upgrade? [s/N]: s
Inserisci l'indirizzo email: admin@example.com
```

### Formato Email - Successo
```
Subject: CheckMK Auto-Upgrade Report
Body: CheckMK upgrade completato su monitor01 alle Sun Jan 12 02:08:45 2026
```

### Formato Email - Errore
```
Subject: [ERROR] CheckMK Auto-Upgrade Failed
Body: CheckMK upgrade fallito su monitor01 alle Sun Jan 12 02:15:30 2026
```

## Backup e Ripristino

### Backup Automatici CheckMK
Prima di ogni upgrade viene creato un backup completo:
```
/opt/omd/backups/
├── mysite_pre-upgrade_20260112_020015.tar.gz
├── mysite_pre-upgrade_20260119_020012.tar.gz
└── mysite_pre-upgrade_20260126_020009.tar.gz
```

### Ripristino Backup CheckMK
```bash
# Lista backup disponibili
ls -lh /opt/omd/backups/

# Ripristina un backup specifico
omd restore mysite /opt/omd/backups/mysite_pre-upgrade_20260112_020015.tar.gz

# Verifica ripristino
omd status mysite
```

### Backup Crontab
```
/root/crontab_backups/
└── crontab_backup_20260112_100530.txt
```

### Ripristino Crontab
```bash
# Visualizza backup disponibili
ls -lh /root/crontab_backups/

# Ripristina un backup specifico
crontab /root/crontab_backups/crontab_backup_20260112_100530.txt

# Verifica ripristino
crontab -l
```

## Gestione Crontab

### Visualizzare Entry Correnti
```bash
crontab -l
```

### Modificare Manualmente
```bash
crontab -e
```

### Rimuovere Auto-Upgrade CheckMK
```bash
crontab -l | grep -v "upgrade-checkmk.sh" | crontab -
```

## Best Practices

### 1.  Orario di Esecuzione
- **Consigliato:** 02:00-04:00 (basso traffico)
- **Evita:** Ore di punta e orari lavorativi
- **Weekend:** Preferibile per sistemi di produzione
- **Considera:** Fuso orario del server

### 2.  Frequenza Upgrade
- **Produzione critica:** Mensile + test preventivi su ambiente staging
- **Produzione standard:** Settimanale
- **Sviluppo/Test:** Anche settimanale va bene
- **Mai:** Giornaliero (troppo rischioso)

### 3.  Monitoraggio
- Controlla i log **dopo ogni upgrade automatico**
- Imposta alert per fallimenti
- Verifica funzionamento CheckMK post-upgrade
- Controlla spazio disco per backup

### 4.  Gestione Backup
- I backup si accumulano in `/opt/omd/backups/`
- Implementa rotazione backup (mantieni ultimi 5-10)
- Verifica regolarmente l'integrità dei backup
- Considera backup esterni aggiuntivi

### 5.  Testing
- **Prima volta:** Testa l'upgrade manuale
- **Staging:** Prova su ambiente di test prima
- **Verifica:** Controlla il primo upgrade automatico
- **Rollback:** Preparati a ripristinare se necessario

### 6.  Notifiche
- Configura email per amministratori
- Integra con sistemi di monitoring esistenti
- Verifica che le email arrivino correttamente
- Test iniziale di invio email

## Script di Manutenzione

### Pulizia Backup Vecchi
```bash
#!/bin/bash
# Mantieni solo gli ultimi 5 backup per ogni sito
cd /opt/omd/backups/
for site in $(omd sites | awk '{print $1}' | grep -v SITE); do
    ls -t ${site}_pre-upgrade_*.tar.gz | tail -n +6 | xargs -r rm
done
```

### Rotazione Log
```bash
# Aggiungi a /etc/logrotate.d/checkmk-auto-upgrade
/var/log/auto-upgrade-checkmk.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
}
```

## Troubleshooting

### Upgrade non viene eseguito

**1. Verifica cron attivo:**
```bash
systemctl status cron
systemctl start cron
```

**2. Controlla entry crontab:**
```bash
crontab -l | grep upgrade-checkmk
```

**3. Controlla log cron:**
```bash
grep CRON /var/log/syslog | grep upgrade-checkmk
```

**4. Test manuale:**
```bash
bash /path/to/upgrade-checkmk.sh
```

### Upgrade fallisce

**1. Controlla log dettagliato:**
```bash
tail -n 200 /var/log/auto-upgrade-checkmk.log
```

**2. Verifica spazio disco:**
```bash
df -h
```

**3. Controlla dipendenze:**
```bash
apt-get -f install
```

**4. Verifica download:**
```bash
ls -lh /tmp/checkmk-upgrade/
```

### Email non arrivano

**1. Verifica mailutils installato:**
```bash
dpkg -l | grep mailutils
apt install mailutils
```

**2. Test invio email:**
```bash
echo "Test email" | mail -s "Test" your@email.com
```

**3. Controlla configurazione mail:**
```bash
cat /etc/postfix/main.cf
```

### Interfaccia interattiva appare ancora

**1. Verifica parametri omd update:**
```bash
# Controlla nel log se usa -f e --conflict=install
grep "omd update" /var/log/auto-upgrade-checkmk.log
```

**2. Aggiungi protezioni extra** (modifica upgrade-checkmk.sh):
```bash
DEBIAN_FRONTEND=noninteractive omd -f update --conflict=install "$SITE_NAME" < /dev/null
```

## Disinstallazione

### Rimozione Completa
```bash
# 1. Rimuovi entry crontab
crontab -l | grep -v "upgrade-checkmk.sh" | grep -v "^# Auto-upgrade CheckMK:" | crontab -

# 2. Rimuovi log
rm /var/log/auto-upgrade-checkmk.log

# 3. (Opzionale) Rimuovi backup crontab
rm -rf /root/crontab_backups/

# 4. (Opzionale) Rimuovi backup CheckMK vecchi
cd /opt/omd/backups/
rm *_pre-upgrade_*.tar.gz
```

### Sospensione Temporanea
```bash
# Commenta la riga nel crontab (aggiungi # all'inizio)
crontab -e
```

## Esempi di Configurazione

### Setup Conservativo (Produzione)
```
Frequenza: Mensile
Orario: 02:00 domenica notte
Email: Sì
Log: Monitora settimanalmente
Backup: Mantieni ultimi 12 mesi
```

### Setup Bilanciato (Consigliato)
```
Frequenza: Settimanale (domenica)
Orario: 02:00
Email: Sì
Log: Monitora mensilmente
Backup: Mantieni ultimi 3 mesi
```

### Setup Aggressivo (Solo Development)
```
Frequenza: Settimanale (qualsiasi giorno)
Orario: 03:00
Email: Opzionale
Log: Controlla se fallisce
Backup: Mantieni ultimo mese
```

## Integrazione con Monitoring

### CheckMK Self-Monitoring
Crea un check locale per monitorare gli upgrade automatici:

```bash
# /usr/lib/check_mk_agent/local/check_auto_upgrade
#!/bin/bash
LOG_FILE="/var/log/auto-upgrade-checkmk.log"
LAST_RUN=$(grep "upgrade completed successfully" "$LOG_FILE" | tail -1)
DAYS_AGO=$(( ($(date +%s) - $(date -d "$(echo "$LAST_RUN" | cut -d']' -f1 | tr -d '[')" +%s)) / 86400 ))

if [ $DAYS_AGO -gt 14 ]; then
    echo "1 CheckMK_Auto_Upgrade - Last successful upgrade: $DAYS_AGO days ago"
elif [ $DAYS_AGO -gt 7 ]; then
    echo "1 CheckMK_Auto_Upgrade - Last successful upgrade: $DAYS_AGO days ago"
else
    echo "0 CheckMK_Auto_Upgrade - Last successful upgrade: $DAYS_AGO days ago"
fi
```

## Sicurezza e Responsabilità

###  Disclaimer
- Gli upgrade automatici comportano rischi intrinseci
- Testa sempre in ambiente di staging prima
- Mantieni backup esterni e indipendenti
- Monitora attivamente il sistema post-upgrade
- Preparati a interventi manuali in caso di problemi

###  Raccomandazioni di Sicurezza
1. **Backup esterni** oltre a quelli automatici
2. **Ambiente di test** per validare upgrade
3. **Documentazione** delle configurazioni custom
4. **Piano di rollback** testato e documentato
5. **Contatti reperibili** durante finestre di upgrade
6. **Monitoraggio attivo** post-upgrade

## Supporto e Contributi

- **Repository:** https://github.com/Coverup20/checkmk-tools
- **Issues:** https://github.com/Coverup20/checkmk-tools/issues
- **Documentazione:** `script-tools/doc/`

## Changelog

### Version 1.0 (2026-01-12)
- Release iniziale
- Menu interattivo con opzioni di frequenza
- Notifiche email opzionali
- Logging completo
- Backup automatici
- Upgrade completamente non-interattivo
- Gestione duplicati crontab
- Validazione input

## Licenza

Questo script fa parte del progetto checkmk-tools.

## Note Finali

 **IMPORTANTE:**
- Questo è uno strumento potente ma potenzialmente pericoloso
- Usalo SOLO se comprendi completamente i rischi
- Per sistemi critici, considera upgrade manuali con test preventivi
- Gli upgrade possono richiedere riavvii del server
- Non tutti gli upgrade sono backward-compatible

 **QUANDO USARLO:**
- Ambienti di sviluppo/test
- Sistemi non critici
- Con monitoring attivo e alerting
- Con backup esterni robusti
- Quando hai competenza per gestire problemi

 **QUANDO NON USARLO:**
- Sistemi critici di produzione senza test
- Se non hai familiarità con CheckMK
- Senza piano di disaster recovery
- Senza possibilità di intervento rapido
- In ambienti con SLA stringenti

 **RISORSE UTILI:**
- [CheckMK Official Documentation](https://docs.checkmk.com/)
- [OMD Update Guide](https://docs.checkmk.com/latest/en/update.html)
- [CheckMK Backup/Restore](https://docs.checkmk.com/latest/en/backup.html)
