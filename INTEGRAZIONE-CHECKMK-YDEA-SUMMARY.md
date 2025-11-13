# 🎉 Integrazione CheckMK → Ydea Completata

## ✅ File Creati

### **Script di Notifica CheckMK**
📁 `script-notify-checkmk/`
- ✅ **`ydea_realip`** - Script notifica principale (415 righe)
  - Gestione automatica ticket Ydea da alert CheckMK
  - Cache intelligente per prevenire duplicati
  - Note private su cambio stato
  - Rilevamento flapping (5+ cambi in 10 min)
  - Supporto HOST e SERVICE alert

- ✅ **`mail_ydea_down`** - Notifica email Ydea offline (300+ righe)
  - Email HTML professionale
  - Informazioni dettagliate su impatto
  - Basato su mail_realip_hybrid_safe

### **Monitoring Ydea**
📁 `Ydea-Toolkit/`
- ✅ **`ydea-health-monitor.sh`** - Monitor periodico (200 righe)
  - Controllo ogni 15 minuti (configurabile)
  - Soglia 3 fallimenti prima di notificare
  - Email alert + recovery notification
  - State tracking in `/tmp/ydea_health_state.json`

### **Configurazione**
📁 `Ydea-Toolkit/`
- ✅ **`.env`** - Aggiornato con nuove variabili
  - `YDEA_ALERT_EMAIL` per notifiche down
  - `YDEA_FAILURE_THRESHOLD` per soglia errori
  - `DEBUG_YDEA` per troubleshooting

### **Documentazione**
📁 `Ydea-Toolkit/`
- ✅ **`README-CHECKMK-INTEGRATION.md`** - Guida completa (600+ righe)
  - Panoramica sistema
  - Installazione passo-passo
  - Configurazione CheckMK notification rule
  - Setup cron job
  - Test e verifica
  - Troubleshooting dettagliato
  - FAQ completa

- ✅ **`QUICK-REFERENCE.md`** - Riferimento rapido (400+ righe)
  - Comandi utili one-liner
  - Test manuali
  - Debug e log
  - Esempi configurazione
  - Manutenzione cache

- ✅ **`install-ydea-checkmk-integration.sh`** - Installer automatico
  - Verifica prerequisiti
  - Copia script nelle directory corrette
  - Setup .env
  - Configurazione cron
  - Test connessione

- ✅ **`INDEX.txt`** - Aggiornato con nuova sezione CheckMK

---

## 🎯 Funzionalità Implementate

### **Alert CheckMK → Ticket Ydea**
✅ **Creazione automatica ticket** quando servizio/host passa a CRITICAL/DOWN
✅ **Identificazione univoca** per IP/Hostname + Servizio
✅ **Prevenzione duplicati** tramite cache JSON
✅ **Note private** (non visibili al cliente) per ogni cambio stato:
   - CRIT → OK (allarme rientrato)
   - CRIT → WARN
   - Rilevamento flapping
✅ **Formato note sintetico**: `[data ora] 🔴CRIT→🟢OK | Output: descrizione`
✅ **Ticket rimane aperto** (non viene chiuso automaticamente)

### **Flapping Detection**
✅ **Soglia configurabile**: 5 cambi stato in 10 minuti (default)
✅ **Alert speciale** quando rilevato flapping
✅ **Priorità elevata** a critical per ticket con flapping
✅ **Cache separata** per tracking cambi stato

### **Monitoraggio Ydea API**
✅ **Check periodico** ogni 15 minuti (via cron)
✅ **Soglia intelligente**: 3 fallimenti consecutivi prima di notificare
✅ **Email alert** quando Ydea non raggiungibile
✅ **Recovery notification** quando torna online
✅ **State tracking** per evitare notifiche duplicate

### **Cache e Persistenza**
✅ **Ticket cache**: `/tmp/ydea_checkmk_tickets.json`
   - Ticket ID, stato corrente, timestamp creazione/aggiornamento
✅ **Flapping cache**: `/tmp/ydea_checkmk_flapping.json`
   - Storia cambi stato con timestamp
   - Auto-pulizia eventi > 10 minuti
✅ **Health state**: `/tmp/ydea_health_state.json`
   - Stato Ydea, ultimo check, fallimenti consecutivi

---

## 📋 Come Funziona

### **Scenario 1: Nuovo Alert CRITICAL**
```
1. CheckMK rileva servizio CRITICAL
2. Esegue script ydea_realip
3. Script controlla cache: ticket esiste per questo servizio?
4. NO → Crea nuovo ticket Ydea:
   - Titolo: "[🔴 CRIT] 192.168.1.50 - CPU Load"
   - Corpo: Dettagli alert con output plugin
   - Priorità: high (o critical se flapping)
5. Salva ticket ID in cache
```

### **Scenario 2: Alert Rientra (CRIT → OK)**
```
1. CheckMK rileva servizio OK
2. Esegue script ydea_realip
3. Script controlla cache: ticket esiste? SÌ
4. Aggiunge nota privata a ticket esistente:
   "🔄 [13/11/25 14:32] 🔴CRIT→🟢OK | ✅ Allarme rientrato | Output: CPU normal"
5. Ticket rimane APERTO
```

### **Scenario 3: Flapping Rilevato**
```
1. Servizio cambia stato 5 volte in 10 minuti
2. Script rileva pattern flapping
3. Nota privata: "⚠️ FLAPPING (5 cambi in 10min) | Current: CRIT"
4. Se nuovo ticket, priorità → CRITICAL
```

### **Scenario 4: Ydea API Down**
```
1. Cron esegue ydea-health-monitor.sh ogni 15 min
2. Login Ydea fallisce 3 volte consecutive
3. Invia email a massimo.palazzetti@nethesis.it:
   - Subject: "🚨 [ALERT] Ydea API - Servizio Non Raggiungibile"
   - Corpo HTML con dettagli e azioni richieste
4. Continua a monitorare
5. Quando Ydea torna up → Email recovery
```

---

## 🚀 Prossimi Passi per l'Installazione

### **1. Deploy su Server CheckMK**
```bash
# Sul tuo PC Windows, commit e push
cd "C:\Users\Marzio\Desktop\CheckMK\Script"
git add .
git commit -m "feat: Integrazione CheckMK → Ydea ticketing automatico"
git push origin main

# Sul server CheckMK
cd /opt
git clone https://github.com/Coverup20/checkmk-tools.git
cd checkmk-tools

# Esegui installer
sudo chmod +x Ydea-Toolkit/install-ydea-checkmk-integration.sh
sudo ./Ydea-Toolkit/install-ydea-checkmk-integration.sh
```

### **2. Configura Credenziali**
```bash
sudo nano /opt/ydea-toolkit/.env
```
Modifica:
- `YDEA_ID="il_tuo_id"`
- `YDEA_API_KEY="la_tua_chiave"`

### **3. Test Connessione**
```bash
cd /opt/ydea-toolkit
source .env
./ydea-toolkit.sh login
# Output atteso: ✅ Login effettuato
```

### **4. Configura CheckMK Notification Rule**
- Setup → Notifications → Add rule
- Nome: "Ydea Ticketing"
- Script: `ydea_realip`
- Conditions: Service CRIT, Host DOWN

### **5. Verifica Cron**
```bash
crontab -l | grep ydea
# Deve mostrare: */15 * * * * /opt/ydea-toolkit/ydea-health-monitor.sh
```

### **6. Test Completo**
Vedi: `QUICK-REFERENCE.md` → sezione "Test Notifica Manuale"

---

## 📊 Struttura File Finali

```
checkmk-tools/
├── script-notify-checkmk/
│   ├── ydea_realip              ← Script notifica CheckMK
│   ├── mail_ydea_down           ← Email per Ydea offline
│   ├── telegram_realip          ← (esistente)
│   └── mail_realip_hybrid_safe  ← (esistente)
│
└── Ydea-Toolkit/
    ├── ydea-toolkit.sh          ← (esistente) Core API
    ├── ydea-health-monitor.sh   ← NEW: Monitor Ydea
    ├── .env                     ← (aggiornato) Config
    │
    ├── README-CHECKMK-INTEGRATION.md  ← NEW: Guida completa
    ├── QUICK-REFERENCE.md             ← NEW: Reference rapido
    ├── install-ydea-checkmk-integration.sh  ← NEW: Installer
    ├── INDEX.txt                ← (aggiornato)
    │
    └── (altri file esistenti...)
```

---

## 🎓 Documentazione

### **Leggere Subito**
1. 📖 `README-CHECKMK-INTEGRATION.md` - Guida completa
2. 🚀 `QUICK-REFERENCE.md` - Comandi rapidi

### **Per Setup**
3. 🔧 `install-ydea-checkmk-integration.sh` - Installer automatico

### **Per Troubleshooting**
4. 📋 `README-CHECKMK-INTEGRATION.md` → sezione Troubleshooting
5. 🔍 `QUICK-REFERENCE.md` → sezione Debug

---

## 💡 Note Importanti

### **Permessi File**
Tutti gli script devono essere eseguibili:
```bash
chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
chmod +x /omd/sites/monitoring/local/share/check_mk/notifications/mail_ydea_down
chmod +x /opt/ydea-toolkit/ydea-health-monitor.sh
```

### **Cache Permissions**
I file cache devono essere scrivibili:
```bash
chmod 666 /tmp/ydea_checkmk_tickets.json
chmod 666 /tmp/ydea_checkmk_flapping.json
chmod 666 /tmp/ydea_health_state.json
```

### **Line Endings**
Gli script bash hanno attualmente CRLF (Windows). Sul server Linux eseguire:
```bash
dos2unix /omd/sites/monitoring/local/share/check_mk/notifications/ydea_realip
dos2unix /opt/ydea-toolkit/ydea-health-monitor.sh
```
Oppure l'installer lo fa automaticamente.

---

## ✅ Checklist Pre-Produzione

- [ ] Repository committato e pushato su GitHub
- [ ] Script deployati su server CheckMK
- [ ] Credenziali Ydea configurate in `.env`
- [ ] Test login Ydea funzionante
- [ ] Notification rule CheckMK configurata
- [ ] Cron job attivo per health monitor
- [ ] Test manuale notifica OK
- [ ] Email test Ydea down ricevuta
- [ ] Cache inizializzata correttamente
- [ ] Log monitorati e funzionanti

---

## 🎯 Risultato Finale

Hai ora un sistema completo che:

✅ **Automatizza** la creazione ticket Ydea da alert CheckMK  
✅ **Traccia** ogni cambio stato con note private  
✅ **Previene** duplicati con cache intelligente  
✅ **Rileva** servizi in flapping  
✅ **Monitora** la disponibilità di Ydea stesso  
✅ **Notifica** il responsabile se Ydea è down  
✅ **Mantiene** tutto sincronizzato e logging completo  

🎉 **Congratulazioni! Sistema pronto per la produzione!** 🎉

---

**Creato:** 13 Novembre 2025  
**Versione:** 1.0.0  
**Repository:** checkmk-tools  
**Autore:** Integrazione CheckMK-Ydea Toolkit
