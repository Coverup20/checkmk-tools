# 🚀 QUICK START TESTING GUIDE

## 📋 **Pre-Test Setup (5 minuti)**

### 1. Carica file su server CheckMK
```bash
# SCP/SFTP files to your CheckMK server
scp mail_realip_hybrid backup_and_deploy.sh pre_test_checker.sh user@your-checkmk-server:/tmp/
```

### 2. Connetti al server e prepara ambiente
```bash
ssh user@your-checkmk-server
sudo -i
cd /tmp
chmod +x *.sh
```

### 3. Controllo ambiente
```bash
# Verifica compatibilità
./pre_test_checker.sh
```

---

## 🧪 **Fase Testing (10 minuti)**

### Test 1: Dry Run (sicuro)
```bash
# Simula deployment senza modifiche
./backup_and_deploy.sh --dry-run
```

### Test 2: Deploy con backup automatico
```bash
# Deploy reale con rollback automatico
./backup_and_deploy.sh
```

### Test 3: Verifica detection FRP
```bash
# Switch to CheckMK site user
su - $(cat /etc/omd/site)

# Test detection manuale
python3 -c "
import os, sys
# Simula scenario FRP
os.environ['NOTIFY_HOSTADDRESS'] = '127.0.0.1:5000'  
os.environ['NOTIFY_HOSTLABEL_real_ip'] = '192.168.1.100'
os.environ['NOTIFY_HOSTNAME'] = 'test-host'
os.environ['NOTIFY_WHAT'] = 'HOST'

# Load script
exec(open('/omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications/mail_realip_hybrid').read())
print('Detection OK!')
"
```

---

## 📧 **Test Notifica Reale (15 minuti)**

### 1. Configura host test con label real_ip

**Via WATO:**
1. Setup → Hosts → [Your Host] → Properties  
2. Custom attributes → Add: `real_ip = 192.168.1.100`
3. Save & Activate Changes

**Via config file:**
```bash
# Aggiungi a /etc/check_mk/conf.d/hosts.mk
extra_host_conf.setdefault("_real_ip", []).append(
    ("192.168.1.100", ["test-host"])
)
```

### 2. Configura regola notifica

**WATO:** Setup → Notifications → New Rule:
- **Notification Method:** `mail_realip_hybrid`  
- **Contact Selection:** Your email
- **Host/Service Conditions:** Match your test host

### 3. Test notifica
```bash
# Force notification test
su - $(cat /etc/omd/site)
cmk --notify-test test-host
```

### 4. Monitor risultati
```bash
# Check logs
tail -f /omd/sites/$(cat /etc/omd/site)/var/log/notify.log

# Check email content per:
# ✅ Grafici funzionanti (localhost:PORT usato internamente)
# ✅ URL clickabili con real IP (192.168.1.100)
```

---

## 🔄 **Rollback se necessario**

```bash
# Il deploy automatico crea script rollback
ls /omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications/backup_*/rollback.sh

# Esegui rollback
/omd/sites/$(cat /etc/omd/site)/local/share/check_mk/notifications/backup_*/rollback.sh
```

---

## 📊 **Validation Checklist**

**Dopo il test, verifica:**

- [ ] **Detection FRP:** Log conferma "FRP scenario detected"
- [ ] **Grafici:** Email contiene PNG allegati 
- [ ] **URL Email:** Link puntano a real IP (192.168.1.100)
- [ ] **URL Grafici:** Template interno usa localhost:PORT
- [ ] **No Errori:** notify.log pulito
- [ ] **Rollback:** Funziona se necessario

---

## 🎯 **Expected Results**

**✅ SUCCESS SCENARIO:**
```
EMAIL CONTENT:
- Subject: CheckMK notification
- Body: Text with real IP links (192.168.1.100)  
- Attachments: Graph PNG images
- Graph URL: http://192.168.1.100/site/check_mk/...

LOGS:
- "FRP scenario detected: HOSTADDRESS=127.0.0.1:5000, real_ip=192.168.1.100"
- "Graph generation successful"
- "Email sent successfully"
```

**❌ SE FALLISCE:**
1. Check pre_test_checker.sh warnings
2. Verifica label real_ip configurata
3. Controlla logs notify.log
4. Esegui rollback.sh
5. Report issue con logs specifici

---

## 🔧 **Troubleshooting Rapido**

```bash
# Check script permissions
ls -la /omd/sites/*/local/share/check_mk/notifications/mail_realip_hybrid

# Test Python syntax
python3 -m py_compile /omd/sites/*/local/share/check_mk/notifications/mail_realip_hybrid

# Verify environment variables in notification
env | grep NOTIFY_ | head -10

# Manual debug mode
export PYTHONUNBUFFERED=1
export DEBUG=1
```

---

🚀 **Ready to rock? Inizia con `pre_test_checker.sh`!**