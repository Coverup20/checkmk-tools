# 🚀 CheckMK Email Real IP + Grafici - Deploy Production Guide

## 📋 PREPARAZIONE COMPLETA

La soluzione è pronta per il deployment in produzione. Tutti i file necessari sono stati creati e testati.

### 📁 File Disponibili

| File | Descrizione | Uso |
|------|-------------|-----|
| `mail_realip_graphs` | Script principale produzione | ⭐ **PRINCIPALE** |
| `deploy-mail-realip-graphs.sh` | Script automatico deployment | 🚀 **AUTO DEPLOY** |
| `checkmk-host-labels-config.md` | Guida configurazione label | 📖 **CONFIGURAZIONE** |
| `test-staging-guide.ps1` | Guida test staging | 🧪 **TEST** |
| `backup-existing-config.ps1` | Backup configurazione | 💾 **BACKUP** |
| `README_mail_realip_graphs.md` | Documentazione completa | 📚 **DOCS** |

## 🎯 DEPLOYMENT PRODUCTION - METODO RAPIDO

### Opzione A: Deployment Automatico (Raccomandato)

```bash
# 1. Rendere eseguibile lo script di deploy
chmod +x deploy-mail-realip-graphs.sh

# 2. Eseguire deployment automatico
./deploy-mail-realip-graphs.sh
```

Lo script guiderà attraverso:
- ✅ Configurazione parametri
- ✅ Backup automatico
- ✅ Installazione script
- ✅ Configurazione guidata
- ✅ Test completi

### Opzione B: Deployment Manuale

Se preferisci il controllo completo:

#### 1. Backup Configurazione Esistente
```powershell
# Da Windows/PowerShell
.\backup-existing-config.ps1
```

#### 2. Copia Script su Server
```bash
# Copiare script sul server CheckMK
scp mail_realip_graphs user@checkmk-server:/tmp/
```

#### 3. Installazione Script
```bash
# Su server CheckMK
sudo cp /tmp/mail_realip_graphs /opt/omd/sites/SITENAME/local/share/check_mk/notifications/
sudo chmod +x /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_graphs
sudo chown SITENAME:SITENAME /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_graphs
```

#### 4. Configurazione Label Host
Seguire guida: `checkmk-host-labels-config.md`

#### 5. Configurazione Regola Notifica
1. Setup → Notifications → Add rule
2. Method: Custom notification script  
3. Script: `mail_realip_graphs`
4. Configurare parametri email normalmente

#### 6. Test e Validazione
```bash
# Test manuale
su - SITENAME
export NOTIFY_CONTACTEMAIL="test@domain.com"
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100"
# ... altre variabili test
./local/share/check_mk/notifications/mail_realip_graphs
```

## ✅ CHECKLIST DEPLOYMENT

### Pre-Deployment
- [ ] Backup configurazione esistente completato
- [ ] Server CheckMK accessibile via SSH
- [ ] Permessi amministrativi disponibili
- [ ] Email test configurata

### Durante Deployment  
- [ ] Script `mail_realip_graphs` copiato e installato
- [ ] Permessi file corretti (executable)
- [ ] Label `real_ip` configurato nell'host
- [ ] Regola notifica configurata per nuovo script

### Post-Deployment
- [ ] Test notifica manuale inviato
- [ ] Email ricevuta con real IP verificata
- [ ] Grafici allegati presenti e funzionanti
- [ ] Link grafici puntano al real IP
- [ ] Nessun errore nei log CheckMK

## 🔍 VALIDAZIONE RISULTATI

### Email Corrette Devono Contenere:
✅ **URL con real IP**: `https://192.168.1.100/site/check_mk/...`  
✅ **Grafici allegati**: File PNG con grafici CheckMK  
✅ **Link grafici funzionanti**: Accessibili tramite real IP  
✅ **Zero riferimenti a 127.0.0.1**: Completamente eliminati  

### Email Scorrette (da correggere):
❌ URL con `127.0.0.1`  
❌ Nessun grafico allegato  
❌ Link grafici non funzionanti  
❌ Errori script nei log  

## 🛠️ TROUBLESHOOTING

### Problema: Script non trovato
**Soluzione:**
```bash
# Verificare installazione
ls -la /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_graphs

# Reinstallare se necessario
sudo cp /tmp/mail_realip_graphs /opt/omd/sites/SITENAME/local/share/check_mk/notifications/
sudo chmod +x /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_graphs
```

### Problema: Label real_ip non trovato
**Soluzione:**
1. Verificare configurazione label in Web UI
2. Controllare sintassi: Key=`real_ip`, Value=`IP_REALE`
3. Attivare modifiche in CheckMK

### Problema: Email ancora con 127.0.0.1
**Soluzione:**
1. Verificare regola notifica usa script `mail_realip_graphs`
2. Controllare priorità regole notifica
3. Verificare label host applicato correttamente

### Problema: Nessun grafico nelle email
**Soluzione:**
1. Verificare parametro `PARAMETER_ELEMENTSS` contiene `graph`
2. Controllare servizio CheckMK graphs funzionante
3. Verificare permessi accesso `ajax_graph_images.py`

## 📊 MONITORAGGIO POST-DEPLOYMENT

### Log da Monitorare
```bash
# Log notifiche generale
tail -f /opt/omd/sites/SITENAME/var/log/notify.log

# Log specifico nuovo script
grep "MAIL REALIP WITH GRAPHS" /opt/omd/sites/SITENAME/var/log/notify.log

# Errori CheckMK
tail -f /opt/omd/sites/SITENAME/var/log/web.log
```

### Metriche da Verificare
- **Tempo invio email**: Dovrebbe rimanere simile a prima
- **Dimensione email**: Aumenterà per presenza grafici
- **Successo delivery**: Verificare nessun errore SMTP
- **Accessibilità grafici**: URL real IP raggiungibili

## 🔄 ROLLBACK (Se Necessario)

Se ci sono problemi con il nuovo script:

```bash
# 1. Ripristinare script originale dal backup
scp backup_TIMESTAMP/mail_realip_00_backup user@server:/tmp/
ssh user@server "sudo cp /tmp/mail_realip_00_backup /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_00"

# 2. Modificare regola notifica per usare script originale
# Via Web UI: Setup → Notifications → Modifica regola

# 3. Attivare modifiche
# Via Web UI: Activate changes
```

## 🎉 SUCCESSO DEPLOYMENT

Dopo deployment riuscito avrai:

### ✅ Benefici Ottenuti
1. **Real IP completo**: Nessun più 127.0.0.1 nelle email
2. **Grafici funzionanti**: Allegati e accessibili
3. **URL corretti**: Tutti puntano al real IP
4. **Compatibilità**: Funziona con tutte le funzionalità CheckMK
5. **Robustezza**: Gestione errori migliorata

### 📈 Miglioramenti vs mail_realip_00
- ✅ **Real IP**: Mantenuto (come prima)  
- ✅ **Grafici**: **ABILITATI** (vs disabilitati prima)  
- ✅ **Funzionalità**: Complete (vs limitate prima)  
- ✅ **Manutenzione**: Più semplice (codice più chiaro)  

## 📞 SUPPORTO

### In caso di problemi:
1. **Controllare log**: `/opt/omd/sites/SITENAME/var/log/notify.log`
2. **Verificare configurazione**: Label host e regole notifica
3. **Test manuale**: Usare script test per debug
4. **Rollback**: Ripristinare configurazione originale se necessario

### File di supporto disponibili:
- 📖 `README_mail_realip_graphs.md` - Documentazione completa
- 🧪 `test-staging-guide.ps1` - Guida test dettagliata  
- 💾 `backup-existing-config.ps1` - Script backup
- 🔧 `checkmk-host-labels-config.md` - Configurazione label

---

## 🏆 CONGRATULAZIONI!

Hai ora una soluzione completa che risolve **ENTRAMBI** i problemi:
- ✅ **Real IP** nelle email invece di 127.0.0.1
- ✅ **Grafici completamente funzionanti** invece che disabilitati

La tua configurazione CheckMK è ora **ottimizzata e professionale**! 🎉