# CheckMK Smart Deploy - Sistema Ibrido

## 📁 **File nel Sistema:**

- **`smart-deploy-hybrid.sh`** - 🚀 **Installatore principale** (questo è quello che usi!)
- **`smart-wrapper-template.sh`** - � **Template base** (struttura del wrapper che viene replicata)
- **`README-Smart-Deploy.md`** - 📚 **Documentazione** (questo file)

## 🎯 **Cos'è**

Un sistema intelligente che combina:
- **📥 Download da GitHub** per avere sempre l'ultima versione
- **💾 Cache locale** per funzionare anche senza internet
- **🔄 Auto-update** trasparente ad ogni esecuzione CheckMK

## 🚀 **Come Funziona**

### **1. Deploy Iniziale**
```bash
# Sul server target
curl -s https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-Tools/smart-deploy-hybrid.sh | sudo bash
```

### **2. Struttura Creata**
```
/usr/lib/check_mk_agent/local/
├── check_cockpit_sessions      # Wrapper smart
├── check_dovecot_status        # Wrapper smart  
├── check_ssh_root_sessions     # Wrapper smart
└── check_postfix_status        # Wrapper smart

/var/cache/checkmk-scripts/
├── check_cockpit_sessions.sh   # Cache locale
├── check_dovecot_status.sh     # Cache locale
├── update-all.sh               # Script manutenzione
└── *.info                      # Info aggiornamenti
```

### **3. Logica di Esecuzione**
```
CheckMK esegue script → Wrapper prova GitHub → Success? Aggiorna cache → Esegue cache locale
                                           ↓
                                         Fail? → Usa cache esistente
```

## 🎯 **Vantaggi**

- ✅ **Sempre aggiornato** (quando c'è internet)
- ✅ **Sempre funzionante** (anche senza internet)  
- ✅ **Zero manutenzione** (auto-update trasparente)
- ✅ **Fallback robusto** (cache locale sicura)
- ✅ **Deploy rapido** (un comando su tutti i server)

## 🔧 **Comandi Utili**

### **Test Manuale**
```bash
# Testa un singolo script
/usr/lib/check_mk_agent/local/check_cockpit_sessions

# Forza aggiornamento di tutti
/var/cache/checkmk-scripts/update-all.sh
```

### **Debug**
```bash
# Vedi cache
ls -la /var/cache/checkmk-scripts/

# Vedi info ultimo aggiornamento  
cat /var/cache/checkmk-scripts/check_cockpit_sessions.sh.info

# Test download manuale
curl -s https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-check-ns7/check_cockpit_sessions.sh
```

## 📊 **Monitoraggio**

Gli script self-report se non riescono ad aggiornarsi:
```
2 check_cockpit_sessions - CRITICAL: No script available (GitHub unreachable, no cache)
```

## 🛠️ **Manutenzione**

### **Aggiungere Nuovo Script**
1. Pusha lo script su GitHub
2. Modifica `smart-deploy-hybrid.sh` aggiungendo alla lista `SCRIPTS`
3. Ri-esegui il deploy

### **Rimuovere Script**
```bash
rm /usr/lib/check_mk_agent/local/nome_script
rm /var/cache/checkmk-scripts/nome_script.*
```

## 🎉 **Il Meglio dei Due Mondi**

- **Aggiornamenti automatici** come il tuo collega
- **Stabilità** dei file locali tradizionali
- **Zero single point of failure**