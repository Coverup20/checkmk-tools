# GitHub Copilot Instructions - checkmk-tools

## 🔴 REGOLA PRELIMINARE OBBLIGATORIA

**⚠️ PRIMA DI INIZIARE QUALSIASI LAVORO:**

- ✅ **SEMPRE leggere QUESTO file** (`.github/copilot-instructions.md`) all'inizio di OGNI conversazione
- ✅ **SEMPRE consultare** questo file prima di iniziare qualsiasi task
- ⚠️ Questo file contiene **TUTTE le regole, workflow e procedure obbligatorie**
- ❌ **NON iniziare a lavorare** senza aver letto e compreso le istruzioni
- ✅ In caso di dubbio su come procedere → **rileggi questo file**

**File correlati:**
- `.copilot-preferences.md` → Sommario/quick reference (220 righe)
- `.github/copilot-instructions.md` → **QUESTO FILE** - Regole complete (~2250 righe, aggiornato automaticamente)

---

## 🎯 FILOSOFIA DI LAVORO FONDAMENTALE

**⚠️ REGOLA ZERO - QUALITÀ PRIMA DI TUTTO:**

> **"LA PRESCIA VUOLE TEMPO!!"**  
> _Fare le cose di fretta = rifarle 10 volte invece di 1 volta fatta per bene_

- ✅ **FARE LE COSE PER BENE** - Usare tutto il tempo necessario
- ❌ **NESSUNA SCORCIATOIA** - Mai saltare step senza esplicita autorizzazione utente
- ✅ **COMPLETEZZA ASSOLUTA** - Seguire workflow completi fino in fondo
- ⏱️ **NON C'È FRETTA** - Non ho impegni che mi costringano a velocizzare
- ✅ **WORKFLOW OBBLIGATORI** - Seguire SEMPRE tutti gli step documentati
- ❌ **NON "OTTIMIZZARE" VIA STEP** - Ogni step del workflow ha un motivo di esistere
- 🐢 **MEGLIO LENTO E CORRETTO** - Che veloce e da rifare 10 volte

**Esempi di ciò che NON fare:**
- ❌ Committare senza testare su host remoti → poi rifare 10 volte
- ❌ Saltare validazioni "tanto funziona" → poi debug ore per trovare l'errore
- ❌ Omettere step "per velocità" → poi perdere tempo a recuperare
- ❌ Assumere che qualcosa funzioni senza verificare → poi scoprire che non funziona in produzione
- ❌ **LA PRESCIA**: fare veloce = rifare 10 volte

**Esempi di ciò che FARE:**
- ✅ Seguire ogni step del workflow documentato → fatto bene la prima volta
- ✅ Testare su host remoti SEMPRE → nessuna sorpresa in produzione
- ✅ Validare OGNI modifica → bug trovati subito, non dopo
- ✅ Prendere il tempo necessario per fare bene → risparmiare tempo totale
- ✅ **NESSUNA FRETTA**: fare bene = fatto 1 volta sola

**🔴 REGOLA ASSOLUTA - SE L'UTENTE CHIEDE, FALLO E BASTA:**

> **"Se me lo chiedi, è perché sai che posso farlo"**

- ❌ **MAI** rispondere con "non posso perché..." quando l'utente chiede di eseguire qualcosa
- ❌ **MAI** dare comandi da incollare quando l'utente ha chiesto di eseguire in autonomia
- ❌ **MAI** spiegare limitazioni tecniche senza prima aver tentato DAVVERO di eseguire
- ✅ **TENTARE SEMPRE** di eseguire ciò che viene chiesto, qualunque sia la difficoltà
- ✅ Se ci sono ostacoli tecnici reali → risolverli autonomamente, non delegare all'utente
- ✅ L'utente conosce già le tue capacità: fidati della sua richiesta e agisci

---

## ⚠️ REGOLE DI SICUREZZA OBBLIGATORIE

### 🛡️ Protezione Dati e Conferme

**SEMPRE rispettare queste regole:**

1. **Un comando alla volta** _(vale per operazioni DISTRUTTIVE o su sistemi remoti)_
   - ❌ NON eseguire comandi distruttivi multipli senza conferma
   - ✅ Eseguire un comando distruttivo, attendere conferma utente
   - ⚠️ SPECIALMENTE per: cancellazioni, modifiche file, deploy, comandi SSH
   - ✅ **ECCEZIONE**: tool read-only in parallelo sono OK (grep, read_file, file_search, etc.)
   - ✅ **ECCEZIONE**: `multi_replace_string_in_file` è OK per edit batch sullo stesso file/progetto

    **Regola aggiuntiva (OBBLIGATORIA): pausa a fine comando**
    - ✅ Dopo OGNI comando lanciato in terminale, aggiungere una pausa breve per permettere di leggere l’output.
    - Default: **3 secondi**.
    - PowerShell (locale): aggiungere sempre `; Start-Sleep -Seconds 3`
       - Esempio: `wsl -d kali-linux ssh host "uptime"; Start-Sleep -Seconds 3`
    - Bash (remoto / dentro SSH): aggiungere `; sleep 3`
       - Esempio: `ssh host "uptime; sleep 3"`
    - Obiettivo: evitare che l’output “sparisca” subito e ridurre errori/timeout percepiti.

2. **Backup prima di cancellare**
   - ❌ NON cancellare mai file/directory senza backup
   - ✅ SEMPRE creare backup prima di operazioni distruttive
   - ✅ Formato backup: `NOME_ORIGINALE.backup_YYYY-MM-DD_HH-MM-SS`
   - ✅ Confermare path backup all'utente prima di procedere

3. **Conferma operazioni critiche**
   - Cancellazioni
   - Modifiche massive (>10 file)
   - Deploy su produzione
   - Comandi su sistemi remoti

4. **Verifica preferenze Copilot periodicamente**
   - ✅ Controllare `.github/copilot-instructions.md` regolarmente
   - ✅ Assicurarsi di seguire sempre le ultime istruzioni
   - ✅ Suggerire aggiornamenti quando necessario

5. **Memorizza informazioni utili**
   - ✅ Se scopri pattern/comandi/procedure utili → aggiungili alle copilot-instructions
   - ✅ Workflow che funzionano bene vanno documentati
   - ✅ Path comuni, configurazioni standard, troubleshooting tips

6. **Pulizia backup dopo test**
   - ✅ Quando i test su file backuppati terminano con successo
   - ✅ Proporre rimozione dei file backup creati
   - ✅ ATTENDERE conferma utente prima di eliminare
   - ✅ Non eliminare mai backup senza conferma esplicita

7. **Controllo integrità periodico automatico**
   - ✅ Durante le conversazioni, proporre periodicamente `.\script-ps-tools\check-integrity.ps1 -SendEmail`
   - ✅ Eseguire il controllo in momenti opportuni (dopo modifiche, commit importanti, richieste utente)
   - ✅ Inviare email se anche solo 1 file corrotto viene trovato
   - ✅ Email include: lista file corrotti, percentuale errori, dettagli
   - ✅ Non inviare email se tutto OK (solo output console)

8. **🔐 CONTROLLO DATI SENSIBILI OBBLIGATORIO**
   - ✅ **SEMPRE** verificare presenza dati sensibili quando si crea/modifica uno script
   - ✅ Scansionare per:
     - **Token**: API keys, auth tokens, access tokens
     - **Password**: hardcoded passwords, default credentials
     - **Secrets**: chiavi SSH/GPG, certificati privati
     - **Credenziali**: username+password, connection strings
     - **Indirizzi IP privati**: se espongono infrastruttura critica
     - **Domini interni**: se riservati/confidenziali
   - ⚠️ **PATTERN CRITICI da cercare**:
     - `token=`, `password=`, `secret=`, `key=`
     - `AUTH_TOKEN=`, `API_KEY=`, `PRIVATE_KEY=`
     - Stringhe lunghe alfanumeriche hardcoded (token-like)
     - Default credentials con valori reali
   - ✅ **Azioni correttive**:
     - Rimuovere valori hardcoded
     - Usare variabili d'ambiente senza default sensibili
     - Forzare input manuale utente (con validazione)
     - Usare placeholder generici (`INSERISCI_TOKEN_QUI`)
   - ✅ **Workflow obbligatorio**:
     1. Prima di commit → scansiona script modificati
     2. Se trovati dati sensibili → avvisa utente
     3. Proponi fix immediato (rimozione/variabili env)
     4. Valida che fix non rompa funzionalità
     5. Ricorda all'utente di **rotare credenziali** se già pubblicate

9. **🧠 EFFICIENZA E CONTENIMENTO TOKEN - Pensare Prima di Agire**
   - ⚠️ **BUDGET MENSILE**: 1500 token/mese utilizzabili
   - ⚠️ **Budget extra disponibili MA preferire NON usarli** - mantenerli come riserva emergenza
   - ✅ **SEMPRE pensare e pianificare** prima di eseguire azioni
   - ✅ **Autonomia decisionale**: Prendere decisioni ovvie senza chiedere conferma per banalità
   - ✅ **Ragionamento profondo**: Analizzare contesto disponibile, dedurre risposte, inferire intent utente
   - ✅ **Capitalizzare token prima richiesta**: Usare informazioni già fornite, evitare domande ridondanti
   - ⚠️ **Chiedere solo se necessario**: Solo per decisioni con reale impatto o ambiguità sostanziali
   - ✅ **Limite tentativi fix**: Max 3 iterazioni per stesso problema
   - ⚠️ **Se 3 tentativi falliscono** → FERMARSI e chiedere aiuto utente
   - ✅ **Evitare loop infiniti**: Non ripetere stesso approccio se fallisce
   - ✅ **Approccio incrementale**: Fix piccoli e testati, non modifiche massive senza validazione
   - ⚠️ **Sessioni lunghe**: Ogni 15-20 interazioni → breve recap e conferma direzione
   - ✅ **Operazioni massive**: Prima di modifiche >20 file → chiedere conferma strategia
   - ❌ **NON iterare ciecamente**: Se un comando fallisce 2 volte → cambiare approccio
   - ✅ **Valutare costo/beneficio**: Per operazioni lunghe → proporre alternative più efficienti
   - ✅ **Ragionamento esplicito**: Per problemi complessi → spiegare piano d'azione prima di eseguire

   **Esempio decisioni AUTONOME (NON chiedere):**
   ```text
   ✅ Fix sintassi ovvia (parentesi mancante, virgola, etc.)
   ✅ Rinumerare liste dopo inserimento elemento
   ✅ Aggiornare timestamp nei backup
   ✅ Correggere path relativo → assoluto (workspace noto)
   ✅ Rendere eseguibile script .sh con git update-index
   ✅ Commit message descrittivo da modifiche ovvie
   ```

   **Esempio decisioni che RICHIEDONO conferma:**
   ```text
   ⚠️ Cancellare dati/file (anche con backup)
   ⚠️ Deploy su produzione
   ⚠️ Scelta tra approcci tecnici diversi con trade-off
   ⚠️ Modifiche che impattano sicurezza/performace
   ⚠️ Scelta tra più host per test quando non ovvio
   ```

   **Esempio gestione tentativi:**
   ```text
   Tentativo 1: wsl bash -n script.sh → ERRORE linea 45
   Fix 1: correggi sintassi → testa
   
   Tentativo 2: wsl bash -n script.sh → ERRORE linea 67
   Fix 2: correggi secondo errore → testa
   
   Tentativo 3: wsl bash -n script.sh → ERRORE linea 45 (stessa linea!)
   ⚠️ STOP: Approccio non funziona, pattern non chiaro
   → Chiedi aiuto: "Ho provato 3 volte, errore persiste. Posso vedere il contesto completo della linea 45?"
   ```

   **Quando fermarsi e chiedere aiuto:**
   - ❌ Loop fix sullo stesso errore (>2 tentativi)
   - ❌ Approccio teoricamente corretto ma fallisce ripetutamente
   - ❌ Errori non chiari o ambigui dopo 2 tentativi
   - ❌ Problema fuori dal tuo controllo (permessi, configurazione sistema, etc.)
   - ❌ Soluzione richiede conoscenza specifica che non hai

10. **🔬 APPROCCIO INCREMENTALE - Spezzare Problemi Complessi**
   - ✅ **Per situazioni complesse**: NON riscrivere tutto lo script/codice immediatamente
   - ✅ **Spezzare problema grande** in tanti micro-problemi gestibili
   - ✅ **Risolvere on the fly**: Affrontare un micro-problema alla volta
   - ✅ **Validare step-by-step**: Solo quando micro-problema risolto → passare al prossimo
   - ✅ **Approccio scalare**: Iterare fino a risolvere tutti i micro-problemi
   - ✅ **Riscrivere codice** solo quando TUTTI i micro-problemi sono risolti
   - ⚠️ **NON fare rewrites massivi** senza aver prima scomposto e validato ogni pezzo

   **Workflow corretto per problemi complessi:**
   ```text
   Problema: Script fallisce con 5 errori diversi
   
   ❌ SBAGLIATO: Riscrivere intero script subito
   
   ✅ CORRETTO: Approccio incrementale
   1. Identifica micro-problema 1 (es: sintassi bash linea 45)
   2. Fix micro-problema 1 on the fly (singola modifica)
   3. Test validazione (wsl bash -n)
   4. Conferma risoluzione → passa a micro-problema 2
   5. Identifica micro-problema 2 (es: path file errato)
   6. Fix micro-problema 2 on the fly
   7. Test validazione
   8. Ripeti fino a risolvere tutti i micro-problemi
   9. SOLO ORA: considera refactoring/rewrite completo se necessario
   ```

   **Benefici approccio incrementale:**
   - ✅ Riduce rischio di introdurre nuovi bug
   - ✅ Facilita debugging (ogni step isolato)
   - ✅ Mantiene funzionalità esistenti durante fix
   - ✅ Permette rollback parziale se necessario
   - ✅ Costo token ridotto (fix mirati vs rewrite massiccio)

11. **⚠️ CONTROLLO PROBLEMS OBBLIGATORIO**
   - ✅ **SEMPRE** controllare pannello PROBLEMS prima di considerare completato un task
   - ✅ Eseguire `get_errors()` dopo modifiche a file markdown/script
   - ✅ Priorità correzione errori:
     - **MD051** (link fragments invalidi) → Fix OBBLIGATORIO
     - **MD042** (empty links) → Rimuovere link o renderli validi
     - **MD022/MD031/MD032** (spacing) → Fix per qualità codice
     - **MD060** (table style) → Fix se facile, altrimenti ignorare
     - **MD024** (duplicate headings) → Valutare caso per caso
   - ⚠️ Se >50 errori: fixare batch con `multi_replace_string_in_file`
   - ✅ Confermare "0 errors" prima di dichiarare task completato
   - ❌ **NON** ignorare problemi senza consultare utente

12. **⚠️ TEST OBBLIGATORIO - TUTTI GLI SCRIPT MODIFICATI**
   - ❌ **MAI** dire "test completato" senza testare TUTTI gli script modificati
   - ✅ **SEMPRE** testare OGNI script modificato nella sessione corrente
   - ✅ Lista script modificati → test CIASCUNO separatamente
   - ⚠️ **CRITICO**: Se modifichi 3 script → testa tutti e 3, non solo 1!
   - ✅ Validare sintassi bash: `wsl bash -n script.sh`
   - ✅ Test esecuzione: eseguire su host remoto (nsec8-stable, laboratorio, etc.)
   - ✅ Verificare output/log per confermare funzionamento
   - ❌ Non dare per scontato che "se uno funziona, funzionano tutti"

**Esempio workflow test CORRETTO:**

```bash
# Modificati: install-script.sh, rocksolid-startup.sh, altro-script.sh

# OBBLIGATORIO: Testa TUTTI E 3 separatamente
wsl bash -n install-script.sh          # ✅ Validazione 1
wsl bash -n rocksolid-startup.sh       # ✅ Validazione 2
wsl bash -n altro-script.sh            # ✅ Validazione 3

# Test esecuzione TUTTI E 3 su host remoto
wsl -d kali-linux ssh nsec8-stable "curl -fsSL .../install-script.sh | bash"      # ✅ Test 1
wsl -d kali-linux ssh nsec8-stable "curl -fsSL .../rocksolid-startup.sh | bash"   # ✅ Test 2
wsl -d kali-linux ssh nsec8-stable "curl -fsSL .../altro-script.sh | bash"        # ✅ Test 3

# SOLO ORA puoi dire "test completato"

```text

**Esempio workflow test SBAGLIATO:**

```bash
# Modificati: install-script.sh, rocksolid-startup.sh

# Test solo rocksolid
wsl -d kali-linux ssh nsec8-stable "rocksolid-startup.sh"  # ✅ Test 1
# ❌ NON testato install-script.sh!

# ❌ ERRORE: Dici "test completato" senza testare install-script.sh

```text

**Esempio workflow corretto:**

```bash
# 1. Backup
cp file.txt file.txt.backup_2026-01-27_20-30-00

# 2. Chiedi conferma
"Ho creato backup in file.txt.backup_2026-01-27_20-30-00. Procedo con cancellazione?"

# 3. Solo dopo OK utente
rm file.txt

```text

13. **⚠️ MARKDOWN QUALITY - Prevenzione Errori Markdownlint**
   - ✅ **WORKFLOW OBBLIGATORIO per OGNI file .md creato/modificato:**
     1. **PRIMA**: Segui best practices markdownlint (vedi sotto)
     2. **SUBITO DOPO modifica**: Esegui `markdownlint file.md` (exit code 0=OK)
     3. **SE ERRORI**: Fix immediato e ri-esegui `markdownlint`
     4. **RIPETI**: Finché non ottieni exit code 0
     5. **OPZIONALE**: `get_errors()` per check VSCode (file path errors)
     6. **SOLO ALLORA**: Considera task completato
   - ✅ **Regole obbligatorie da rispettare:**
     - **Heading spacing**: Riga vuota SEMPRE dopo heading `###`

     - **List spacing**: Riga vuota dopo ultima voce lista prima di paragrafo/heading
     - **Code block spacing**: Riga vuota prima E dopo blocchi ` ``` `
     - **Code language**: Specificare SEMPRE linguaggio nei code block (bash, powershell, python, json, text)
     - **No empty links**: Mai usare link vuoti con anchor #, usare URL valido o rimuovere link
     - **Link fragments**: Se usi TOC con emoji negli heading, usa testo bold invece di link
   - ✅ **Esempi corretti:**
     - Heading con riga vuota sotto
     - Lista con riga vuota dopo ultima voce
     - Code block con linguaggio specificato (bash/powershell/json)
     - Code block con righe vuote prima e dopo
   - ❌ **Esempi SBAGLIATI:**
     - Heading senza riga vuota sotto
     - Lista senza riga vuota prima di paragrafo/heading
     - Code block senza linguaggio specificato
     - Code block senza righe vuote intorno
   - ✅ Dopo creazione/modifica file .md → `get_errors()` per validazione immediata
   - ✅ Preferire TOC senza link se heading hanno emoji (usa **testo bold** invece)

14. **Recupero script corrotti o persi**
   - ✅ **Metodo 1**: Git history - `git log`, `git show`, `git checkout`
   - ✅ **Metodo 2**: Backup locali - `C:\CheckMK-Backups\<timestamp>\`
   - ✅ **Metodo 3**: Backup rete - `\\192.168.10.132\usbshare\CheckMK-Backups\<timestamp>\`
   - ⚠️ Verificare **sempre** disponibilità backup prima di modifiche massive
   - ✅ Backup automatici eseguiti daily: job00 (locale+rete), ultra-minimal (locale)

**Esempio recupero file:**

```powershell
# Da Git (commit precedente)
git show HEAD~1:script-tools/full/script.sh > script.sh.recovered

# Da backup locale
Copy-Item "C:\CheckMK-Backups\2026-01-29_03-00-00\script-tools\full\script.sh" -Destination ".\"

# Da backup rete
Copy-Item "\\192.168.10.132\usbshare\CheckMK-Backups\2026-01-29_00-00-00\script-tools\full\script.sh" -Destination ".\"

```text

15. **Test-Fix-Validate Loop Automatico**
   - ✅ Quando modifichiamo uno script E abbiamo accesso a host di test
   - ✅ **SEMPRE** seguire questo ciclo automatico dopo ogni modifica:
     1. **Modifica** script
     2. **Valida** sintassi (`bash -n` o PSParser)
     3. **Testa** su host remoto (esecuzione reale)
     4. **Se fallisce** → Fix errore
     5. **Ri-valida** sintassi
     6. **Ri-testa** su host
     7. **Ripeti** finché non funziona o finché utente non ferma
   - ⚠️ **NON fermarsi** dopo validazione sintassi se test fallisce
   - ⚠️ **NON aspettare** comando utente per fixare - fallo automaticamente
   - ✅ **Continuare** a iterare fino a successo completo

**Esempio workflow test-driven:**

```powershell
# 1. Modifica script
# ... edit file ...

# 2. Valida sintassi
wsl bash -n script.sh  # EXIT CODE: 0 ✓

# 3. Testa su host
wsl -d kali-linux ssh nsec8-stable "bash /opt/checkmk-tools/script.sh"
# Output: ERROR line 45: comando non trovato

# 4. Fix automatico (NON fermarsi!)
# ... correggi errore linea 45 ...

# 5. Ri-valida
wsl bash -n script.sh  # EXIT CODE: 0 ✓

# 6. Ri-testa
wsl -d kali-linux ssh nsec8-stable "bash /opt/checkmk-tools/script.sh"
# Output: SUCCESS ✓

# 7. Solo ora committa
git commit -m "fix: risolto errore comando"

```text

**Host disponibili per test:**
- `nsec8-stable` (10.155.100.100) - NethSecurity 8 test environment
- `checkmk-vps-02` (monitor01.nethlab.it) - CheckMK staging/test
- `checkmk-z1plus` (192.168.10.128) - CheckMK locale test

16. **⚠️ WORKFLOW OBBLIGATORIO - Sviluppo e Test Script**
   - ✅ **SEMPRE seguire questo workflow completo** per modifiche a script bash/shell
   - ❌ **MAI** saltare step o dichiarare "completato" senza test reale
   - 🔄 **LOOP finché non funziona tutto** - non uscire fino a successo completo

**WORKFLOW OBBLIGATORIO (da seguire SEMPRE):**

```text

┌─────────────────────────────────────────────────────────┐
│ 1. MODIFICA/SCRITTURA SCRIPT                            │
│    - Implementa funzionalità richiesta                  │
│    - Segui best practices bash/PowerShell               │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 2. TEST SINTASSI                                        │
│    Bash: wsl bash -n script.sh                          │
│    PowerShell: PSParser validation                      │
│    ✓ Exit code DEVE essere 0                            │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 3. VERIFICA ESEGUIBILITÀ                                │
│    git ls-files -s script.sh                            │
│    ✓ DEVE mostrare 100755 (eseguibile)                  │
│    Se 100644 → git update-index --chmod=+x script.sh    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 4. ALLINEA REPO E COMMIT                                │
│    git add script.sh                                    │
│    git commit -m "descriptive message"                  │
│    git push                                             │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 5. CHIEDI HOST PER TEST                                 │
│    "Su quale host vuoi testare?"                        │
│    Host disponibili: nsec8-stable, laboratorio, etc.    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 6. VERIFICA E AGGIORNA REPO LOCALE                      │
│    - Verifica esistenza /opt/checkmk-tools/             │
│    - Se NON esiste → git clone                          │
│    - Se esiste → cd /opt/checkmk-tools && git pull      │
│    ✓ OBBLIGATORIO prima di ogni test                    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│ 7. TEST FUNZIONAMENTO COMPLETO                          │
│    - Esegui script da REPO LOCALE                       │
│    - Path: /opt/checkmk-tools/script-check-*/full/xxx   │
│    - Verifica output/log                                │
│    - Controlla exit code                                │
│    - Valida risultato atteso                            │
└─────────────────────────────────────────────────────────┘
                         ↓
              ┌──────────────────┐
              │ FUNZIONA TUTTO?  │
              └──────────────────┘
                    /    \
                   /      \
              NO ↙        ↘ SI
                /          \
    ┌──────────────┐    ┌──────────────────────┐
    │ TORNA A 1.   │    │ ✅ ESCI DAL LOOP     │
    │ FIX + RITEST │    │ Task completato!     │
    └──────────────┘    └──────────────────────┘

```text

**⚠️ REGOLE CRITICHE:**
- ❌ **MAI** dire "test completato" senza test REALE su host remoto
- ❌ **MAI** uscire dal loop se ci sono errori
- ❌ **MAI** saltare step del workflow senza autorizzazione esplicita utente
- ❌ **MAI** assumere che funzioni senza testare
- ✅ **SEMPRE** fixare errori e ri-testare automaticamente
- ✅ **SEMPRE** testare TUTTI gli script modificati nella sessione
- ✅ **SEMPRE** seguire TUTTI gli step 1-7 del workflow
- 🔄 **LOOP infinito** finché non funziona o utente ferma
- ⏱️ **NESSUNA FRETTA** - Prendere tutto il tempo necessario per fare bene
- ⚠️ **STEP 7 SU HOST PASSWORD**: se l'host target richiede password (es. ns-lab00, laboratorio)
  → NON eseguire il test in autonomia → dare i comandi da incollare all'utente

**Esempio completo:**

```bash
# 1. Modifica
vi install-script.sh

# 2. Test sintassi
wsl bash -n install-script.sh  # Exit: 0 ✓

# 3. Verifica eseguibilità
git ls-files -s install-script.sh  # 100755 ✓

# 4. Commit
git add install-script.sh
git commit -m "fix: correzione download dinamico"
git push

# 5. Chiedi host
"Su quale host testo? [nsec8-stable]"

# 6. Verifica e aggiorna repo locale
wsl -d kali-linux ssh nsec8-stable "[ -d /opt/checkmk-tools ] && echo 'EXISTS' || echo 'MISSING'"
# Se MISSING → git clone https://github.com/Coverup20/checkmk-tools.git /opt/checkmk-tools
# Se EXISTS → wsl -d kali-linux ssh nsec8-stable "cd /opt/checkmk-tools && git pull"

# 7. Test da REPO LOCALE (NON GitHub!)
wsl -d kali-linux ssh nsec8-stable "/opt/checkmk-tools/script-tools/full/install-script.sh"
# Output: ERRORE linea 45

# ❌ ERRORE → TORNA A 1 (fix + ritest)
# Fix errore linea 45, ricommit, ritest...

# ✅ OK → Test completato, ESCI DAL LOOP
```

17. **Script eseguibili - Verifica SEMPRE permessi Git**
   - ⚠️ **Windows (NTFS) NON preserva il bit eseguibile Unix**
   - ✅ **SEMPRE** quando crei/modifichi script bash/shell (.sh):
     1. Crea/modifica il file
     2. Verifica permessi: `git ls-files -s script.sh`
     3. Se mostra `100644` (NON eseguibile) → FIX:
        ```bash
        git update-index --chmod=+x script.sh
        ```

     4. Verifica: `git ls-files -s script.sh` → deve mostrare `100755`
     5. Committo e push normalmente
   - ✅ **Controllo batch** su directory:
     ```bash
     # Trova script NON eseguibili
     git ls-files -s script-tools/full/*.sh | Select-String "100644"

     # Rendi tutti eseguibili
     git update-index --chmod=+x script-tools/full/*.sh
     ```

   - ⚠️ **NON fare affidamento** su `wsl -- test -x` su Windows → usa `git ls-files -s`
   - ✅ Quando proponi nuovi script bash → renderli subito eseguibili con git update-index

**Esempio workflow creazione script:**

```powershell
# 1. Crea script
New-Item script-tools/full/nuovo-script.sh

# 2. Scrivi contenuto
# ... edit file ...

# 3. OBBLIGATORIO: Rendi eseguibile
git add script-tools/full/nuovo-script.sh
git update-index --chmod=+x script-tools/full/nuovo-script.sh

# 4. Verifica (deve mostrare 100755)
git ls-files -s script-tools/full/nuovo-script.sh

# 5. Commit
git commit -m "feat: nuovo script"

```

18. **📌 VERSIONING SCRIPT OBBLIGATORIO**
   - ✅ **SEMPRE aggiungere variabile VERSION** all'inizio di ogni script bash/PowerShell/Python
   - ✅ Rendere **versione visibile nell'output/header** dello script
   - ✅ **Aggiornare versione ad OGNI modifica** committata
   - ⚠️ Permette identificazione immediata versione in esecuzione su host remoti
   
   **Schema versionamento:**
   - `MAJOR.MINOR.PATCH` (es: `2.0.5`)
   - MAJOR: cambio architettura/breaking changes
   - MINOR: nuove funzionalità backwards-compatible
   - PATCH: bugfix/miglioramenti minori
   
   **Template Python (PREFERITO - policy Python-first):**
   ```python
   #!/usr/bin/env python3
   VERSION = "1.0.0"   # Versione script (aggiornare ad ogni modifica)
   
   # Mostra versione in output/help
   print(f"Script Name - Version v{VERSION}")
   ```
   
   **Template Bash:**
   ```bash
   #!/bin/bash
   VERSION="1.0.0"   # Versione script (aggiornare ad ogni modifica)
   
   # Mostra versione in output/help
   echo "Script Name - Version v${VERSION}"
   ```
   
   **Template PowerShell:**
   ```powershell
   # Script Name
   $VERSION = "1.0.0"   # Versione script (aggiornare ad ogni modifica)
   
   Write-Host "Script Name - Version v$VERSION"
   ```
   
   **Esempio commit message con bump versione:**
   ```bash
   git commit -m "fix(script): v1.0.1 - corregge bug parsing ACL"
   ```
   
   **Workflow modifica script:**
   1. Modifica codice
   2. **OBBLIGATORIO**: Bump VERSION variable
   3. Test validazione
   4. Commit con versione nel message
   5. Push

---
## 📋 NethSecurity 8 - Local Checks CheckMK

### ⚠️ REGOLA DEPLOYMENT - Mantenere estensione .sh

**Local checks devono mantenere l'estensione `.sh` anche quando deployed:**

```bash
# ✅ CORRETTO - Mantieni estensione
cp /opt/checkmk-tools/script-check-nsec8/full/check_vpn_tunnels.sh \
   /usr/lib/check_mk_agent/local/check_vpn_tunnels.sh
#                                                    ^^^ CON .sh

# ❌ SBAGLIATO - Non rimuovere estensione
cp script.sh /usr/lib/check_mk_agent/local/script  # NO!

```text

**Motivo preferenza utente:**
- Coerenza con repository (tutti gli script .sh)
- Più facile identificare tipo file
- CheckMK esegue comunque file con estensione

**Auto-restore deve usare nome completo con estensione:**

```bash
# In rocksolid-startup-check.sh
basename_script=$(basename "$script")  # NON rimuovere .sh
cp "$script" "/usr/lib/check_mk_agent/local/$basename_script"

```text

---
## �️ NethServer - Gestione Configurazione

### ⚠️ REGOLA CRITICA - NON modificare file di configurazione manualmente

**NethServer (NS7/NS8) usa sistema e-smith/template:**
- ❌ **MAI modificare direttamente** file in `/etc/` (fail2ban, httpd, postfix, etc.)
- ✅ **SEMPRE usare interfaccia web** o comandi `config`
- ⚠️ Modifiche manuali ai file = **perse al prossimo `signal-event`**

**Esempio configurazioni gestite da template:**

```bash
/etc/fail2ban/fail2ban.conf          # Gestito da templates
/etc/fail2ban/jail.conf              # Gestito da templates
/etc/httpd/conf.d/*                  # Gestito da templates
/etc/postfix/main.cf                 # Gestito da templates
/etc/shorewall/*                     # Gestito da templates

```text

**Metodi corretti per modificare configurazioni:**

1. **Via interfaccia web NethServer**
   - Server Manager → sezione specifica
   - Modifiche persistenti e validate

2. **Via comandi config (CLI)**

```bash
# Visualizza configurazione
config show fail2ban

# Modifica proprietà
config setprop fail2ban LogLevel NOTICE
config setprop fail2ban DbPurgeAge 30d

# Applica modifiche
signal-event nethserver-fail2ban-save

```text

3. **Via template custom** (avanzato)

```bash
# Crea template custom in /etc/e-smith/templates-custom/
# Le modifiche sopravvivono ai signal-event

```text

**⚠️ Conseguenze modifiche manuali:**
- `signal-event nethserver-<servizio>-save` → configurazione ripristinata
- Riavvio servizio → configurazione ripristinata
- Aggiornamenti sistema → configurazione ripristinata

**✅ SEMPRE chiedere conferma utente** prima di suggerire modifiche manuali a file su NethServer!

---

## 🔧 NethSecurity 8 - NGINX Web UI Major Upgrade Issue

### ⚠️ PROBLEMA CRITICO - Symlink /etc/nginx/uci.conf cancellato durante upgrade

**Sintomo:**
- Post major upgrade: nginx non parte, Web UI (porta 9090) non disponibile
- Log error: `open() "/etc/nginx/nginx.conf" failed (2: No such file or directory)`
- Directory `/etc/nginx/` esiste e protetta, ma manca symlink

**Causa ROOT:**
- NethSecurity usa `/var/lib/nginx/uci.conf` come configurazione nginx principale
- `/etc/nginx/uci.conf` è un **symlink** → `/var/lib/nginx/uci.conf`
- Durante major upgrade: symlink cancellato anche se `/etc/nginx/` è protetto in sysupgrade.conf
- Nginx cerca `uci.conf` ma non lo trova → fallisce avvio

**Soluzione implementata (commit 6107753 + 1986623):**

1. **Protezione directory** (`install-checkmk-agent-persistent-nsec8.sh`):

```bash
# In protect_checkmk_installation()
add_to_sysupgrade "/etc/nginx/" "NGINX configuration (Web UI NethSecurity)"

```text

2. **Ripristino automatico symlink** (`rocksolid-startup-check.sh`):

```bash
# Prima di verificare nginx
if [ ! -L /etc/nginx/uci.conf ] && [ -f /var/lib/nginx/uci.conf ]; then
    log "[Nginx] Ripristino symlink uci.conf..."
    ln -sf /var/lib/nginx/uci.conf /etc/nginx/uci.conf 2>/dev/null || true
fi

```text

**Fix manuale emergenza:**

```bash
# Su sistema già upgradato con nginx rotto
ln -sf /var/lib/nginx/uci.conf /etc/nginx/uci.conf
/etc/init.d/nginx restart
# Web UI torna disponibile su porta 9090

```text

**Verifica soluzione:**

```bash
# Dopo upgrade/reboot
ls -la /etc/nginx/uci.conf  # Deve essere symlink
/etc/init.d/nginx status    # Deve essere "running"
netstat -tlnp | grep :9090  # Deve mostrare nginx in ascolto

```text

**Note tecniche:**
- `/var/lib/nginx/uci.conf` generato dinamicamente da nginx-ssl-util
- Contiene configurazioni server blocks per porte 80/443/9090
- Symlink necessario perché nginx include `/etc/nginx/uci.conf` nel main config
- Backup laboratorio disponibile: `C:\Users\Marzio\Desktop\CheckMK\nginx-backup-laboratorio.tar.gz`

---

## �🔧 Strumenti di Controllo Qualità

### check-integrity.ps1 - Controllo Integrità Repository

**Quando usare questo strumento:**
- Quando l'utente chiede di "controllare l'integrità" o "verificare la corruzione"
- Dopo modifiche massive a script bash o PowerShell
- Prima di merge importanti
- Quando sospetti corruzione file nel repository

**Comandi disponibili:**

```powershell
# Controllo standard con riepilogo
.\script-ps-tools\check-integrity.ps1

# Controllo dettagliato con lista completa errori
.\script-ps-tools\check-integrity.ps1 -Detailed

# Esporta report completo su file
.\script-ps-tools\check-integrity.ps1 -ExportReport

# Cambia soglia di corruzione (default: 15%)
.\script-ps-tools\check-integrity.ps1 -Threshold 20

```text

**Funzionalità:**
- ✅ Verifica sintassi **PowerShell** tramite `[System.Management.Automation.Language.Parser]::ParseFile()`
- ✅ Verifica sintassi **Bash/Shell** tramite WSL `bash -n`
- ✅ Rileva **corruzione massiva** (soglia default: 15%)
- ✅ Report dettagliato per tipo di file (PS1, Bash, Batch, Python)
- ✅ Exit codes: 0=OK, 1=Warning (<15%), 2=Critical (>15%)

**Integrazione con Sistema di Backup:**
- `backup-simple.ps1` usa la stessa logica di validazione
- Il backup viene **bloccato** se la corruzione supera il 15%
- Le email di backup includono report dettagliato degli errori rilevati

**Struttura Repository Verificata:**

```text

checkmk-tools/
├── script-check-ns7/full/         # Script NethServer 7
├── script-check-ns8/full/         # Script NethServer 8
├── script-check-proxmox/full/     # Script Proxmox
├── script-check-ubuntu/full/      # Script Ubuntu
├── script-tools/full/             # Tools vari
├── script-notify-checkmk/full/    # Notifiche CheckMK
└── Ydea-Toolkit/full/             # Integrazione Ydea

```text

**Output Esempio:**

```text

================================================================
    RISULTATI VERIFICA INTEGRITÀ
================================================================

RIEPILOGO GENERALE:
  Script verificati:    451
  Script validi:        387
  Script con errori:    64
  Percentuale errori:   14.19%
  Soglia corruzione:    15%

DETTAGLIO PER TIPO:
  Bash/Shell
    Totale:      416
    Validi:      352
    Errori:      64 (15.4%)

[STATO] WARNING - Errori rilevati ma sotto soglia

```text

---

## 🎯 Workflow Consigliato

### ⚠️ REGOLA OBBLIGATORIA - Validazione Script

#### Bash/Shell Script

**SEMPRE quando crei o modifichi uno script Bash/Shell:**
1. ✅ Testa con `wsl bash -n <file_path>`
2. ✅ Verifica che `$LASTEXITCODE -eq 0`
3. ✅ Se exit code ≠ 0, correggi gli errori e ritesta
4. ✅ Ripeti finché non ottieni exit code 0
5. ✅ Solo allora considera il file completato

**Comando PowerShell da usare:**

```powershell
wsl bash -n "path/to/script.sh"; echo "EXIT CODE: $LASTEXITCODE"

```text

**Non procedere mai senza exit code 0!**

#### PowerShell Script (.ps1)

**SEMPRE quando crei o modifichi uno script PowerShell:**
1. ✅ Valida con PSParser
2. ✅ Verifica che errori count = 0
3. ✅ Se errori presenti, correggi e ritesta
4. ✅ Ripeti finché non ottieni 0 errori
5. ✅ Solo allora considera il file completato

**Comando validazione da usare:**

```powershell
$errors = $null; $null = [System.Management.Automation.PSParser]::Tokenize((Get-Content "path/to/script.ps1" -Raw), [ref]$errors); if ($errors.Count -eq 0) { Write-Host "Sintassi OK" -ForegroundColor Green } else { Write-Host "ERRORI:" -ForegroundColor Red; $errors }; Write-Host "EXIT CODE: $LASTEXITCODE"

```text

**Errori comuni PowerShell:**
- ❌ Carattere `%` non escaped in stringhe → Usare `$($variabile)%`
- ❌ Regex anchor `\z` → Preferire `$` (più compatibile)
- ❌ Apici/virgolette non chiuse correttamente

**Non procedere mai se PSParser riporta errori!**

### 📂 REGOLA DEPLOYMENT - Path Script Repository

**⚠️ IMPORTANTE: Repository già clonato su tutte le macchine**

**Path repository locale:**
- ✅ **TUTTE le macchine (server e host) hanno git clone in `/opt/checkmk-tools/`**
- ✅ Repository aggiornato automaticamente (git pull automatico)
- ✅ Preferire esecuzione locale quando disponibile (più comodo/veloce)
- ⚠️ **ATTENZIONE: Il clone locale è READ-ONLY** - qualsiasi modifica viene sovrascritta dal git pull automatico
- ❌ **MAI modificare file in `/opt/checkmk-tools/`** - modifiche si perdono sistematicamente

**Ordine di priorità:**
1. **Locale (se disponibile)**: `/opt/checkmk-tools/script-tools/full/script-name.sh` (più comodo)
2. **GitHub raw**: `https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/...` (funziona ugualmente bene)

**Esempi esecuzione locale:**

```bash
# Esecuzione diretta da repo locale
/opt/checkmk-tools/script-tools/full/installation/install-agent-interactive.sh

# Cron job - usa repo locale
0 3 * * * /opt/checkmk-tools/script-tools/full/backup_restore/cleanup-checkmk-retention.sh >> /var/log/script.log 2>&1

# Con bash esplicito
bash /opt/checkmk-tools/script-tools/full/script-name.sh

```text

**Esempi esecuzione da GitHub (fallback o host remoti):**

```bash
# Cron job - esecuzione diretta da GitHub
0 3 * * * curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash >> /var/log/script.log 2>&1

# Esecuzione manuale remota
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/script-name.sh | bash

```text

**Vantaggi path locale:**
- ✅ Più veloce (no download)
- ✅ Funziona offline
- ✅ Stesso codice su tutti i server (git pull auto)

**Vantaggi GitHub raw (curl/wget):**
- ✅ Funziona ugualmente bene
- ✅ Sempre ultima versione GitHub
- ✅ Utile per host remoti o bootstrap

**⚠️ WORKFLOW TEST OBBLIGATORIO - Repository Locale**

**REGOLA FONDAMENTALE (da seguire SEMPRE durante test):**

1. **PRIMA di ogni test su host remoto**:
   - ✅ Verifica presenza `/opt/checkmk-tools/`
   - ✅ Se NON esiste → clonalo manualmente
   - ✅ Se esiste → aggiornalo con `git pull`
   - ✅ Usa SEMPRE path locale per test (NO GitHub raw)

2. **Workflow corretto test:**

```bash
# STEP 1: Verifica + crea/aggiorna repo locale
wsl -d kali-linux ssh <host> "[ -d /opt/checkmk-tools ] && echo 'REPO EXISTS' || echo 'REPO MISSING'"

# Se REPO MISSING → clona
wsl -d kali-linux ssh <host> "git clone https://github.com/Coverup20/checkmk-tools.git /opt/checkmk-tools"

# Se REPO EXISTS → aggiorna
wsl -d kali-linux ssh <host> "cd /opt/checkmk-tools && git pull"

# STEP 2: Esegui test da repo LOCALE (NON da GitHub!)
wsl -d kali-linux ssh <host> "/opt/checkmk-tools/script-check-ns7/full/check-sos-ns7.py"

# ✅ VANTAGGI:
# - Nessun problema cache GitHub
# - Versione garantita post-commit
# - Più veloce (no download)
```

3. **Test con launcher remoto:**

```bash
# Aggiorna repo
wsl -d kali-linux ssh <host> "cd /opt/checkmk-tools && git pull"

# Test launcher da repo locale
wsl -d kali-linux ssh <host> "/opt/checkmk-tools/script-check-ns7/remote/rcheck-sos-ns7.py"

# ✅ Launcher scarica full/ da GitHub (comportamento normale)
# ✅ Ma launcher stesso viene da repo locale aggiornato
```

**⚠️ QUANDO usare GitHub raw:**
- ❌ **MAI** per test durante sviluppo (cache 5 min!)
- ✅ Solo per bootstrap iniziale (host senza repo)
- ✅ Solo per esempi documentazione

**⚠️ REGOLA IMPORTANTE: Modifiche al repository**
- ✅ Modifiche SOLO su VSCode locale (Windows)
- ✅ Commit e push da VSCode
- ✅ Git pull manuale/automatico distribuisce a tutti i server
- ❌ **MAI modificare file in `/opt/checkmk-tools/` sui server remoti**
- ❌ Modifiche locali vengono perse al prossimo git pull

### Prima di ogni commit importante:

1. Eseguire `.\script-ps-tools\check-integrity.ps1` per verificare lo stato
2. Se errori >15%, indagare prima di committare
3. Verificare che tutti gli script .sh siano eseguibili

### Dopo modifiche massive:

1. Eseguire `.\script-ps-tools\check-integrity.ps1 -Detailed` per vedere tutti gli errori
2. Valutare se è necessario riparare script corrotti
3. Usare `.\script-ps-tools\repair-corrupted-scripts.ps1` se disponibile

### Monitoraggio periodico:

- **Settimanale**: `.\script-ps-tools\check-integrity.ps1 -ExportReport` per storico
- **Mensile**: Analizzare trend corruzione nel tempo

---

## 📚 Strumenti di Backup Repository

### backup-simple.ps1 - Backup Completo con Controllo Integrità

**Quando usare:**
- Backup scheduled automatici (task schedulato)
- Backup periodici completi con validazione
- Quando non è stato eseguito recentemente `check-integrity.ps1`

**Caratteristiche:**
- ✅ Controllo integrità completo di tutti gli script (PS1, Bash, Python)
- ✅ Validazione sintassi con PSParser e `bash -n`
- ✅ Blocco automatico se corruzione >15% (protezione propagazione errori)
- ✅ Report dettagliato errori via email
- ✅ Backup locale + rete
- ✅ Retention policy automatica (20 backup)

**Comandi:**

```powershell
# Modalità interattiva
.\script-ps-tools\backup-simple.ps1

# Modalità automatica (scheduled task)
.\script-ps-tools\backup-simple.ps1 -Unattended
```

**Tempo esecuzione:** ~2-5 minuti (dipende da numero script)

---

### backup-quick.ps1 - Backup Veloce senza Controllo Integrità

**Quando usare:**
- Durante workflow conversione Python (dopo ogni categoria completata)
- Backup rapidi post-commit quando integrità già verificata
- Situazioni dove velocità è prioritaria

**Caratteristiche:**
- ✅ Backup immediato senza validazione sintassi
- ✅ Backup locale + rete
- ✅ Retention policy automatica (20 backup)
- ✅ Report via email (senza sezione integrità)
- ⚠️ Presuppone che `check-integrity.ps1` sia stato eseguito separatamente

**Comandi:**

```powershell
# Modalità interattiva
.\script-ps-tools\backup-quick.ps1

# Modalità automatica (workflow Python)
.\script-ps-tools\backup-quick.ps1 -Unattended
```

**Tempo esecuzione:** ~30-60 secondi

---

### Confronto Script Backup

| Caratteristica | backup-simple.ps1 | backup-quick.ps1 |
|----------------|-------------------|------------------|
| Controllo integrità | ✅ Sì | ❌ No |
| Validazione sintassi | ✅ PSParser + bash -n | ❌ No |
| Blocco corruzione >15% | ✅ Sì | ❌ No |
| Backup locale | ✅ Sì | ✅ Sì |
| Backup rete | ✅ Sì | ✅ Sì |
| Retention policy | ✅ Sì | ✅ Sì |
| Email report | ✅ Con integrità | ✅ Senza integrità |
| Tempo esecuzione | 2-5 min | 30-60 sec |
| Uso consigliato | Task periodici | Workflow conversione |

---

### Workflow Consigliato

**Conversione Python (categoria completa):**
```powershell
# 1. Converti tutti gli script della categoria
# 2. Testa e deploya tutti
# 3. Backup veloce
.\script-ps-tools\backup-quick.ps1 -Unattended
```

**Backup periodico completo:**
```powershell
# Task schedulato (es: ogni notte)
.\script-ps-tools\backup-simple.ps1 -Unattended
```

**Verifica integrità on-demand:**
```powershell
# Controllo manuale senza backup
.\script-ps-tools\check-integrity.ps1 -Detailed
```

---

## 📚 Strumenti Correlati

- **check-integrity.ps1**: Controllo integrità senza backup
- **repair-corrupted-scripts.ps1**: Riparazione automatica script corrotti
- **WSL**: Necessario per validazione Bash (`bash -n`)

---

## 🔧 Agent CheckMK - Installazione/Aggiornamento

**⚠️ IMPORTANTE: Usare sempre lo script dedicato per agent CheckMK**

### Script da usare:

```bash
# Su server remoti CheckMK
/opt/checkmk-tools/script-tools/full/installation/install-agent-interactive.sh

# Da GitHub (se repo non clonato)
curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/installation/install-agent-interactive.sh | bash

```text

### Cosa fa lo script:

- ✅ Rileva OS automaticamente (Debian/Ubuntu/RHEL/OpenWrt)
- ✅ Scarica agent corretto dalla versione CheckMK server
- ✅ **Disabilita automaticamente `cmk-agent-ctl-daemon.service`** (causa conflitti porta 6556)
- ✅ Configura socket TCP plain su porta 6556
- ✅ Gestisce correttamente systemd/xinetd/procd
- ✅ Opzionale: configura FRPC per tunnel

### Problema comune:

**NON usare solo `dpkg -i check-mk-agent.deb`** perché:
- ❌ Lascia attivo `cmk-agent-ctl-daemon` che va in conflitto
- ❌ Non configura correttamente il socket TCP
- ❌ Causa errore "Address in use (os error 98)"

### Fix se già installato manualmente:

```bash
# Disabilita daemon problematico
systemctl disable --now cmk-agent-ctl-daemon.service
systemctl reset-failed cmk-agent-ctl-daemon.service

# L'agent continua a funzionare via check-mk-agent.socket

```text

---

## 🐍 Conversione Script Bash → Python - Best Practices

**⚠️ POLICY PYTHON-FIRST (dal 13 Febbraio 2026):**

- ✅ **TUTTI i nuovi script DEVONO essere scritti in Python**
- ✅ Python è la lingua ufficiale per nuovi check/tool/automation
- ❌ Bash solo per wrapper minimali o casi eccezionali giustificati
- ✅ Script bash esistenti vanno gradualmente convertiti in Python
- ✅ Launcher remoti: SEMPRE Python puri (urllib + exec), NO bash+curl

**Motivazioni:**

- Robustezza parsing e error handling superiore
- Type hints per sicurezza e manutenibilità
- Testing più facile e completo
- Portabilità e consistenza codebase
- Unico linguaggio significa unica expertise da mantenere

**⚠️ WORKFLOW COMPLETO per conversione script esistenti:**

### 1. Strategia Conversione

**Quando convertire bash → Python:**
- ✅ Script con parsing complesso (output comandi, regex, testo strutturato)
- ✅ Script con logica condizionale articolata
- ✅ Necessità di error handling robusto
- ✅ Script che beneficiano di type hints e modularità
- ✅ Script destinati a evolversi (più feature nel tempo)

**Vantaggi Python:**
- ✅ Parsing più robusto (regex, split, strip vs sed/awk/grep)
- ✅ Error handling elegante (try/except vs if/then)
- ✅ Type hints per sicurezza e documentazione
- ✅ Modularità con funzioni documentate (docstring)
- ✅ Testing più facile (unit tests, mock)
- ✅ Libreria standard ricca (subprocess, urllib, json, etc.)

### 2. Template Script Python CheckMK Local Check

```python
#!/usr/bin/env python3
"""
check_service_name.py - CheckMK Local Check per <descrizione>

<Descrizione funzionalità dettagliata>

Version: 1.0.0
"""

import subprocess
import sys
import re
from typing import Tuple, List, Optional

VERSION = "1.0.0"
SERVICE = "ServiceName"


def run_command(cmd: List[str]) -> Tuple[int, str, str]:
    """
    Execute a shell command and return exit code, stdout, stderr.
    
    Args:
        cmd: Command as list of strings
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timeout"
    except FileNotFoundError:
        return 127, "", "Command not found"
    except Exception as e:
        return 1, "", str(e)


def main() -> int:
    """
    Main check logic.
    
    Returns:
        Exit code (always 0 for CheckMK local checks)
    """
    # Check logic here
    # Output format: <STATE> <SERVICE> - <message>
    # STATE: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN
    
    print(f"0 {SERVICE} - OK message")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 3. Pattern CheckMK Output

**Format obbligatorio local check:**

```text
<STATE> <SERVICE_NAME> - <message>
```

**State codes:**

- `0` = OK (verde)
- `1` = WARNING (giallo)
- `2` = CRITICAL (rosso)
- `3` = UNKNOWN (arancione)

**Exit code script:**

- SEMPRE `0` per local checks (CheckMK ignora exit code, legge solo primo campo output)

### 4. Deploy Diretto da Repo Locale (NO Launcher)

❌ **LAUNCHER DEPRECATI** - Non creare più script `remote/rssh_*.py`

✅ **POLICY ATTUALE: Deploy diretto dello script `full/` da `/opt/checkmk-tools/`**

**Motivazione:**
- Il repo `/opt/checkmk-tools/` è già presente su tutti gli host (git pull automatico ogni minuto)
- Deploy diretto = nessun download HTTP in runtime, funziona offline
- Meno file da mantenere, meno complessità
- Nessun doppio step (launcher → download → exec)

**Metodo deploy:**

```bash
# Aggiorna repo locale
cd /opt/checkmk-tools && git pull

# Copia script full/ nella directory local checks (SENZA estensione)
cp script-check-<categoria>/full/check_service_name.py /usr/lib/check_mk_agent/local/check_service_name
chmod +x /usr/lib/check_mk_agent/local/check_service_name

# Test immediato
/usr/lib/check_mk_agent/local/check_service_name
```

**Nome file deployato:**
- SENZA estensione `.py` (CheckMK esegue tutti i file eseguibili)
- Usa direttamente il nome del check: `check_nethvoice_trunks`, `check_fail2ban_status`, etc.
- ❌ Niente più prefisso `rssh_`

### 5. Workflow Completo Conversione/Nuovo Script

**Step OBBLIGATORI (seguire SEMPRE):**

```bash
# 1. Crea script Python completo (full/)
vim script-check-ubuntu/full/check_service_name.py
# Implementa funzionalità con template sopra

# 2. Valida sintassi Python
python -m py_compile script-check-ubuntu/full/check_service_name.py
# EXIT CODE deve essere 0

# 3. Rendi eseguibile e aggiungi a git
git add script-check-ubuntu/full/check_service_name.py
git update-index --chmod=+x script-check-ubuntu/full/check_service_name.py

# 4. Verifica permessi (devono mostrare 100755)
git ls-files -s script-check-ubuntu/full/check_service_name.py

# 5. Commit & Push
git commit -m "feat(ubuntu): check_service_name v1.0.0 - descrizione"
git push

# 6. Deploy su host remoto (aggiorna repo + copia direttamente)
# HOST CON CHIAVE SSH (vps-01, vps-02):
wsl -d kali-linux ssh <host> "cd /opt/checkmk-tools && git pull && cp script-check-ubuntu/full/check_service_name.py /usr/lib/check_mk_agent/local/check_service_name && chmod +x /usr/lib/check_mk_agent/local/check_service_name"

# HOST CON PASSWORD (tutti gli altri): dare i comandi da incollare:
# cd /opt/checkmk-tools && git pull
# cp script-check-ubuntu/full/check_service_name.py /usr/lib/check_mk_agent/local/check_service_name
# chmod +x /usr/lib/check_mk_agent/local/check_service_name

# 7. Test local check
wsl -d kali-linux ssh <host> "/usr/lib/check_mk_agent/local/check_service_name"

# 8. Verifica output agent CheckMK
wsl -d kali-linux ssh <host> "check_mk_agent 2>/dev/null | grep ServiceName"
# Deve mostrare UNA SOLA riga con output check
```

❌ **NON creare cartella `remote/` né file `rssh_*.py`** - non servono più.

### 6. Naming Convention

**File nel repository:**

- `script-check-<categoria>/full/check_service_name.py` → Script completo Python (unico file da creare)
- `script-check-<categoria>/full/check_service_name.sh` → Script bash OLD (deprecato, non creare nuovi)
- ❌ `script-check-<categoria>/remote/` → NON creare più questa cartella/file

**File deployati su host (local checks):**

- `/usr/lib/check_mk_agent/local/check_service_name` → Script deployato SENZA estensione `.py`
- Nome uguale al file `full/` senza `.py` (es: `check_nethvoice_trunks`)
- CheckMK esegue tutti i file eseguibili nella directory

### 7. Migrazione Graduale

**Quando converti uno script bash esistente:**

1. ✅ Mantieni versione bash originale (`.sh`) nel repository durante transizione
2. ✅ Crea nuova versione Python (`.py`) in `full/`
3. ✅ Testa script Python direttamente su host pilota
4. ✅ Se tutto OK → sostituisci il file deployato in `/usr/lib/check_mk_agent/local/` con la versione Python
5. ✅ OPZIONALE: Rimuovi `.sh` dal repository dopo periodo transizione

**NON eliminare mai script bash senza test completo Python!**
❌ **NON creare launcher `remote/rssh_*`** - deploy diretto da repo locale.

### 8. Testing Obbligatorio

**Checklist test prima di dichiarare conversione completata:**

- ✅ Validazione sintassi Python (py_compile)
- ✅ Esecuzione script completo su host remoto
- ✅ Output compatibile CheckMK format (`<STATE> <SERVICE> - <msg>`)
- ✅ Check appare in `check_mk_agent` output
- ✅ NO duplicati (solo 1 istanza del check nell'output agent)
- ✅ Comportamento identico a versione bash (stessi state codes, stessi messaggi)

**⚠️ BACKUP A FINE CATEGORIA:**

- ✅ **BACKUP OBBLIGATORIO**: A fine conversione **intera categoria/cartella**
- ✅ Esempio: dopo aver completato TUTTI gli script di `script-check-ubuntu/` → `.\script-ps-tools\backup-quick.ps1 -Unattended`
- ❌ NON eseguire backup dopo ogni singolo script
- ✅ Eseguire backup solo quando categoria completa è testata e deployata
- ✅ `script-ps-tools\backup-quick.ps1` è ottimizzato per workflow conversione (NO controllo integrità)
- ℹ️ Controllo integrità eseguito separatamente con `.\script-ps-tools\check-integrity.ps1` quando necessario

### 9. Esempio Completo Real World

**Caso studio: check_fail2ban_status.sh → check_fail2ban_status.py**

**Commit History:**

- `c0e26d5`: Creazione `check_fail2ban_status.py` (script completo)
- `64bfdee`: Creazione `rssh_fail2ban_status_py.sh` (launcher bash - deprecato)
- `f108044`: Refactor `rssh_fail2ban_status.py` (launcher Python puro)

**Path finali:**

- Repository: `script-check-ubuntu/full/check_fail2ban_status.py` (script completo)
- Repository: `script-check-ubuntu/remote/rssh_fail2ban_status.py` (launcher Python)
- Deployato: `/usr/lib/check_mk_agent/local/rssh_fail2ban_status` (launcher senza .py)

**Output produzione:**

```text
0 Fail2ban - running, no banned IPs
```

---

## �🔌 Accesso Remoto SSH - VPS e Server Locali

### Setup WSL SSH

**Environment configurato:**
- ✅ WSL: **Kali Linux** su Windows (`wsl -d kali-linux bash -c "command"`)
- ✅ SSH Keys: `~/.ssh/checkmk` (protetta da passphrase)
- ✅ SSH Config: `~/.ssh/config` con alias host
- ✅ SSH ControlMaster: Riutilizzo connessioni (passphrase 1 volta, poi 1 min attiva)

**⚠️ REGOLA FORMATO COMANDI - Quando l'utente chiede "comandi da incollare":**

- Passare il comando **nudo**, senza wrapper `wsl -d kali-linux ssh ...`
- L'utente lo incolla direttamente nel terminale remoto già aperto
- SBAGLIATO: `wsl -d kali-linux ssh -tt -o ControlMaster=no -J sos -p 2333 root@45.33.235.86 "apt-get install -y git"`
- CORRETTO: `apt-get install -y git`
- Usare il wrapper `wsl -d kali-linux ssh ...` SOLO quando si esegue da VS Code terminal in modo autonomo

**⚠️ REGOLA PRATICA - Password SSH (no “pausa continua”):**

- ✅ Usa `ssh -tt` quando prevedi prompt (password/confirm)
- ⚠️ Se compare davvero un prompt `password for ...:`/`[sudo] password for ...:` → fermarsi solo finché la password non viene inserita
- ✅ Non forzare `sudo`/`sudo -v` “di default”: usare `sudo` solo quando serve e quando l’utente lo sta effettivamente facendo (o lo richiede)

**⚠️ REGOLA CRITICA - Timeout Comandi SSH Remoti:**
- ⚠️ **PROBLEMA**: Agent SSH va troppo veloce e pensa che utente abbia interrotto (^C), ma in realtà comando stava ancora elaborando
- ✅ **SOLUZIONE**: Usare timeout GENEROSI per comandi remoti
- ✅ **Timeout consigliati**:
  - Comandi semplici (ls, cat, echo): `timeout: 10000` (10 sec)
  - Comandi SSH normali (script execution): `timeout: 30000` (30 sec)
  - Comandi SSH complessi (check_mk_agent, git operations): `timeout: 60000` (60 sec)
  - Backup/restore/operazioni massive: `timeout: 120000` (2 min)
- ⚠️ **MAI usare timeout < 10000** per comandi SSH
- ✅ **ASPETTARE completamento** anche se sembra lento - il comando sta lavorando
- ❌ **NON assumere** che ^C nell'output significhi interruzione utente - potrebbe essere timeout tool troppo breve

**🔴 REGOLA CRITICA - NON lanciare un secondo comando SSH prima dell'output del primo:**
- ❌ **MAI** lanciare un nuovo comando SSH mentre il precedente è ancora in attesa di password o output
- ❌ **MAI** usare `get_terminal_output` subito dopo e poi lanciare un secondo comando "perché il primo non ha risposto"
- ✅ **SEMPRE** usare `terminal_last_command` per leggere l'output del comando in corso
- ❌ **NON** lanciare un comando alternativo "più semplice" se il primo non risponde subito - ASPETTARE

**🔴 REGOLA CRITICA - Leggere SEMPRE l'output prima di parlare:**
- ✅ **PRIMA di dire qualsiasi cosa** dopo un comando → controlla exit code nel context
- ✅ **Se exit code = 0** → chiama `terminal_last_command` immediatamente e leggi l'output
- ✅ **Solo se exit code = unknown / comando ancora in esecuzione** → aspetta o chiedi
- ❌ **MAI** dire "inserisci la password" o "aspetta il completamento" se exit code è già 0
- ❌ **MAI** rilanciate un comando se il precedente ha già exit code 0 — l'output è già disponibile

**🔴 REGOLA GENERALE - Host con autenticazione PASSWORD (checkmk-z1plus, ns-lab00, laboratorio, srv-monitoring, etc.):**
- ❌ **MAI** tentare connessioni SSH autonome via `run_in_terminal` su host con password
  → il tool non può inserire la password → fallisce sempre con `^C` o timeout
- ✅ **SE il primo tentativo `run_in_terminal` su host-password fallisce** (output `^C` o vuoto):
  → NON riprovare
  → Dare IMMEDIATAMENTE i comandi da incollare nel terminale dell'utente
- ✅ **ECCEZIONE**: checkmk-vps-01 e checkmk-vps-02 usano chiave SSH → run_in_terminal funziona
- ⚠️ **NOTA CRITICA**: avere l'alias host in `~/.ssh/config` NON significa accesso senza password!
  → La config WSL definisce parametri di connessione, NON autentica automaticamente
  → Se l'host usa password, il tool va in `^C` indipendentemente dall'alias configurato
- ✅ **Classificazione host per metodo auth**:
  - 🔑 **CHIAVE SSH** (run_in_terminal OK): checkmk-vps-01, checkmk-vps-02
  - � **ControlMaster SSH** (run_in_terminal OK - socket auto): srv-monitoring → `wsl -d kali-linux bash -c "ssh -tt srv-monitoring 'cmd'"`
  - 🔐 **PASSWORD** (dare comandi da incollare): checkmk-z1plus, checkmk-testfrp, nodo-proxmox, ns-lab00, box-lab00, rl94ns8, rl94ns81, nsec8-stable, laboratorio, marziodemo, ubntmarzio, fwlab, redteam

**Host disponibili:**

```bash
# VPS CheckMK (chiave: ~/.ssh/checkmk + passphrase)
checkmk-vps-01    # monitor.nethlab.it (CheckMK 2.4.0p19.cre) - PRODUZIONE
                  # ⚠️ rclone configurato dentro il site OMD (non root)
                  # Path: /opt/omd/sites/monitoring/.config/rclone/rclone.conf
                  # Comandi: omd su monitoring -c "rclone ..."
checkmk-vps-02    # monitor01.nethlab.it - ⚠️ TEST CRITICI / STAGING

# Server locali CheckMK (autenticazione password)
checkmk-z1plus    # 192.168.10.128 (locale)
checkmk-testfrp   # 192.168.10.126 (user: admin_nethesis)

# Server locali altri (autenticazione password)
nodo-proxmox      # 10.155.100.20:22 (root, Proxmox VE)
ns-lab00          # 192.168.10.100:2222 (root, NethServer 7)
box-lab00         # 192.168.10.132:22 (root) - Host share \\192.168.10.132\usbshare
rl94ns8           # 10.155.100.40:22 (root, NethServer 8)
                  # Moduli: samba1, mail2, webtop1, webtop3
                  # Nodo completo per test report quindicinale NS8 (AD + Mail + WebTop)
rl94ns81          # 10.155.100.41:22 (root, NethServer 8)
                  # Moduli: webtop1 (con Postgres attivo)
                  # Nodo WebTop per test condivisioni email
nsec8-stable      # 10.155.100.100:22 (root, NethSecurity 8)
                  # Agent CheckMK installato con: install-checkmk-agent-persistent-nsec8.sh
                  # Path: /opt/checkmk-tools/script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh
laboratorio       # 10.155.100.1:2222 (root, NethSecurity 8)
                  # ROCKSOLID Mode validato - resistente major upgrade
marziodemo        # 10.155.100.61:22 (root, Demo environment)
ubntmarzio        # 10.155.100.108:22 (user: marzio)
srv-monitoring    # 45.33.235.86:2333 (root, Monitoring)
                  # ⚠️ USARE SEMPRE root@45.33.235.86 - MAI admin-nethesis o altri utenti!
                  # ⚠️ NON usare sudo (connessione già come root - sudo non serve)
                  # ✅ OMD installato: sito 'monitoring' in /omd/sites/monitoring/
                  # ✅ rclone configurato: /opt/omd/sites/monitoring/.config/rclone/rclone.conf (remote 'do', bucket 'testmonbck')
                  # ✅ Backup locali in: /var/backups/checkmk/
                  # ✅ Cloud push: checkmk-cloud-backup-push@monitoring.timer (ogni minuto)
                  # ✅ Comandi OMD come root: su - monitoring -c "comando"
                  # Firewall pubblico 45.33.235.86 porta 2333 → DNAT → 127.0.0.1:2222 interno
                  # ⚠️ fail2ban attivo sul firewall - NON fare tentativi multipli di connessione
                  # ⚠️ Firewall whitelist solo IP 159.65.203.113 (alias sos) - OBBLIGATORIO jump via sos
                  # ⚠️ Autenticazione PASSWORD (non chiave SSH) - NON installare chiavi SSH
                  # ✅ Comando accesso diretto (da WSL):
                  #   wsl -d kali-linux ssh srv-monitoring          (usa alias ~/.ssh/config in WSL)
                  # ✅ Config WSL ~/.ssh/config entry OBBLIGATORIA:
                  #   Host srv-monitoring
                  #       HostName 45.33.235.86
                  #       Port 2333
                  #       User root
                  #       ProxyJump sos
                  #       ControlMaster auto
                  #       ControlPath ~/.ssh/sockets/%r@%h:%p
                  #       ControlPersist 60m
                  # ✅ Comando corretto: wsl -d kali-linux bash -c "ssh srv-monitoring 'cmd'"  (NO -tt!)
                  # ✅ Prima connessione chiede password, poi socket attivo per 60 minuti (ControlPersist 60m)
                  #
                  # ✅ REGOLA - srv-monitoring: ESEGUIRE AUTONOMAMENTE con run_in_terminal
                  #    → Il socket ControlMaster funziona, abbiamo eseguito comandi più volte autonomamente
                  #    → Comando base: wsl -d kali-linux bash -c "ssh srv-monitoring 'cmd'"
                  #    → ⚠️ NON usare -tt flag (causa ^C), usare senza -tt
                  #    → ⚠️ Per rclone con su - monitoring: usare escape backslash per spazi nel -c
                  #       CORRETTO: wsl -d kali-linux bash -c "ssh srv-monitoring 'su - monitoring -c rclone\ ls\ do:testmonbck/...'"
                  #       SBAGLIATO: wsl -d kali-linux bash -c "ssh srv-monitoring 'su - monitoring -c \"rclone ls ...\"'"
                  #    → Se il socket è scaduto → ritentare eseguendo comunque, non delegare all'utente
                  #    → Timeout consigliato: 60000ms (60 sec)
                  # ✅ Non usare più di un blocco per operazione (evitare back-and-forth inutile)

# Altri server
fwlab             # 192.168.5.117:2222 (root)
redteam           # redteam.security.nethesis.it (root)

```text

### 🚀 Workflow Accesso Remoto

**⚠️ IMPORTANTE - Ambiente Test:**
- **checkmk-vps-02** (monitor01.nethlab.it) è dedicato ai **TEST CRITICI**
- Usare **SEMPRE** vps-02 per testare:
  - Nuovi script di disaster recovery
  - Modifiche agli script di backup/restore
  - Upgrade CheckMK con cambiamenti critici
  - Test di procedure che potrebbero compromettere il sistema
- **NON testare direttamente su vps-01 (produzione)**

**1. Comando singolo SSH:**

```powershell
# Da PowerShell → esegui comando su VPS (con timeout generoso)
wsl -d kali-linux ssh checkmk-vps-01 "omd version"
# timeout: 30000 (30 sec) - comando SSH normale

wsl -d kali-linux ssh checkmk-vps-02 "omd sites"
# timeout: 30000 (30 sec)

# Comando complesso (check_mk_agent, git pull)
wsl -d kali-linux ssh ns-lab00 "check_mk_agent"
# timeout: 60000 (60 sec) - comando complesso, output lungo

wsl -d kali-linux ssh ns-lab00 "cd /opt/checkmk-tools && git pull"
# timeout: 60000 (60 sec) - operazione git remota
```

**2. Esecuzione script da GitHub:**

```powershell
# Download ed esecuzione diretta script dal repository
wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash"

# Con parametri
wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/script.sh | bash -s -- arg1 arg2"

```text

**3. Verifica stato CheckMK remoto:**

```powershell
# Check rapido su tutti i VPS
wsl -d kali-linux ssh checkmk-vps-01 "omd status"
wsl -d kali-linux ssh checkmk-vps-02 "omd status"

# Verifica backup
wsl -d kali-linux ssh checkmk-vps-01 "ls -lh /opt/omd/sites/monitoring/var/check_mk/notify-backup/"

```text

**4. Deploy script su VPS:**

```powershell
# NON copiare file, eseguire sempre da GitHub!
# ❌ SBAGLIATO: scp script.sh checkmk-vps-01:/usr/local/bin/
# ✅ CORRETTO: esegui da GitHub con curl

wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash"

```text

### 🔐 Note Sicurezza

- **Passphrase**: Le chiavi richiedono passphrase ad ogni comando
  - Non è un problema: inserire passphrase quando richiesta
  - Protegge accesso non autorizzato

- **StrictHostKeyChecking no**: Disabilitato per automazione
  - OK per ambiente lab/interno
  - Valutare riabilitazione per produzione

### 🎯 Use Cases Comuni

**Controllo integrità remoto:**

```powershell
# Esegui check-integrity su VPS
wsl -d kali-linux ssh checkmk-vps-01 "curl -fsSL https://raw.githubusercontent.com/Coverup20/checkmk-tools/main/script-tools/full/backup_restore/cleanup-checkmk-retention.sh | bash -n"

```text

**Verifica logs:**

```powershell
wsl -d kali-linux ssh checkmk-vps-01 "tail -100 /omd/sites/monitoring/var/log/notify.log"

```text

**Raccolta info sistema:**

```powershell
wsl -d kali-linux ssh checkmk-vps-01 "df -h && free -h && uptime"

```text

### ⚙️ Path Chiavi e Config

```bash
# WSL paths
~/.ssh/checkmk              # Chiave privata VPS (con passphrase)
~/.ssh/config               # Configurazione SSH
~/.ssh/known_hosts          # Host verificati

# Windows paths originali (backup)
C:\Users\Marzio\.ssh\checkmk

```text

---

## ☁️ Backup Cloud - rclone su CheckMK

**⚠️ IMPORTANTE - Configurazione rclone su checkmk-vps-01:**
- ✅ rclone è configurato **dentro il site OMD**, NON come utente root
- ✅ Path config: `/opt/omd/sites/monitoring/.config/rclone/rclone.conf`
- ✅ Remote configurato: `do` (DigitalOcean Spaces)
- ✅ Bucket: `testmonbck`
- ✅ Struttura: `checkmk-backups/job00-daily/`, `checkmk-backups/job01-weekly/`, `checkmk-backups/monitoring-minimal/`

**Comandi corretti per accesso rclone:**

```bash
# ❌ SBAGLIATO (comando errato)
ssh checkmk-vps-01 'rclone ls do:testmonbck'
ssh checkmk-vps-01 'omd su monitoring -c "rclone ..."'

# ✅ CORRETTO (su - monitoring -c)
ssh checkmk-vps-01 'su - monitoring -c "rclone ls do:testmonbck"'

# Lista ultimi backup
ssh checkmk-vps-01 'su - monitoring -c "rclone ls do:testmonbck"' | tail -20

# Lista cartella specifica
ssh checkmk-vps-01 'su - monitoring -c "rclone ls do:testmonbck/checkmk-backups/job00-daily/"'

# Verifica spazio bucket
ssh checkmk-vps-01 'su - monitoring -c "rclone size do:testmonbck"'

# Download backup specifico
ssh checkmk-vps-01 'su - monitoring -c "rclone copy do:testmonbck/checkmk-backups/job00-daily/file.tar.gz /tmp/"'

```text

**Backup disponibili:**
- **job00-daily**: Backup daily completi (~1.2 MB)
- **job01-weekly**: Backup weekly completi con history (~378 MB)
- **monitoring-minimal**: Backup ultra-minimali (~115 KB)

**Script backup automatico:**
- Script: `/opt/checkmk-tools/script-tools/full/backup_restore/checkmk_rclone_space_dyn.sh`
- Eseguito da: site monitoring (non root)
- Cron: Configurato dentro il site OMD

---

## 🚨 INCIDENTI E TROUBLESHOOTING

### 30 Gennaio 2026 - Update Windows + VSCode Crash

**PROBLEMA INIZIALE:**
- Aggiornamento Microsoft Windows ha causato errori all'avvio di VSCode
- Errore principale: `EPIPE: broken pipe, write` su processi interni
- Stack trace mostra crash in `console.value`, `Writable.write`, socket communication

**COSA È STATO FATTO (E PEGGIORATO):**
1. ❌ Tentato reset cache VSCode
2. ❌ Tentato riavvio multipli
3. ❌ **Modificata modalità login in "basic" - QUESTO HA ROTTO TUTTO**
4. ❌ Modifiche a configurazioni interne
5. ⚠️ Update Windows rimosso (TARDI)
6. ❌ Situazione peggiorata invece di migliorare
7. ❌ **Uninstall approfondito con Revo Uninstaller + Reinstall VSCode** - NON ha risolto
8. ❌ Reset cache post-reinstall - NON ha risolto
9. ❌ Riabilitato github.gitAuthentication - NON ha risolto
10. ❌ Restart Windows Explorer - NON ha risolto
11. ❌ Ricreato chiavi registro VSCode (Applications\Code.exe, DefaultIcon) - NON ha risolto

**STATO ATTUALE (30/01/2026 ore ~19:00):**
- VSCode non si avvia o non mostra nulla
- Ultimo danno non risolto
- Necessario ripristino completo
- ⚠️ **PATTERN CRITICO**:
  - Start-Process da PowerShell → VSCode SI AVVIA
  - Click su Code.exe con mouse → NON SI AVVIA
  - Click su collegamento menu Start → NON SI AVVIA
  - Comando `code .` da terminale → SI AVVIA
  - Qualunque azione MANUALE utente → FALLISCE
  - Qualunque azione via COMANDO → FUNZIONA
- ✅ **Problema SPECIFICO di VSCode** - altri exe (notepad, ecc.) funzionano normalmente con doppio click
- ❌ **NON è problema generale Windows** - circoscritto solo a Code.exe

**SOLUZIONE TROVATA (30/01/2026 ore ~19:15):**
- ✅ VSCode si avvia correttamente con:
  ```powershell
  cd C:\Users\Marzio\Desktop\CheckMK\checkmk-tools
  code .
  ```

- ⚠️ Importante fare `cd` nella directory workspace PRIMA di lanciare `code .`
- ⚠️ Non lanciare `code` senza parametri o da directory diversa
- ❌ **Collegamento desktop/start menu NON funziona** - lanciare sempre da terminale
- ❌ **NESSUNA SOLUZIONE TROVATA** per ripristinare funzionamento normale
- ⚠️ Problema causato da Revo Uninstaller che ha cancellato chiavi registro critiche
- ⚠️ Ricreare chiavi registro NON ha risolto - problema più profondo
- ✅ **WORKAROUND TEMPORANEO**: Aprire PowerShell e usare `code .`

**CAUSA ROOT (30/01/2026 ore ~19:45):**

- 🔍 Diagnostica con `Code.exe --verbose` rivela:

  ```text
  Sending some foreground love to the running instance: 17752
  Sent env to running instance. Terminating...
  ```

- ⚠️ **VSCode si connette a istanza zombie nascosta/corrotta** invece di aprire nuova finestra
- Quando lanciato dal collegamento, VSCode rileva istanza esistente (PID 17752) e le invia il comando
- Ma quella finestra è nascosta o corrotta dall'update Windows
- `code .` con workspace funziona perché forza apertura in quel contesto specifico
- Soluzione: killare TUTTI i processi VSCode prima di riaprire dal collegamento

**CAUSA ROOT (30/01/2026 ore ~19:45):**

- 🔍 Diagnostica con `Code.exe --verbose` rivela:

  ```text
  Sending some foreground love to the running instance: 17752
  Sent env to running instance. Terminating...
  ```

- ⚠️ **Problema reale: VSCode aperto come ADMINISTRATOR**
- Windows impedisce apertura multiple istanze Administrator di VSCode
- Tentativo di aprire da collegamento/menu Start → errore "Another instance of Code is already running as administrator"
- `code .` da terminale integrato funziona perché usa stessa istanza admin già aperta
- L'update Windows potrebbe aver forzato VSCode a girare sempre come admin
- **Soluzione da testare**: Chiudere VSCode admin, riaprire senza privilegi elevati

**✅ SOLUZIONE DEFINITIVA (30/01/2026 ore ~22:30) - PROBLEMA RISOLTO:**

**Causa ROOT reale:**

- ⚠️ **Variabile d'ambiente `ELECTRON_RUN_AS_NODE` presente nel sistema**

- ⚠️ **Variabile d'ambiente `ELECTRON_RUN_AS_NODE` presente nel sistema**
- Questa variabile (anche se impostata a "0") causa malfunzionamento di Electron/VSCode
- L'update Windows potrebbe averla introdotta o riattivata
- Sintomi: VSCode si avvia da CLI ma NON da GUI (doppio click/menu Start)

**Fix definitivo (persistente):**

**1. Verifica variabile in cmd.exe:**

```cmd
set ELECTRON_RUN_AS_NODE

```text

Se mostra qualcosa tipo `ELECTRON_RUN_AS_NODE=0` o altro valore → **va rimossa completamente**

**2A. Rimozione via GUI (consigliato):**

```text

1. Win + R → esegui: SystemPropertiesAdvanced
2. Tab "Avanzate" → pulsante "Variabili d'ambiente..."
3. Cerca ELECTRON_RUN_AS_NODE in:
   - "Variabili utente" (sezione superiore)
   - "Variabili di sistema" (sezione inferiore)
4. Se presente → Seleziona → pulsante "Elimina"
5. OK su tutte le finestre
6. Logout/Login Windows (o riavvio)

```text

**2B. Rimozione via CLI (rapido):**

```cmd
# Apri cmd.exe come Amministratore ed esegui:
reg delete "HKCU\Environment" /v ELECTRON_RUN_AS_NODE /f
reg delete "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v ELECTRON_RUN_AS_NODE /f

```text

Poi **logout/login** (o riavvio) Windows.

**3. Verifica dopo logout/login:**

```cmd
set ELECTRON_RUN_AS_NODE

```text

Deve mostrare:

```text

Environment variable ELECTRON_RUN_AS_NODE not defined

```text

**4. Verifica finale VSCode:**

```cmd
"C:\Program Files\Microsoft VS Code\Code.exe" --version
"C:\Program Files\Microsoft VS Code\Code.exe" --disable-extensions

```text

Atteso:
- `--version` **NON deve mostrare** output strano tipo "v22.x.x"
- `--disable-extensions` avvia VSCode correttamente
- Log "Extension host ... exited with code: 0" è normale con estensioni disabilitate

**5. Avvio normale:**

```cmd
"C:\Program Files\Microsoft VS Code\Code.exe"

```text

✅ Doppio click su Code.exe, collegamento menu Start, tutto **funziona correttamente**

**6. Note reinstallazione VSCode (se necessaria):**
- ✅ Usare sempre: **System Installer x64** → `VSCodeSetup-x64-<versione>.exe`
- ❌ Evitare: `VSCodeUserSetup-...` (User Installer), soprattutto dopo feature update Windows

**7. Recupero settings (opzionale):**
Se avevi rinominato `%APPDATA%\Code` (es. `Code.old`):

```powershell
# Chiudi VSCode completamente
# Rinomina per test:
Rename-Item "$env:APPDATA\Code" "$env:APPDATA\Code.new"
Rename-Item "$env:APPDATA\Code.old" "$env:APPDATA\Code"
# Avvia VSCode
# Se problemi ritornano, rollback:
# Rename-Item "$env:APPDATA\Code" "$env:APPDATA\Code.problem"
# Rename-Item "$env:APPDATA\Code.new" "$env:APPDATA\Code"

```text

**⚠️ CHECKPOINT CRITICO:**
- **Variabile ELECTRON_RUN_AS_NODE = poison** per VSCode/Electron
- Sempre verificare con `set ELECTRON_RUN_AS_NODE` in caso di problemi VSCode
- Rimuoverla COMPLETAMENTE (non basta impostarla a "0")
- Logout/login Windows **obbligatorio** dopo rimozione

**LEZIONI APPRESE:**
- ⚠️ Errori `EPIPE: broken pipe` sono **transitori** - NON richiedono riavvio
- ⚠️ Stack trace con path `Microsoft%20VS%20Code/resources.../` indicano problemi **interni VSCode**
- ✅ Prima azione: **rimuovere update Windows SUBITO** (non dopo vari tentativi)
- ✅ Seconda azione: **reset cache minimale** (non modifiche aggressive)
- ❌ **MAI** modificare configurazioni interne senza backup completo
- ✅ Creare **System Restore Point PRIMA** di troubleshooting aggressivo

**PROCEDURE DI RIPRISTINO EMERGENZA VSCode:**

**Step 1 - Reset cache leggero (SEMPRE provare prima):**

```powershell
# Chiudi VSCode
taskkill /F /IM Code.exe

# Cancella solo cache volatile
Remove-Item -Recurse -Force "$env:APPDATA\Code\Cache\*" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:APPDATA\Code\CachedData\*" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:APPDATA\Code\logs\*" -ErrorAction SilentlyContinue

# Riavvia
code

```text

**Step 2 - Reset estensioni (se Step 1 fallisce):**

```powershell
# Backup lista estensioni
code --list-extensions > "$env:USERPROFILE\Desktop\vscode-extensions-backup.txt"

# Disabilita tutte le estensioni
code --disable-extensions

```text

**Step 3 - Reinstallazione pulita (ultimo resort):**

```powershell
# Backup configurazioni utente
Copy-Item -Recurse "$env:APPDATA\Code\User" "$env:USERPROFILE\Desktop\VSCode-User-Backup"

# Disinstalla VSCode (mantieni dati utente)
# Reinstalla versione stabile da https://code.visualstudio.com/

# Ripristina configurazioni
Copy-Item -Recurse "$env:USERPROFILE\Desktop\VSCode-User-Backup\*" "$env:APPDATA\Code\User"

```text

**⚠️ REGOLA CRITICA PER FUTURO:**
- Errori `EPIPE`, `broken pipe`, socket errors = **IGNORARE E CONTINUARE**
- Non sono critici, sono comunicazioni IPC interne che si ripristinano da sole
- Riavvio VSCode window (Ctrl+R) sufficiente se proprio necessario
- **NON FARE** troubleshooting aggressivo per errori transitori

**BACKUP PATH CRITICI:**
- Settings: `$env:APPDATA\Code\User\settings.json`
- Keybindings: `$env:APPDATA\Code\User\keybindings.json`
- Extensions list: `code --list-extensions`
- Workspace: `.vscode/` dentro ogni progetto

---

## 🚀 CHECKPOINT - Sistema ROCKSOLID NethSecurity 8

### ⚠️ STATO ATTUALE (2026-02-10): SISTEMA DISMESSO

**ATTENZIONE:**
- ❌ **Sistema ROCKSOLID rimosso da nsec8-stable e laboratorio** (10 febbraio 2026)
- ❌ **NON eseguire install-checkmk-agent-persistent-nsec8.sh** su nsec8-stable (10.155.100.100) e laboratorio (10.155.100.1)
- ✅ CheckMK Agent e FRP rimangono attivi e funzionanti
- ✅ Repository /opt/checkmk-tools ancora presente (auto-sync git funzionante)
- ❌ Rimossi: /opt/checkmk-backups/, /etc/checkmk-post-upgrade.sh, autocheck rc.local, protezioni sysupgrade.conf

**Componenti rimosse:**
- Backup binari critici (/opt/checkmk-backups/binaries/)
- Script post-upgrade (/etc/checkmk-post-upgrade.sh)
- Autocheck all'avvio (rocksolid-startup-check.sh)
- Protezioni sysupgrade.conf (CheckMK, FRP, QEMU-GA entries)
- Marker FRP (/etc/.frp-installed)

**Componenti mantenuti:**
- CheckMK Agent (porta 6556) - funzionante
- FRP Client + configurazione tunnel
- QEMU Guest Agent
- Repository /opt/checkmk-tools + auto-sync git (cron ogni minuto)

---

### ✅ Implementazione Completata (2026-02-04) - STORICO

**Obiettivo raggiunto:**
- ✅ Eliminazione di TUTTI gli URL statici/hardcoded dagli script di installazione
- ✅ Download dinamico dei pacchetti da repository OpenWrt/NethSecurity
- ✅ Sistema auto-riparante post major-upgrade
- ✅ Validazione completa su host production

**Script validati e production-ready:**

1. **install-checkmk-agent-persistent-nsec8.sh** (commit b29a2cf)
   - Path: `script-tools/full/installation/install-checkmk-agent-persistent-nsec8.sh`
   - Funzione: Installazione completa CheckMK Agent + FRP Client + QEMU-GA + Auto Git Sync
   - Fix implementati:
     - ✅ Dynamic package download via `download_openwrt_package()`
     - ✅ Pattern fix: `grep "${package_name}_"` (corregge rilevamento pacchetti)
     - ✅ Dependencies chain: libbfd → ar → objdump → binutils con `--force-depends`
     - ✅ Gestione corruzione binari (ar corrotto durante upgrade)
   - Test: ✅ nsec8-stable, ✅ laboratorio (da GitHub)

2. **rocksolid-startup-check.sh** (commit ea67364)
   - Path: `script-tools/full/upgrade_maintenance/rocksolid-startup-check.sh`
   - Funzione: Verifica e auto-remediation all'avvio sistema
   - Fix implementati:
     - ✅ Logic reordering: backup restore → corruption check → dependencies install
     - ✅ Git auto-install: download git + git-http da OpenWrt se mancante
     - ✅ Pattern fix identico a install script
     - ✅ Verifica DOPO ripristino backup (non prima)
   - Test: ✅ nsec8-stable, ✅ laboratorio (da GitHub)

**Host validati (production):**

| Host | IP | OS | Status | Packages |
|------|----|----|--------|----------|
| **nsec8-stable** | 10.155.100.100:22 | NethSecurity 8.7.1 | ✅ ROCKSOLID | ar 2.40-1, git 2.43.2-1, libbfd 2.40-1 |
| **laboratorio** | 10.155.100.1:2222 | NethSecurity 8.7.1 | ✅ ROCKSOLID | ar 2.40-1, git 2.43.2-1, libbfd 2.40-1 |

**Componenti attivi:**
- ✅ CheckMK Agent 2.4.0p20 (porta 6556)
- ✅ FRP Client (tunnel verso monitor.nethlab.it:7000)
- ✅ Auto Git Sync (cron ogni minuto, /opt/checkmk-tools)
- ✅ Rocksolid startup check (rc.local, log: /var/log/rocksolid-startup.log)
- ✅ 12 local checks deployed

**Protezioni major upgrade:**
- ✅ File critici in `/etc/sysupgrade.conf`
- ✅ Binari backuppati in `/opt/checkmk-backups/binaries/`
- ✅ Nginx configuration (`/etc/nginx/`) protetta
- ✅ Script auto-ripristino: `/etc/checkmk-post-upgrade.sh`

### 🔧 Dettagli Tecnici

**Dynamic Package Download:**

```bash
download_openwrt_package() {
    local package_name="$1"
    local repo_url="$2"
    local output_path="$3"

    # Download Packages.gz index
    wget -q -O /tmp/Packages.gz "$repo_url/Packages.gz"

    # Parse package filename (fix: grep "${package_name}_" non "/$package_name")
    local package_file=$(gunzip -c /tmp/Packages.gz | grep "^Filename:" | grep "${package_name}_" | head -1 | awk '{print $2}')

    # Download package
    wget -q -O "$output_path" "$repo_url/$package_file"
}

```text

**Dependencies Chain (circular dependency fix):**

```bash
# Order matters: libbfd first (shared library), then ar (uses libbfd)
opkg install --force-depends /tmp/libbfd.ipk
opkg install --force-depends /tmp/ar.ipk
opkg install --force-depends /tmp/objdump.ipk
opkg install --force-depends /tmp/binutils.ipk

```text

**Rocksolid Logic (fixed order):**

```bash
# STEP 1: Restore backups FIRST
for backup in /opt/checkmk-backups/binaries/*.backup; do
    cp -p "$backup" "$dest" 2>/dev/null || true
done

# STEP 2: Check corruption AFTER restore (not before!)
if [ -x /usr/bin/ar ]; then
    if ! /usr/bin/ar --version >/dev/null 2>&1; then
        BINARIES_CORRUPTED=1
    fi
fi

# STEP 3: Install dependencies if still corrupted
if [ $BINARIES_CORRUPTED -eq 1 ]; then
    download_openwrt_package "libbfd" "$REPO_BASE" "/tmp/libbfd.ipk"
    opkg install --force-depends /tmp/libbfd.ipk
    download_openwrt_package "ar" "$REPO_BASE" "/tmp/ar.ipk"
    opkg install --force-depends /tmp/ar.ipk
fi

```text

### 📋 Testing Workflow Validato

**Workflow obbligatorio seguito:**
1. ✅ Modifica script (dynamic download, pattern fix, logic reorder, git auto-install)
2. ✅ Test sintassi: `wsl bash -n script.sh` (exit code 0)
3. ✅ Verifica eseguibilità: `git ls-files -s` (100755)
4. ✅ Commit + push: b29a2cf, ea67364, 68661c1, 67f3cbc
5. ✅ Test su nsec8-stable: `curl -fsSL https://raw.githubusercontent.com/.../script.sh | bash`
6. ✅ Test su laboratorio: `curl -fsSL https://raw.githubusercontent.com/.../script.sh | bash`
7. ✅ Validazione output: ar/git/libbfd versioni corrette installate

**Test reali eseguiti:**
- ✅ Post major upgrade scenario (ar corrotto, git mancante)
- ✅ Fresh install su sistema pulito
- ✅ Re-install su sistema già configurato (idempotenza)
- ✅ Esecuzione da GitHub (non repo locale)

### 🎯 Lessons Learned

**Pattern Matching:**
- ❌ `grep "/$package_name"` → Non trova "package_name_version.ipk"
- ✅ `grep "${package_name}_"` → Corretto per formato Packages.gz

**Circular Dependencies:**
- ❌ `opkg install binutils` → "cannot find dependency ar"
- ✅ Install chain: libbfd → ar → objdump → binutils con `--force-depends`

**Backup Restore Timing:**
- ❌ Check corruption BEFORE backup restore → Binari mancanti post-upgrade mai rilevati
- ✅ Restore backups FIRST, THEN check corruption → Rileva problemi anche se binario presente ma corrotto

**Testing:**
- ❌ Test solo 1 script di 3 modificati → Script non testati falliscono in production
- ✅ Test TUTTI gli script modificati nella sessione → 100% coverage
- ❌ Test da repo locale → Potrebbe essere stale
- ✅ Test da GitHub raw URL → Garantisce production source

**Git Auto-Install:**
- ⚠️ Git può essere rimosso durante major upgrade
- ✅ Auto-sync repository richiede git funzionante
- ✅ Rocksolid deve auto-installare git se mancante
- ✅ Necessari: git + git-http (dipendenza)

### 🚀 Sistema Production-Ready

**Status finale:**
- ✅ Entrambi gli host (nsec8-stable, laboratorio) ROCKSOLID mode attivo
- ✅ Tutti i binari critici protetti e auto-riparabili
- ✅ CheckMK Agent, FRP Client, QEMU-GA operativi
- ✅ Auto Git Sync funzionante (repository aggiornato ogni minuto)
- ✅ Sistema resiliente a major upgrade NethSecurity/OpenWrt
- ✅ Zero hardcoded URLs - tutto dinamico da repository upstream

**Prossimi major upgrade:**
- Sistema auto-ripristina binari corrotti (ar, tar, gzip, libbfd)
- Sistema auto-installa git se rimosso
- Sistema verifica e riavvia servizi critici (CheckMK, FRP)
- Log dettagliato in `/var/log/rocksolid-startup.log`
- **Zero intervento manuale richiesto**

---

**Ultimo aggiornamento**: 2026-02-04

---

## 🎫 Ydea-Toolkit - Integrazione CheckMK su srv-monitoring

### Path script (notification scripts CheckMK, senza estensione)

```bash
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_la
/omd/sites/monitoring/local/share/check_mk/notifications/ydea_ag
```

### Test manuale notifica

```bash
su - monitoring -c "
  cd /omd/sites/monitoring/local/share/check_mk/notifications/ && \
  NOTIFY_WHAT=PROBLEM \
  NOTIFY_HOSTNAME=ns8.ad.studiopaci.info \
  NOTIFY_SERVICEDESC=CPU \
  NOTIFY_SERVICESTATE=CRITICAL \
  NOTIFY_SERVICEOUTPUT='CPU load 95%' \
  NOTIFY_NOTIFICATIONTYPE=PROBLEM \
  python3 ydea_la
"
# Verifica cache
cat /opt/ydea-toolkit/cache/ydea_checkmk_tickets.json
```

### Cache Ydea (percorso corretto post fix installer commit b8f2090)

```text
/opt/ydea-toolkit/cache/ydea_checkmk_tickets.json
/opt/ydea-toolkit/cache/ydea_checkmk_flapping.json
/opt/ydea-toolkit/cache/ydea_cache.lock
```

### Fix manuale rapido su host già installati

```bash
mkdir -p /opt/ydea-toolkit/cache
echo '{}' > /opt/ydea-toolkit/cache/ydea_checkmk_tickets.json
echo '{}' > /opt/ydea-toolkit/cache/ydea_checkmk_flapping.json
touch /opt/ydea-toolkit/cache/ydea_cache.lock
chmod 666 /opt/ydea-toolkit/cache/*.json /opt/ydea-toolkit/cache/*.lock
chmod 777 /opt/ydea-toolkit/cache
chmod 640 /opt/ydea-toolkit/.env.la /opt/ydea-toolkit/.env.ag
chown monitoring:monitoring /opt/ydea-toolkit/.env.la /opt/ydea-toolkit/.env.ag
```

### Note

- API key `Y_KEY_8c814108a0345fdeace7fb9c637fb6c9` → **scaduta** (febbraio 2026) - attendere nuova key
- Log: `tail -f /var/log/ydea_health.log` e `tail -f /var/log/ydea_cache_validator.log`
