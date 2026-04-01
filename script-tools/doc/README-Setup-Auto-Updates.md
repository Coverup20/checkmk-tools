# Setup Auto-Updates - Configurazione Aggiornamenti Automatici Sistema
> **Categoria:** Operativo

## Descrizione

Script per configurare aggiornamenti automatici del sistema Linux tramite crontab. Permette di pianificare l'esecuzione periodica di `apt update`, `apt full-upgrade` e `apt autoremove` con logging automatico.

## Componenti

### 1. Script Full (Interattivo)
**Path:** `script-tools/full/upgrade_maintenance/setup-auto-updates.sh`

Versione completa con interfaccia interattiva che guida l'utente nella configurazione.

### 2. Remote Launcher
**Path:** `script-tools/remote/rsetup-auto-updates.sh`

Launcher che scarica ed esegue lo script completo direttamente da GitHub.

## Caratteristiche

-  **Menu interattivo** con opzioni predefinite
-  **Backup automatico** del crontab esistente
-  **Logging completo** degli aggiornamenti
-  **Validazione input** per sicurezza
-  **Gestione duplicati** - rimuove entry esistenti
-  **Output colorato** per migliore leggibilità
-  **Personalizzazione orari** flessibile

## Utilizzo

### Esecuzione Locale (Interattiva)

```bash
# Dalla cartella dello script
cd /path/to/script-tools/full
sudo bash setup-auto-updates.sh
```

### Esecuzione Remota

```bash
# Download ed esecuzione in un comando
bash <(curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/remote/rsetup-auto-updates.sh)
```

### Esecuzione da Repository Clonato

```bash
# Se hai clonato il repository
cd script-tools/remote
sudo bash rsetup-auto-updates.sh
```

## Opzioni di Pianificazione

### 1. Giornaliero
- **Frequenza:** Ogni giorno
- **Orario default:** 03:00
- **Cron:** `0 3 * * *`

### 2. Settimanale
- **Frequenza:** Ogni domenica
- **Orario default:** 03:00
- **Cron:** `0 3 * * 0`

### 3. Mensile
- **Frequenza:** 1° giorno del mese
- **Orario default:** 03:00
- **Cron:** `0 3 1 * *`

### 4. Personalizzato
- **Frequenza:** Inserimento manuale
- **Formato:** `minuto ora giorno mese giornosettimana`
- **Esempio:** `30 2 * * 1` (ogni lunedì alle 02:30)

## Menu Interattivo

```
╔════════════════════════════════════════════════════════════════╗
║    Configurazione Aggiornamenti Automatici Sistema            ║
╚════════════════════════════════════════════════════════════════╝

Comando che verrà eseguito:
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y

Seleziona la frequenza degli aggiornamenti automatici:

  1) Giornaliero  - Ogni giorno alle 03:00
  2) Settimanale  - Ogni domenica alle 03:00
  3) Mensile      - Il primo giorno del mese alle 03:00
  4) Personalizzato - Specifica orario e frequenza custom
  5) Annulla

Scelta [1-5]:
```

## Esempi di Configurazioni Personalizzate

### Ogni 6 ore
```
Pianificazione cron: 0 */6 * * *
```

### Ogni lunedì alle 02:30
```
Pianificazione cron: 30 2 * * 1
```

### Due volte al giorno (02:00 e 14:00)
```
Prima entry: 0 2 * * *
Seconda entry: 0 14 * * *
```

### Primo e quindicesimo del mese
```
Pianificazione cron: 0 3 1,15 * *
```

## File di Log

### Posizione
```
/var/log/auto-updates.log
```

### Formato Log
```
[Sun Jan 12 03:00:01 2026] Starting system updates
Hit:1 http://archive.ubuntu.com/ubuntu jammy InRelease
...
[Sun Jan 12 03:05:23 2026] Updates completed successfully
```

### Monitoraggio in Tempo Reale
```bash
# Visualizzare gli ultimi aggiornamenti
tail -f /var/log/auto-updates.log

# Vedere le ultime 50 righe
tail -n 50 /var/log/auto-updates.log

# Cercare errori
grep -i error /var/log/auto-updates.log
```

## Backup Crontab

### Posizione Backup
```
/root/crontab_backups/
```

### Formato File
```
crontab_backup_YYYYMMDD_HHMMSS.txt
```

### Ripristino Backup
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

### Rimuovere Tutte le Entry
```bash
crontab -r
```

### Rimuovere Solo Auto-Updates
```bash
crontab -l | grep -v "apt update.*apt full-upgrade" | crontab -
```

## Requisiti di Sistema

- **OS:** Linux (Debian/Ubuntu based)
- **Package Manager:** APT
- **Permessi:** Root (sudo)
- **Dipendenze:** bash, cron, curl (per versione remota)

## Verifica Installazione

```bash
# Verifica che cron sia attivo
systemctl status cron

# Verifica entry nel crontab
crontab -l | grep "apt update"

# Test manuale del comando
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y
```

## Troubleshooting

### Entry non viene eseguita

1. Verifica che cron sia attivo:
```bash
systemctl status cron
systemctl start cron
```

2. Controlla i log di sistema:
```bash
grep CRON /var/log/syslog
```

3. Verifica sintassi cron:
```bash
crontab -l
```

### Permessi insufficienti

```bash
# Assicurati di eseguire con sudo
sudo bash setup-auto-updates.sh
```

### Log file non accessibile

```bash
# Verifica permessi
ls -l /var/log/auto-updates.log

# Ricrea il file se necessario
sudo touch /var/log/auto-updates.log
sudo chmod 644 /var/log/auto-updates.log
```

### Script remoto non scaricabile

```bash
# Verifica connessione
curl -I https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/upgrade_maintenance/setup-auto-updates.sh

# Usa versione locale
git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools/script-tools/full
sudo bash setup-auto-updates.sh
```

## Best Practices

### 1. Orario di Esecuzione
- Scegli orari di basso traffico (es. 02:00-04:00)
- Evita orari di lavoro per server di produzione
- Considera il fuso orario del server

### 2. Frequenza Aggiornamenti
- **Server di produzione:** Settimanale o mensile
- **Server di sviluppo:** Giornaliero
- **Workstation:** Settimanale

### 3. Monitoraggio
- Controlla regolarmente i log
- Imposta alert per errori critici
- Verifica spazio disco disponibile

### 4. Backup
- Mantieni backup del crontab
- Testa i ripristini periodicamente
- Documenta le configurazioni custom

### 5. Sicurezza
- Rivedi gli aggiornamenti installati
- Monitora riavvii necessari
- Pianifica maintenance window per kernel updates

## Testing

### Test Manuale Immediato
```bash
# Esegui il comando senza aspettare la schedulazione
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y
```

### Test Dry-Run
```bash
# Simula aggiornamenti senza installarli
sudo apt update
sudo apt list --upgradable
```

### Verifica Next Run
```bash
# Installa at per vedere prossima esecuzione
# (cron non ha un comando nativo per questo)
```

## Disinstallazione

### Metodo 1: Rimozione Manuale
```bash
crontab -e
# Cancella la riga relativa agli auto-updates
```

### Metodo 2: Rimozione Automatica
```bash
crontab -l | grep -v "apt update.*apt full-upgrade" | grep -v "^# Auto-updates:" | crontab -
```

### Pulizia Completa
```bash
# Rimuovi entry crontab
crontab -l | grep -v "apt update.*apt full-upgrade" | crontab -

# Rimuovi log file
sudo rm /var/log/auto-updates.log

# (Opzionale) Rimuovi backup
sudo rm -rf /root/crontab_backups/
```

## Supporto e Contributi

- **Repository:** https://github.com/Coverup20/checkmk-tools
- **Issues:** https://github.com/Coverup20/checkmk-tools/issues
- **Documentazione:** `script-tools/doc/`

## Changelog

### Version 1.0 (2026-01-12)
- Release iniziale
- Menu interattivo con 5 opzioni
- Backup automatico crontab
- Logging completo
- Validazione input
- Gestione duplicati
- Output colorato

## Licenza

Questo script fa parte del progetto checkmk-tools.

## Note Importanti

 **ATTENZIONE:**
- Gli aggiornamenti automatici possono richiedere riavvii
- Monitora sempre i log dopo le prime esecuzioni
- Testa prima su sistemi non critici
- Mantieni backup del sistema aggiornati

 **SUGGERIMENTO:**
- Configura notifiche email per i risultati degli aggiornamenti
- Considera l'uso di `unattended-upgrades` per configurazioni più avanzate
- Integra con sistemi di monitoring esistenti (CheckMK, Nagios, etc.)
