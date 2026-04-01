# CheckMK Agent - ROCKSOLID Installation Guide
> **Categoria:** Operativo

##  Problema Risolto

Durante un **major upgrade** di NethSecurity/OpenWrt (es. 8.7.0 → .8.7.1), il sistema ripristina il firmware e:
-  **Perde** file non protetti in `/usr/bin`, `/etc/init.d`
-  **Cancella** configurazioni non listate in `/etc/sysupgrade.conf`
-  **Rimuove** binari installati manualmente

**Risultato**: CheckMK Agent smette di funzionare dopo l'upgrade.

##  Soluzione ROCKSOLID

Lo script `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh` implementa protezioni automatiche:

### 1⃣ Protezione File Critici

Aggiunge automaticamente a `/etc/sysupgrade.conf`:
```
# CheckMK Agent - Binary
/usr/bin/check_mk_agent

# CheckMK Agent - Init Script
/etc/init.d/check_mk_agent

# CheckMK Agent - Configuration
/etc/check_mk/

# FRP Client - Binary
/usr/local/bin/frpc

# FRP Client - Configuration
/etc/frp/

# FRP Client - Init Script
/etc/init.d/frpc

# Post-upgrade verification script
/etc/checkmk-post-upgrade.sh

# Custom package repositories
/etc/opkg/customfeeds.conf
```

### 2⃣ Script Post-Upgrade Automatico

Crea `/etc/checkmk-post-upgrade.sh` che:
-  Verifica presenza file critici dopo upgrade
-  Riattiva servizi CheckMK e FRP
-  Controlla che socat sia in ascolto su porta 6556

### 3⃣ Autocheck all'Avvio (NUOVO!)

Lo script `rocksolid-startup-check.sh` esegue **automaticamente ad ogni riavvio**:
-  Verifica e riavvia CheckMK Agent se non attivo
-  Verifica e riavvia FRP Client se non attivo
-  **Reinstalla Git automaticamente** se mancante (dopo upgrade)
-  Verifica e ripristina cron job git-sync
-  Test sync del repository
-  Log completo in `/var/log/rocksolid-startup.log`

**Configurazione**: Eseguito automaticamente da `/etc/rc.local` in background.
-  Logga tutti gli eventi in syslog

### 3⃣ Differenze vs Script Originale

| Feature | Originale | ROCKSOLID |
|---------|-----------|-----------|
| Installa agent |  |  |
| Configura socat |  |  |
| Installa FRP (opzionale) |  |  |
| Protegge da upgrade |  |  |
| Script post-upgrade |  |  |
| Aggiunge a sysupgrade.conf |  |  Automatico |
| Logging upgrade |  |  Syslog |

##  Installazione

### Su NethSecurity/OpenWrt - Modalità Interattiva

```bash
# Da repository locale (se disponibile)
bash /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh

# Da GitHub
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh | bash
```

### Modalità Non-Interattiva (Boot Automatico)

Per esecuzioni automatiche (es. boot, cron, automation):

```bash
# Mantiene automaticamente configurazione FRP esistente (se presente)
# Salta prompt interattivi
NON_INTERACTIVE=1 bash /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh
```

**Comportamento modalità non-interattiva:**
-  Se esiste `/etc/frp/frpc.toml` → **mantiene automaticamente** la configurazione
-  Non chiede conferma per mantenere config FRP
-  Se FRP non configurato → salta installazione FRP
-  Ideale per script di avvio, autocheck, automation

### Output Installazione

```
╔════════════════════════════════════════════════════════════════╗
║  CheckMK Agent Installer - ROCKSOLID Edition                  ║
║  Versione resistente ai major upgrade NethSecurity/OpenWrt    ║
╚════════════════════════════════════════════════════════════════╝

[INFO] Configuro repository (customfeeds)
[INFO] opkg update
[INFO] Installo tool necessari (binutils/tar/gzip/wget/socat/ca-certificates)
[INFO] Installazione Checkmk agent
[INFO] Download .deb agente
[INFO] Estrazione .deb (ar + tar)
[INFO] Copia binario agente
[INFO] Agente installato: /usr/bin/check_mk_agent
[INFO] Creo servizio procd (socat listener su 6556)
[INFO] Checkmk agent in ascolto su TCP 6556 (socat)
[INFO] ROCKSOLID: Proteggo installazione CheckMK da major upgrade
[INFO] Aggiunto a sysupgrade.conf: /usr/bin/check_mk_agent
[INFO] Aggiunto a sysupgrade.conf: /etc/init.d/check_mk_agent
[INFO] Aggiunto a sysupgrade.conf: /etc/check_mk/
[INFO] Creo script di ripristino post-upgrade: /etc/checkmk-post-upgrade.sh
[INFO] Script post-upgrade creato e protetto

╔════════════════════════════════════════════════════════════════╗
║  INSTALLAZIONE COMPLETATA - ROCKSOLID MODE ATTIVO             ║
╚════════════════════════════════════════════════════════════════╝

Protezioni attivate:
   File critici aggiunti a /etc/sysupgrade.conf
   Script post-upgrade creato: /etc/checkmk-post-upgrade.sh
   Installazione resistente ai major upgrade

Test agent locale: nc 127.0.0.1 6556 | head
```

##  Procedura Major Upgrade

### Prima dell'Upgrade

1. Verifica file protetti:
```bash
cat /etc/sysupgrade.conf | grep -E 'check_mk|frpc'
```

2. Backup manuale (opzionale):
```bash
tar czf /tmp/checkmk-backup.tar.gz \
  /usr/bin/check_mk_agent \
  /etc/init.d/check_mk_agent \
  /etc/check_mk/ \
  /usr/local/bin/frpc \
  /etc/frp/ \
  /etc/init.d/frpc
```

### Dopo l'Upgrade

1. **AUTOMATICO**: Lo script `rocksolid-startup-check.sh` si avvia automaticamente al boot e:
   - Riattiva CheckMK Agent e FRP Client
   - Reinstalla Git se mancante
   - Ripristina cron job git-sync
   - Logga tutto in `/var/log/rocksolid-startup.log`

2. **MANUALE (se serve)**: Esegui script post-upgrade:
```bash
/etc/checkmk-post-upgrade.sh
/etc/git-sync-post-upgrade.sh
```

3. **VERIFICA Git**: Se git è mancante, verrà reinstallato automaticamente al boot:
```bash
# Lo script esegue automaticamente:
opkg update
opkg install git git-http
```

4. Verifica servizi attivi:
```bash
ps | grep -E 'socat|frpc'
netstat -tlnp | grep 6556
```

5. Test agent:
```bash
nc 127.0.0.1 6556 | head -20
```

6. Controlla log autocheck:
```bash
tail -50 /var/log/rocksolid-startup.log
```

##  Test Pre-Upgrade (Simulazione)

Prima di un major upgrade, testa la persistenza:

```bash
# 1. Simula perdita file
mv /usr/bin/check_mk_agent /tmp/
/etc/init.d/check_mk_agent stop

# 2. Esegui script post-upgrade
/etc/checkmk-post-upgrade.sh

# 3. Dovrebbe rilevare il problema
# Output atteso: "ERRORE: /usr/bin/check_mk_agent mancante dopo upgrade!"

# 4. Ripristina per continuare test
mv /tmp/check_mk_agent /usr/bin/
/etc/checkmk-post-upgrade.sh
```

##  Verifica Installazione ROCKSOLID

### Metodo 1: Script Automatico (Consigliato)

```bash
# Esegue verifica completa con autocheck
/usr/local/bin/rocksolid-startup-check.sh

# Visualizza log
tail -50 /var/log/rocksolid-startup.log
```

### Metodo 2: Script di Verifica Manuale

```bash
#!/bin/sh
echo "=== VERIFICA INSTALLAZIONE ROCKSOLID ==="
echo ""

echo "1. Binario CheckMK Agent:"
ls -lh /usr/bin/check_mk_agent && echo "   OK" || echo "   MANCANTE"

echo "2. Init script CheckMK:"
ls -lh /etc/init.d/check_mk_agent && echo "   OK" || echo "   MANCANTE"

echo "3. Configurazione CheckMK:"
ls -ld /etc/check_mk && echo "   OK" || echo "   MANCANTE"

echo "4. FRP client binary:"
ls -lh /usr/local/bin/frpc 2>/dev/null && echo "   OK" || echo "   Non installato"

echo "5. FRP configurazione:"
ls -ld /etc/frp 2>/dev/null && echo "   OK" || echo "   Non installato"

echo "6. Script post-upgrade:"
ls -lh /etc/checkmk-post-upgrade.sh && echo "   OK" || echo "   MANCANTE"

echo "7. Script autocheck avvio:"
ls -lh /usr/local/bin/rocksolid-startup-check.sh && echo "   OK" || echo "   MANCANTE"

echo "8. Configurazione rc.local:"
grep -q rocksolid-startup-check.sh /etc/rc.local && echo "   Autocheck attivo" || echo "   Autocheck non configurato"

echo "9. Protezione sysupgrade.conf:"
if grep -q check_mk_agent /etc/sysupgrade.conf; then
    echo "   CheckMK protetto"
else
    echo "   CheckMK NON protetto"
fi

echo "10. Processo socat attivo:"
if pgrep -f "socat TCP-LISTEN:6556" >/dev/null; then
    echo "   Agent in ascolto"
else
    echo "   Agent non attivo"
fi

echo "11. Porta 6556 in ascolto:"
netstat -tlnp | grep -q 6556 && echo "   Porta aperta" || echo "   Porta chiusa"

echo "12. Git installato:"
command -v git >/dev/null && echo "   Git presente: $(git --version)" || echo "   Git mancante"

echo ""
echo "=== CONTENUTO sysupgrade.conf (ROCKSOLID) ==="
grep -E 'check_mk|frpc|frp/|git-sync|rocksolid|rc.local' /etc/sysupgrade.conf || echo "Nessuna entry trovata"
```

##  Troubleshooting

### Agent non funziona dopo upgrade

```bash
# 1. Verifica file presenti
ls -la /usr/bin/check_mk_agent /etc/init.d/check_mk_agent

# 2. Esegui script post-upgrade
/etc/checkmk-post-upgrade.sh

# 3. Riavvia manualmente
/etc/init.d/check_mk_agent enable
/etc/init.d/check_mk_agent restart

# 4. Verifica log
logread | tail -50
```

### File persi dopo upgrade

Se i file sono stati comunque persi:
1. Re-esegui lo script di installazione ROCKSOLID
2. I file verranno ricreati e protetti
3. La configurazione FRP verrà preservata se in `/etc/frp/`

### FRP non riconnette

```bash
# Verifica configurazione preservata
cat /etc/frp/frpc.toml

# Riavvia servizio
/etc/init.d/frpc restart

# Controlla log
tail -f /var/log/frpc.log
```

##  Statistiche Protezione

| Componente | Dimensione | Protetto | Critico |
|------------|------------|----------|---------|
| check_mk_agent | ~74 KB |  | Alta |
| check_mk_agent init | ~552 B |  | Alta |
| /etc/check_mk/ | ~8 KB |  | Media |
| frpc binary | ~14.8 MB |  | Media |
| frpc.toml | ~389 B |  | Alta |
| frpc init | ~283 B |  | Media |
| post-upgrade.sh | ~1.2 KB |  | Alta |

**Totale spazio protetto**: ~15 MB

##  Best Practices

1. **Sempre usare versione ROCKSOLID** per nuove installazioni su NethSecurity/OpenWrt
2. **Testare script post-upgrade** prima di major upgrade reali
3. **Verificare sysupgrade.conf** periodicamente con `cat /etc/sysupgrade.conf`
4. **Backup manuale** prima di upgrade critici (anche se protetto)
5. **Monitorare log syslog** dopo upgrade: `logread | grep checkmk`

##  Riferimenti

- Script originale: `install-checkmk-agent-debtools-frp-nsec8c.sh`
- Script ROCKSOLID: `install-checkmk-agent-debtools-frp-nsec8c-rocksolid.sh`
- OpenWrt sysupgrade: https://openwrt.org/docs/guide-user/installation/sysupgrade
- NethSecurity Upgrade: https://github.com/nethserver/nethsecurity

---

**Ultimo aggiornamento**: 2026-01-29  
**Versione**: 1.0 ROCKSOLID  
**Testato su**: NethSecurity 8.7.1 (OpenWrt 24.10.3)
