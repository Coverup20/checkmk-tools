# 📧 Email Notification Scripts con Real IP e Grafici

Questa cartella contiene script di notifica email migliorati per CheckMK che risolvono il problema delle email che mostrano `127.0.0.1` invece dell'IP reale del server, mantenendo i grafici abilitati.

## 🔍 Problema Risolto

**Problema originale**: 
- Le email di CheckMK mostrano `127.0.0.1` nei link e grafici
- Lo script `mail_realip_00` risolve l'IP ma **disabilita i grafici**
- Serve una soluzione che mantenga **ENTRAMBI**: real IP + grafici

## 📁 Script Disponibili

### 1. `mail_realip_graphs` ⭐ **[RACCOMANDATO]**
**Script finale ottimizzato per produzione**

**Caratteristiche:**
- ✅ Usa real IP dai label host per tutti gli URL
- ✅ Mantiene i grafici **COMPLETAMENTE ABILITATI**
- ✅ Integrazione completa con CheckMK
- ✅ Gestione errori robusta
- ✅ Backward compatibility

**Differenze da `mail_realip_00`:**
- **NON disabilita i grafici** (rimuove `_no_graphs`)
- Usa real IP per generazione URL grafici
- Mantiene tutte le funzionalità email HTML

### 2. `mail_realip_graphs_enhanced`
**Versione avanzata con patch dinamiche**

**Caratteristiche:**
- 🔧 Patch dinamiche delle funzioni utils
- 🔧 Gestione temporanea modifiche contesto
- 🔧 Ripristino automatico funzioni originali
- ⚠️ Più complesso, per uso avanzato

### 3. `mail_realip_with_graphs`
**Prima versione di test e sviluppo**

**Caratteristiche:**
- 🧪 Versione proof-of-concept
- 🧪 Logica base per real IP + grafici
- ⚠️ Non ottimizzata per produzione

## 🚀 Installazione

### 1. Preparazione Host Labels
**IMPORTANTE**: Il server deve avere il label `real_ip` configurato:

```bash
# Su CheckMK Server - aggiungere label all'host
# Host Properties → Labels → Add Label:
# Key: real_ip
# Value: <IP_PUBBLICO_REALE>
```

### 2. Installazione Script
```bash
# 1. Copiare script sul server CheckMK
sudo cp mail_realip_graphs /opt/omd/sites/SITENAME/local/share/check_mk/notifications/

# 2. Rendere eseguibile
sudo chmod +x /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_graphs

# 3. Cambio proprietario
sudo chown SITENAME:SITENAME /opt/omd/sites/SITENAME/local/share/check_mk/notifications/mail_realip_graphs
```

### 3. Configurazione CheckMK
1. **Setup → Notifications → Add rule**
2. **Method of notification → HTML Email**
3. **Plugin → Notification plugins → Custom plugins**
4. **Selezionare: `mail_realip_graphs`**
5. **Configurare parametri email normalmente**
6. **Salvare e attivare configurazione**

## 🔧 Configurazione Avanzata

### Labels Host Supportati
Lo script cerca questi label (in ordine di priorità):
1. `real_ip` ⭐ **[RACCOMANDATO]**
2. `external_ip`
3. `public_ip`

### Debug e Troubleshooting
Lo script genera log dettagliati:
```bash
# Visualizzare log notifiche
tail -f /opt/omd/sites/SITENAME/var/log/notify.log

# Log specifico script
grep "MAIL REALIP WITH GRAPHS" /opt/omd/sites/SITENAME/var/log/notify.log
```

### Test Script
```bash
# Test manuale (come utente site)
su - SITENAME
export NOTIFY_CONTACTEMAIL="test@domain.com"
export NOTIFY_HOSTNAME="test-server"
export NOTIFY_HOSTLABEL_real_ip="1.2.3.4"
export NOTIFY_WHAT="HOST"
export NOTIFY_NOTIFICATIONTYPE="PROBLEM"

./local/share/check_mk/notifications/mail_realip_graphs
```

## 🔍 Come Funziona

### 1. Estrazione Real IP
```python
def get_real_ip_from_context(context: Dict[str, str]) -> Optional[str]:
    # CheckMK espone i label come NOTIFY_HOSTLABEL_<nome_label>
    real_ip = context.get("HOSTLABEL_real_ip")
    return real_ip
```

### 2. Modifica Contesto
```python
def modify_monitoring_host(context: Dict[str, str]) -> str:
    real_ip = get_real_ip_from_context(context)
    if real_ip:
        context["MONITORING_HOST"] = real_ip  # ← Chiave del successo!
        return real_ip
```

### 3. Generazione URL
- **URL host/service**: Usa real IP per navigazione web
- **URL grafici**: Usa real IP per `ajax_graph_images.py`
- **Link email**: Tutti puntano al real IP

### 4. Grafici Abilitati
**DIFFERENZA PRINCIPALE da `mail_realip_00`:**
```python
# mail_realip_00 (DISABILITA grafici):
def _no_graphs(context):
    return []  # ← Nessun grafico!

# mail_realip_graphs (ABILITA grafici):
def patched_render_performance_graphs(context):
    return render_performance_graphs(context)  # ← Grafici completi!
```

## 📊 Confronto Script

| Feature | `mail_realip_00` | `mail_realip_graphs` |
|---------|------------------|---------------------|
| Real IP | ✅ | ✅ |
| Grafici | ❌ **DISABILITATI** | ✅ **ABILITATI** |
| URL corretti | ✅ | ✅ |
| Integrazione CheckMK | ✅ | ✅ |
| Produzione ready | ✅ | ✅ |

## 🆘 Troubleshooting

### Problema: "Real IP non trovato"
**Soluzione:**
```bash
# Verificare label host
cmk-update-host-labels

# Controllare configurazione host
grep -r "real_ip" /opt/omd/sites/SITENAME/etc/check_mk/conf.d/
```

### Problema: "Grafici non generati" 
**Soluzione:**
```bash
# Verificare accesso ajax_graph_images.py
curl "http://localhost/SITENAME/check_mk/ajax_graph_images.py?host=HOSTNAME&service=_HOST_&num_graphs=1"

# Controllare permessi
ls -la /opt/omd/sites/SITENAME/local/share/check_mk/notifications/
```

### Problema: "Email non inviate"
**Soluzione:**
```bash
# Test invio email base
echo "test" | mail -s "Test" test@domain.com

# Verificare configurazione SMTP CheckMK
grep -r "smtp" /opt/omd/sites/SITENAME/etc/check_mk/
```

## ✅ Risultati Attesi

Dopo l'installazione corretta:

1. **Email con real IP**: Tutti i link puntano a `https://REAL_IP/SITE/check_mk/...`
2. **Grafici inclusi**: Le email contengono immagini grafici generate
3. **URL grafici corretti**: I link "View graph" usano real IP
4. **Nessun 127.0.0.1**: Eliminato completamente dalle email

## 🔄 Migrazione da mail_realip_00

Se usi già `mail_realip_00`:

1. **Backup configurazione attuale**
2. **Sostituire script** con `mail_realip_graphs`
3. **Testare notifica**
4. **Verificare grafici attivi** nelle email ricevute

## 📞 Supporto

Per problemi o miglioramenti:
- Controllare log CheckMK dettagliati
- Verificare label host configurati
- Testare script manualmente
- Controllare permessi file e directory

---

**💡 Tip**: Usa `mail_realip_graphs` come sostituzione completa di `mail_realip_00` per avere real IP + grafici in un unico script ottimizzato!