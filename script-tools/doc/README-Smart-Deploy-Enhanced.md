#  CheckMK Smart Deploy - Sistema Ibrido Migliorato
> **Categoria:** Operativo

##  **NOVITÀ: Pattern CheckMK Ufficiali Integrati**

Dopo aver analizzato il **repository ufficiale CheckMK** (https://github.com/Checkmk/checkmk), abbiamo integrato i pattern professionali utilizzati da Checkmk GmbH nel nostro sistema:

### **1.  Version Tracking & Metadata**
```bash
# Ogni script ora include metadata automatico (pattern CheckMK)
# CMK_VERSION="1.0.0"
# Auto-deployed via smart-deploy-hybrid
# Last-update: 2025-10-13 15:30:45
```

### **2.  Configuration Management**
```bash
# Variabili ambiente standard CheckMK
MK_CONFDIR="/etc/check_mk"              # Configurazioni
MK_VARDIR="/var/lib/check_mk_agent"     # Dati variabili
CACHE_DIR="/var/cache/checkmk-scripts"  # Cache script
```

### **3.  Error Handling Robusto**
```bash
# Report errori in formato CheckMK standard
report_error() {
    if [ "$SCRIPT_TYPE" = "local" ]; then
        echo "<<<check_mk>>>"
        echo "FailedScript: $SCRIPT_NAME - $error_msg"
    fi
}
```

### **4.  Timeout & Safety**
```bash
# Esecuzione con timeout (pattern CheckMK)
if timeout 30 "$CACHE_FILE" 2>/dev/null; then
    log_info "Script executed successfully"
else
    report_error "Script execution failed"
fi
```

##  **Architettura Sistema**

```
CheckMK Environment
├──  /usr/lib/check_mk_agent/
│   ├── local/          # ← Smart wrappers (auto-update)
│   ├── plugins/        # ← Plugin scripts
│   └── spool/          # ← Spool scripts (cache-based)
├──  /var/cache/checkmk-scripts/
│   ├── *.sh           # ← Script cache (GitHub download)
│   ├── update-all.sh  # ← Manual update script
│   ├── check-status.sh # ← Health check script
│   └── deployment_status.json # ← Status tracking
└──  /etc/check_mk/
    └── *.cfg          # ← Configuration files
```

##  **Funzionalità Principali**

### **Auto-Update Intelligente**
-  Download automatico da GitHub (timeout 5s)
-  Validazione script (shebang check)
-  Fallback su cache locale
-  Error reporting in formato CheckMK

### **Health Monitoring**
-  Status check automatico post-deployment
-  Conteggio script funzionanti/falliti
-  JSON status per monitoring
-  Log debug configurabile

### **Maintenance Tools**
-  Script aggiornamento manuale (`update-all.sh`)
-  Health check script (`check-status.sh`)
-  Deployment status JSON
-  Version tracking per script

##  **Utilizzo**

### **Deploy Iniziale**
```bash
sudo ./smart-deploy-hybrid.sh
```

### **Verifica Status**
```bash
/var/cache/checkmk-scripts/check-status.sh
```

### **Aggiornamento Manuale**
```bash
/var/cache/checkmk-scripts/update-all.sh
```

### **Debug Mode**
```bash
DEBUG=true ./smart-deploy-hybrid.sh
```

##  **Output Esempio**

```
 CheckMK Smart Deploy - Sistema Ibrido
  Environment: Agent Client
 Cache: /var/cache/checkmk-scripts

 Deploying scripts...
 Processing check_cockpit_sessions (type: local)...
 Cache iniziale per check_cockpit_sessions creata
 Creando wrapper smart per check_cockpit_sessions (local)...
 Wrapper check_cockpit_sessions creato in /usr/lib/check_mk_agent/local

 Checking local plugins in /usr/lib/check_mk_agent/local...
 local: 5 total, 5 working, 0 errors

 Setup completed successfully!
 Run '/var/cache/checkmk-scripts/check-status.sh' to verify status
 Run '/var/cache/checkmk-scripts/update-all.sh' to manually update all scripts
```

##  **Innovazioni dal Repository CheckMK**

### **1. Plugin Detection Logic**
```bash
# CheckMK usa questo pattern per rilevare plugin Python
get_plugin_interpreter() {
    if [ "${extension}" != "py" ]; then
        return 0  # Execute as shell script
    fi
    
    if [ -n "${PYTHON3}" ]; then
        echo "${PYTHON3}"
    fi
}
```

### **2. Section Output Format**
```bash
# Format standard per output CheckMK
echo "<<<section_name:sep(0)>>>"  # JSON data
echo "<<<section_name>>>"         # Key-value data
```

### **3. Version Management**
```bash
# Pattern versioning automatico
script_version=$(grep -e '^__version__' -e '^CMK_VERSION' "${script}")
```

### **4. Error Reporting Standard**
```bash
# Report errori in sezione check_mk
echo "<<<check_mk>>>"
echo "FailedPythonPlugins: $plugin_name"
```

##  **Vantaggi del Sistema Migliorato**

1. ** Monitoring Integrato**: Status check automatico come CheckMK ufficiale
2. ** Maintenance Tools**: Script di utilità per gestione quotidiana
3. ** Error Handling**: Report errori in formato CheckMK standard
4. ** Performance**: Timeout e validazione per evitare hang
5. ** Tracking**: Version e deployment tracking completo
6. ** Auto-Healing**: Fallback automatico su cache locale
7. ** Debug Support**: Logging dettagliato configurabile

##  **Conclusione**

Il sistema ora segue **fedelmente i pattern dell'architettura CheckMK ufficiale**, garantendo:
-  Compatibilità totale con l'ecosistema CheckMK
-  Robustezza enterprise-grade
-  Facilità di manutenzione e debug
-  Scalabilità per ambienti complessi

**Il tuo sistema ibrido è ora allineato con gli standard professionali di Checkmk GmbH!** 