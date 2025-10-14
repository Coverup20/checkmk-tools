# 🎯 mail_realip_hybrid - Soluzione FRP-Aware

**Script ibrido per risolvere il dilemma CheckMK: Real IP OR Grafici → Real IP AND Grafici**

## 🎯 **PROBLEMA RISOLTO**

### Scenario PRO (VPS + FRP):
```
CheckMK VPS (pubblico)
    ↕️ FRP Tunnel (porta SSH/custom)
CheckMK Local / Host (privato)
    ↕️ LAN
Host monitorati (192.168.x.x)
```

**Dilemma originale confermato dal codice CheckMK ufficiale:**
- ✅ **Grafici funzionanti** (127.0.0.1:PORT via FRP) + ❌ **Email con localhost**
- ✅ **Email con real IP** (192.168.1.100) + ❌ **Grafici rotti** (non raggiungibili)

### 🔍 **Evidenze Repository CheckMK**

La ricerca nel repository ufficiale CheckMK ha rivelato che:

1. **`render_cmk_graphs()`** in `cmk/notification_plugins/utils.py` usa **sempre**:
   ```python
   f"http://localhost:{site.get_apache_port(omd_root)}/{site}/check_mk/ajax_graph_images.py"
   ```

2. **Non esiste gestione nativa** per reverse proxy/FRP nelle notifiche email

3. Il conflitto tra **localhost** (grafici) e **real IP** (URL) è **architetturale**

4. La nostra soluzione **dual IP handling** è l'unico approccio possibile

## 🚀 **SOLUZIONE IBRIDA**

### 🧠 **Intelligenza Automatica:**
Lo script **rileva automaticamente** lo scenario:

1. **FRP Scenario** (VPS + tunneling):
   - `HOSTADDRESS` = `127.0.0.1:PORT` o `localhost:PORT`
   - Label `real_ip` presente
   - **→ Modalità IBRIDA attivata**

2. **Standard Scenario** (Basic/Medium):
   - `HOSTADDRESS` = IP diretto
   - **→ Comportamento classico**

### ⚙️ **Logica Ibrida:**

```python
# SCENARIO FRP RILEVATO:
if is_frp_scenario and real_ip:
    # 1. Grafici: Usa 127.0.0.1:PORT (funziona via FRP)
    graphs_address = "127.0.0.1:7999"  # Mantiene connessione FRP
    
    # 2. Email URL: Usa real_ip (pubblicamente accessibili)
    email_links = "https://192.168.1.100/site/check_mk/..."
    
    # → ENTRAMBI FUNZIONANTI! 🎉
```

## 📋 **INSTALLAZIONE**

### 1. **Prerequisiti:**
```bash
# Host deve avere label real_ip configurato
# Setup → Hosts → [Host] → Host labels → Add label:
# Key: real_ip
# Value: 192.168.1.100  # IP pubblico reale
```

### 2. **Deploy Script:**
```bash
# Copia su server CheckMK
scp mail_realip_hybrid user@checkmk-server:/tmp/

# Installa
sudo cp /tmp/mail_realip_hybrid /opt/omd/sites/SITE/local/share/check_mk/notifications/
sudo chmod +x /opt/omd/sites/SITE/local/share/check_mk/notifications/mail_realip_hybrid
sudo chown SITE:SITE /opt/omd/sites/SITE/local/share/check_mk/notifications/mail_realip_hybrid
```

### 3. **Configura Notifica:**
```
Setup → Notifications → Add rule
- Description: "Email Real IP + Grafici FRP"
- Method: Custom notification script  
- Script: mail_realip_hybrid
- Parameters: standard email
```

## 🧪 **TEST SCENARI**

### **Test 1: FRP Scenario** 
```bash
export NOTIFY_HOSTADDRESS="127.0.0.1:7999"
export NOTIFY_HOSTLABEL_real_ip="192.168.1.100" 
export NOTIFY_CONTACTEMAIL="test@domain.com"

./mail_realip_hybrid
# Output atteso:
# FRP Scenario rilevato: True
# MODALITÀ IBRIDA FRP ATTIVATA
# ✅ Email URL useranno: 192.168.1.100
# ✅ Grafici useranno: 127.0.0.1:7999 (via FRP)
```

### **Test 2: Standard Scenario**
```bash
export NOTIFY_HOSTADDRESS="203.0.113.50"
export NOTIFY_HOSTLABEL_real_ip="203.0.113.50"
export NOTIFY_CONTACTEMAIL="test@domain.com"

./mail_realip_hybrid
# Output atteso:
# FRP Scenario rilevato: False
# MODALITÀ STANDARD REAL IP
```

## 📊 **RISULTATI ATTESI**

### ✅ **Email FRP-Aware:**
- **Tutti i link**: `https://192.168.1.100/site/check_mk/...`
- **Grafici allegati**: Funzionanti (generati via 127.0.0.1:PORT)
- **View graph links**: Puntano al real IP pubblico
- **Host status**: Mostra real IP invece di localhost

### 🔧 **Compatibilità:**
- ✅ **Scenario PRO**: FRP + VPS + host privati
- ✅ **Scenario Medium**: Agent diretto
- ✅ **Scenario Basic**: Agentless
- ✅ **Fallback**: Comportamento CheckMK standard se nessun label

## 🆘 **TROUBLESHOOTING**

### **Problema: Script non rileva FRP**
```bash
# Debug variabili
env | grep NOTIFY_HOSTADDRESS
env | grep HOSTLABEL_real_ip

# Verifica pattern FRP
echo $NOTIFY_HOSTADDRESS | grep -E "^127\.0\.0\.1:\d+$"
```

### **Problema: Grafici ancora rotti**
```bash
# Verifica connessione FRP interna
curl -s "http://127.0.0.1:PORT/site/check_mk/" | head -10

# Test generazione grafico manuale  
su - SITE
cmk --debug -v HOSTNAME
```

### **Problema: Email con localhost**
```bash
# Verifica label host
cmk-update-host-labels
grep -r "real_ip" /opt/omd/sites/SITE/etc/check_mk/conf.d/
```

## 🏆 **VANTAGGI CHIAVE**

1. **🎯 Risoluzione Definitiva**: Real IP + Grafici simultaneamente
2. **🧠 Auto-Detection**: Rileva automaticamente scenario FRP vs Standard  
3. **🔄 Backward Compatible**: Funziona anche in scenari non-FRP
4. **⚡ Zero Configuration**: Nessuna configurazione aggiuntiva richiesta
5. **🛡️ Sicuro**: Basato su mail_realip_00 (non modificato)

---

**💡 Tip**: Perfetto per infrastrutture **CheckMK distribuite** con tunneling FRP dove serve accesso sia interno (grafici) che esterno (email pubbliche).