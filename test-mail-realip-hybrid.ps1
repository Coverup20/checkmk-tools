# ===================================================================
# 🚀 CheckMK mail_realip_hybrid - Remote Testing Suite
# ===================================================================
# Script PowerShell per testare mail_realip_hybrid su VPS CheckMK
# via SSH con supporto chiavi e passphrase
# ===================================================================

Write-Host "🚀 CHECKMK MAIL_REALIP_HYBRID - REMOTE TESTING" -ForegroundColor Cyan
Write-Host "Testing sicuro su VPS con backup automatico e rollback" -ForegroundColor Gray

# ==================== CONFIGURAZIONE VPS ====================
Write-Host "`n📋 CONFIGURAZIONE VPS:" -ForegroundColor Yellow

$config = @{}

# Carica configurazione salvata se disponibile
$configFile = "vps_config.json"
if (Test-Path $configFile) {
    Write-Host "📂 Trovata configurazione salvata. Carico..." -ForegroundColor Green
    try {
        $savedConfig = Get-Content $configFile | ConvertFrom-Json
        $loadSaved = Read-Host "Usare configurazione salvata per $($savedConfig.VpsIP)? [Y/n]"
        if ($loadSaved -ne 'n') {
            $config = @{}
            $savedConfig.PSObject.Properties | ForEach-Object { $config[$_.Name] = $_.Value }
            Write-Host "✅ Configurazione caricata!" -ForegroundColor Green
        }
    } catch {
        Write-Host "⚠️ Errore caricamento configurazione salvata" -ForegroundColor Yellow
    }
}

# Richiedi configurazione se non caricata
if (-not $config.VpsIP) {
    do {
        $config.VpsIP = Read-Host "`nIP/Hostname VPS CheckMK"
    } while (-not $config.VpsIP)

    do {
        $config.SshUser = Read-Host "Username SSH (es: root, ubuntu, cmkadmin)"
    } while (-not $config.SshUser)

    do {
        $config.SiteCheckMK = Read-Host "Nome site CheckMK (es: monitoring, prod)"
    } while (-not $config.SiteCheckMK)

    # Path chiave SSH
    do {
        $config.SshKeyPath = Read-Host "Path chiave SSH privata (es: C:\Users\..\.ssh\id_rsa)"
        if (-not (Test-Path $config.SshKeyPath)) {
            Write-Host "⚠️ File chiave non trovato!" -ForegroundColor Yellow
            $continue = Read-Host "Continuare comunque? [y/N]"
            if ($continue -ne 'y') { exit 1 }
        }
    } while (-not $config.SshKeyPath)

    # Salva configurazione
    try {
        $config | ConvertTo-Json | Set-Content $configFile
        Write-Host "💾 Configurazione salvata in $configFile" -ForegroundColor Green
    } catch {
        Write-Host "⚠️ Impossibile salvare configurazione" -ForegroundColor Yellow
    }
}

# ==================== VERIFICA PREREQUISITI ====================
Write-Host "`n🔍 VERIFICA PREREQUISITI:" -ForegroundColor Yellow

# 1. Verifica script locali
$requiredFiles = @(
    "script-notify-checkmk\mail_realip_hybrid",
    "script-notify-checkmk\backup_and_deploy.sh", 
    "script-notify-checkmk\pre_test_checker.sh",
    "script-notify-checkmk\TESTING_GUIDE.md"
)

foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        Write-Host "❌ File richiesto non trovato: $file" -ForegroundColor Red
        exit 1
    } else {
        Write-Host "✅ $file" -ForegroundColor Green
    }
}

# 2. Test connessione SSH
Write-Host "`n🔐 Test connessione SSH..." -ForegroundColor Cyan
Write-Host "⚠️ Ti verrà richiesta la passphrase della chiave SSH" -ForegroundColor Yellow

try {
    $sshTestCmd = "ssh -i `"$($config.SshKeyPath)`" -o ConnectTimeout=10 -o StrictHostKeyChecking=no $($config.SshUser)@$($config.VpsIP) `"echo 'SSH_OK'`""
    $sshResult = Invoke-Expression $sshTestCmd
    if ($sshResult -match "SSH_OK") {
        Write-Host "✅ Connessione SSH funzionante!" -ForegroundColor Green
    } else {
        Write-Host "❌ Test SSH fallito!" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "❌ Errore connessione SSH: $_" -ForegroundColor Red
    exit 1
}

# ==================== FUNZIONI UTILITY ====================
function Invoke-SshCommand {
    param(
        [string]$Command,
        [string]$Description = "Comando SSH"
    )
    
    Write-Host "`n🔧 $Description..." -ForegroundColor Cyan
    $sshCmd = "ssh -i `"$($config.SshKeyPath)`" $($config.SshUser)@$($config.VpsIP) `"$Command`""
    
    try {
        $result = Invoke-Expression $sshCmd
        Write-Host "✅ $Description completato" -ForegroundColor Green
        return $result
    } catch {
        Write-Host "❌ Errore $Description`: $_" -ForegroundColor Red
        return $null
    }
}

function Copy-FilesToVps {
    param([string[]]$Files, [string]$RemotePath = "/tmp")
    
    Write-Host "`n📦 Upload file su VPS..." -ForegroundColor Cyan
    
    foreach ($file in $Files) {
        $scpCmd = "scp -i `"$($config.SshKeyPath)`" `"$file`" $($config.SshUser)@$($config.VpsIP):$RemotePath/"
        try {
            Invoke-Expression $scpCmd
            Write-Host "✅ $(Split-Path $file -Leaf) uploaded" -ForegroundColor Green
        } catch {
            Write-Host "❌ Errore upload $file`: $_" -ForegroundColor Red
            return $false
        }
    }
    return $true
}

# ==================== MENU TESTING ====================
function Show-TestingMenu {
    Write-Host "`n🎯 MENU TESTING MAIL_REALIP_HYBRID:" -ForegroundColor Yellow
    Write-Host "1. 🧪 Pre-Test Check (verifica ambiente)" -ForegroundColor White
    Write-Host "2. 📦 Upload + Dry Run (test sicuro)" -ForegroundColor White  
    Write-Host "3. 🚀 Deploy Real (con backup automatico)" -ForegroundColor White
    Write-Host "4. 📧 Test Notifica Completa" -ForegroundColor White
    Write-Host "5. 📊 Monitor Logs Live" -ForegroundColor White
    Write-Host "6. 🔄 Rollback (emergency restore)" -ForegroundColor White
    Write-Host "7. 📋 Show Remote Environment Info" -ForegroundColor White
    Write-Host "0. ❌ Exit" -ForegroundColor Red
    
    do {
        $choice = Read-Host "`nScegli opzione [0-7]"
    } while ($choice -notmatch '^[0-7]$')
    
    return $choice
}

# ==================== TEST FUNCTIONS ====================
function Test-PreCheck {
    Write-Host "`n🧪 ESECUZIONE PRE-TEST CHECK..." -ForegroundColor Cyan
    
    # Upload pre_test_checker.sh
    if (-not (Copy-FilesToVps @("script-notify-checkmk\pre_test_checker.sh"))) { return }
    
    # Esegui pre-check
    $checkResult = Invoke-SshCommand "cd /tmp && chmod +x pre_test_checker.sh && sudo ./pre_test_checker.sh" "Pre-Test Environment Check"
    
    if ($checkResult) {
        Write-Host "`n📋 RISULTATO PRE-CHECK:" -ForegroundColor Yellow
        Write-Host $checkResult -ForegroundColor White
    }
}

function Test-DryRun {
    Write-Host "`n🧪 ESECUZIONE DRY RUN..." -ForegroundColor Cyan
    
    # Upload tutti i file necessari
    $filesToUpload = @(
        "script-notify-checkmk\mail_realip_hybrid",
        "script-notify-checkmk\backup_and_deploy.sh",
        "script-notify-checkmk\pre_test_checker.sh"
    )
    
    if (-not (Copy-FilesToVps $filesToUpload)) { return }
    
    # Esegui dry run
    $dryRunResult = Invoke-SshCommand "cd /tmp && chmod +x *.sh && sudo ./backup_and_deploy.sh --dry-run" "Dry Run Deployment"
    
    if ($dryRunResult) {
        Write-Host "`n📋 RISULTATO DRY RUN:" -ForegroundColor Yellow
        Write-Host $dryRunResult -ForegroundColor White
    }
}

function Deploy-Real {
    Write-Host "`n🚀 DEPLOYMENT REALE CON BACKUP..." -ForegroundColor Red
    $confirm = Read-Host "⚠️ Questo modificherà il sistema. Continuare? [y/N]"
    if ($confirm -ne 'y') { 
        Write-Host "❌ Deploy annullato" -ForegroundColor Yellow
        return 
    }
    
    # Upload tutti i file necessari
    $filesToUpload = @(
        "script-notify-checkmk\mail_realip_hybrid",
        "script-notify-checkmk\backup_and_deploy.sh",
        "script-notify-checkmk\pre_test_checker.sh"
    )
    
    if (-not (Copy-FilesToVps $filesToUpload)) { return }
    
    # Esegui deploy reale
    $deployResult = Invoke-SshCommand "cd /tmp && chmod +x *.sh && sudo ./backup_and_deploy.sh" "Real Deployment"
    
    if ($deployResult) {
        Write-Host "`n📋 RISULTATO DEPLOYMENT:" -ForegroundColor Yellow
        Write-Host $deployResult -ForegroundColor White
        Write-Host "`n✅ DEPLOYMENT COMPLETATO!" -ForegroundColor Green
        Write-Host "📂 Backup automatico creato per rollback sicuro" -ForegroundColor Cyan
    }
}

function Test-Notification {
    Write-Host "`n📧 TEST NOTIFICA COMPLETA..." -ForegroundColor Cyan
    
    # Comandi test suggeriti
    $testCommands = @(
        "# 1. Verifica script deployato",
        "ls -la /omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_hybrid",
        "",
        "# 2. Test detection FRP manuale", 
        "su - $($config.SiteCheckMK) -c `"python3 -c 'import os; os.environ[\\`"NOTIFY_HOSTADDRESS\\`"] = \\`"127.0.0.1:5000\\`"; os.environ[\\`"NOTIFY_HOSTLABEL_real_ip\\`"] = \\`"192.168.1.100\\`"; exec(open(\\`"/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_hybrid\\`").read())'`"",
        "",
        "# 3. Test notifica real",
        "su - $($config.SiteCheckMK) -c `"echo 'Test notification' | /omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_hybrid`""
    )
    
    Write-Host "`n📋 COMANDI TEST SUGGERITI:" -ForegroundColor Yellow
    foreach ($cmd in $testCommands) {
        if ($cmd.StartsWith("#")) {
            Write-Host $cmd -ForegroundColor Cyan
        } elseif ($cmd -eq "") {
            Write-Host ""
        } else {
            Write-Host $cmd -ForegroundColor White
        }
    }
    
    $runNow = Read-Host "`nEseguire test automatico ora? [y/N]"
    if ($runNow -eq 'y') {
        # Esegui test detection
        $testResult = Invoke-SshCommand "su - $($config.SiteCheckMK) -c `"python3 -c 'import os; os.environ[\\`"NOTIFY_HOSTADDRESS\\`"] = \\`"127.0.0.1:5000\\`"; os.environ[\\`"NOTIFY_HOSTLABEL_real_ip\\`"] = \\`"192.168.1.100\\`"; exec(open(\\`"/omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/mail_realip_hybrid\\`").read()); print(\\`"TEST OK\\`")'`"" "Test Detection FRP"
        
        if ($testResult -match "TEST OK") {
            Write-Host "✅ Test detection FRP superato!" -ForegroundColor Green
        } else {
            Write-Host "⚠️ Test detection da verificare manualmente" -ForegroundColor Yellow
        }
    }
}

function Monitor-Logs {
    Write-Host "`n📊 MONITOR LOGS LIVE..." -ForegroundColor Cyan
    Write-Host "🔍 Monitoring: /omd/sites/$($config.SiteCheckMK)/var/log/notify.log" -ForegroundColor Gray
    Write-Host "⚠️ Premi Ctrl+C per interrompere" -ForegroundColor Yellow
    
    $logCmd = "tail -f /omd/sites/$($config.SiteCheckMK)/var/log/notify.log"
    Invoke-SshCommand $logCmd "Live Log Monitoring"
}

function Rollback-Deploy {
    Write-Host "`n🔄 ROLLBACK EMERGENCY..." -ForegroundColor Red
    $confirm = Read-Host "⚠️ Questo ripristinerà la configurazione precedente. Continuare? [y/N]"
    if ($confirm -ne 'y') { 
        Write-Host "❌ Rollback annullato" -ForegroundColor Yellow
        return 
    }
    
    # Trova e esegui script rollback
    $rollbackResult = Invoke-SshCommand "find /omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/backup_* -name 'rollback.sh' -exec {} \;" "Rollback Execution"
    
    if ($rollbackResult) {
        Write-Host "`n📋 RISULTATO ROLLBACK:" -ForegroundColor Yellow
        Write-Host $rollbackResult -ForegroundColor White
        Write-Host "`n✅ ROLLBACK COMPLETATO!" -ForegroundColor Green
    }
}

function Show-RemoteInfo {
    Write-Host "`n📋 INFORMAZIONI AMBIENTE REMOTO..." -ForegroundColor Cyan
    
    $infoCommands = @(
        ("Sistema", "uname -a"),
        ("Site CheckMK", "ls -la /omd/sites/"),
        ("Configurazione Apache", "grep -E 'CONFIG_APACHE_TCP_' /omd/sites/$($config.SiteCheckMK)/etc/omd/site.conf"),
        ("Script Notifiche", "ls -la /omd/sites/$($config.SiteCheckMK)/local/share/check_mk/notifications/"),
        ("Processi FRP", "pgrep -f frp || echo 'Nessun processo FRP trovato'"),
        ("Spazio Disco", "df -h /omd/sites/$($config.SiteCheckMK)")
    )
    
    foreach ($info in $infoCommands) {
        Write-Host "`n🔍 $($info[0]):" -ForegroundColor Yellow
        $result = Invoke-SshCommand $info[1] $info[0]
        if ($result) {
            Write-Host $result -ForegroundColor White
        }
    }
}

# ==================== MAIN LOOP ====================
Write-Host "`n🎯 AMBIENTE PRONTO PER TESTING!" -ForegroundColor Green
Write-Host "VPS: $($config.VpsIP)" -ForegroundColor Cyan
Write-Host "Site: $($config.SiteCheckMK)" -ForegroundColor Cyan

do {
    $choice = Show-TestingMenu
    
    switch ($choice) {
        "1" { Test-PreCheck }
        "2" { Test-DryRun }
        "3" { Deploy-Real }
        "4" { Test-Notification }
        "5" { Monitor-Logs }
        "6" { Rollback-Deploy }
        "7" { Show-RemoteInfo }
        "0" { 
            Write-Host "`n👋 Testing terminato!" -ForegroundColor Green
            exit 0
        }
    }
    
    if ($choice -ne "0") {
        Read-Host "`nPremi Enter per continuare..."
    }
    
} while ($choice -ne "0")