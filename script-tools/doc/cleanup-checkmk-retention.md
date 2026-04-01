# Cleanup Retention CheckMK - Guida Installazione
> **Categoria:** Operativo

##  Descrizione

Script automatico per gestione retention dati CheckMK:
- **180 giorni** per file RRD (metriche performance P4P)
- **180 giorni** per archivi Nagios (con compressione dopo 30 giorni)
- **30 giorni** per backup notifiche (con compressione dopo 1 giorno)

##  Installazione

### 1. Copia lo script sul server CheckMK

```bash
# Su server CheckMK (come utente monitoring)
cd /omd/sites/monitoring/local/bin
wget https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh
chmod +x cleanup-checkmk-retention.sh
```

### 2. Test in modalità DRY-RUN (senza modifiche)

```bash
# Verifica cosa verrebbe eliminato senza modificare nulla
DRY_RUN=true ./cleanup-checkmk-retention.sh
```

### 3. Esecuzione manuale (prima volta)

```bash
# Esegui cleanup reale
./cleanup-checkmk-retention.sh
```

### 4. Configurazione cron automatico

```bash
# Modifica crontab utente monitoring
crontab -e

# Aggiungi questa riga (esecuzione giornaliera alle 2:00 AM)
0 2 * * * /omd/sites/monitoring/local/bin/cleanup-checkmk-retention.sh >> /omd/sites/monitoring/var/log/cleanup-retention-cron.log 2>&1
```

##  Configurazione Personalizzata

Puoi modificare i parametri via variabili d'ambiente:

```bash
# Cambia retention a 90 giorni per RRD
RETENTION_RRD=90 ./cleanup-checkmk-retention.sh

# Comprimi dopo 7 giorni invece di 30
COMPRESS_AFTER=7 RETENTION_NAGIOS=180 ./cleanup-checkmk-retention.sh

# Site diverso da "monitoring"
OMD_SITE=cmk ./cleanup-checkmk-retention.sh
```

##  Output e Log

Lo script genera log dettagliati in:
```
/omd/sites/monitoring/var/log/cleanup-retention.log
```

Esempio output:
```
[2026-01-22 16:30:00] [INFO] CLEANUP FILE RRD (retention: 180 giorni)
[2026-01-22 16:30:05] [OK] RRD eliminati: 245 file
[2026-01-22 16:30:05] [OK] Spazio liberato: 156MB
[2026-01-22 16:30:10] [OK] File compressi: 89
[2026-01-22 16:30:10] [OK] Spazio risparmiato: 1.2GB
```

##  Risultati Attesi

**Prima del cleanup** (stato attuale):
- Totale: 8.4 GB
- RRD: 1.8 GB
- Nagios: 4.6 GB
- Notify: 582 MB

**Dopo cleanup** (stima):
- Totale: ~4.3-4.8 GB
- RRD: ~900 MB (eliminati file >180 giorni)
- Nagios: ~1.4-1.8 GB (compressi 30-180 giorni, eliminati >180 giorni)
- Notify: ~120 MB (compressi 1-30 giorni, eliminati >30 giorni)

**Risparmio**: ~43-50% (3.6-4.1 GB liberati)

##  Note Importanti

1. **Backup prima dell'uso**: Il primo cleanup può eliminare molti dati. Fai un backup completo prima.

2. **File RRD non recuperabili**: I file RRD eliminati non possono essere ripristinati. Le metriche storiche oltre 180 giorni saranno perse definitivamente.

3. **Compressione incrementale**: La compressione dopo 30 giorni riduce lo spazio ma i file restano accessibili.

4. **Frequenza esecuzione**: Raccomandato giornaliero (di notte) per evitare accumulo.

##  Troubleshooting

### Script non elimina nulla
```bash
# Verifica permessi
ls -la /omd/sites/monitoring/var/nagios
ls -la /omd/sites/monitoring/var/pnp4nagios

# Verifica ownership
stat /omd/sites/monitoring/local/bin/cleanup-checkmk-retention.sh
```

### Errore "Site non trovato"
```bash
# Verifica nome site
omd sites

# Usa site corretto
OMD_SITE=tuosite ./cleanup-checkmk-retention.sh
```

### Log non viene creato
```bash
# Verifica cartella log esista
mkdir -p /omd/sites/monitoring/var/log
chmod 755 /omd/sites/monitoring/var/log
```

##  Monitoraggio

Monitora lo spazio disco con:
```bash
# Dimensioni attuali
du -sh /omd/sites/monitoring/var/{nagios,pnp4nagios,notify-backup}

# Conta file RRD
find /omd/sites/monitoring/var/pnp4nagios -name "*.rrd" | wc -l

# File più vecchi
find /omd/sites/monitoring/var/nagios -type f -printf "%T@ %p\n" | sort -n | head -5
```

##  Aggiornamento Script

```bash
cd /omd/sites/monitoring/local/bin
wget -O cleanup-checkmk-retention.sh https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh
chmod +x cleanup-checkmk-retention.sh
```
