# Script di Backup Completo Repository CheckMK-Tools
# Backup locale + opzionale su \\192.168.10.132\usbshare

param(
    [switch]$Unattended  # Modalità automatica senza prompt
)

$ErrorActionPreference = "Stop"

$REPO_PATH = "C:\Users\Marzio\Desktop\CheckMK\checkmk-tools"
$LOCAL_BACKUP_BASE = "C:\CheckMK-Backups"
$NETWORK_BACKUP_BASE = "\\192.168.10.132\usbshare\CheckMK-Backups"
$TIMESTAMP = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$LOCAL_BACKUP_PATH = Join-Path $LOCAL_BACKUP_BASE $TIMESTAMP
$NETWORK_BACKUP_PATH = Join-Path $NETWORK_BACKUP_BASE $TIMESTAMP

Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      BACKUP COMPLETO REPOSITORY CHECKMK-TOOLS      ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# ═══════════════════════════════════════════════════════════════════
# CONTROLLO INTEGRITÀ SCRIPT
# ═══════════════════════════════════════════════════════════════════

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║           VERIFICA INTEGRITÀ SCRIPT                ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow

function Test-ScriptIntegrity {
    param(
        [string]$ScriptPath
    )
    
    $relativePath = $ScriptPath.Replace($REPO_PATH, "").TrimStart('\')
    
    # Verifica esistenza file
    if (-not (Test-Path $ScriptPath)) {
        Write-Host " File non trovato: $relativePath" -ForegroundColor Red
        return $false
    }
    
    # Skip verifica vuoto per file che possono essere legittimamente vuoti
    $allowedEmptyFiles = @(
        "corrupted-files-list.txt",
        ".gitkeep",
        ".env"
    )
    
    $fileName = Split-Path $ScriptPath -Leaf
    $canBeEmpty = $allowedEmptyFiles -contains $fileName
    
    # Verifica che il file non sia vuoto (a meno che non sia nella whitelist)
    $fileInfo = Get-Item $ScriptPath
    if ($fileInfo.Length -eq 0 -and -not $canBeEmpty) {
        Write-Host " File vuoto: $relativePath" -ForegroundColor Red
        return $false
    }
    
    # Per file PowerShell, verifica la sintassi
    if ($ScriptPath -like "*.ps1") {
        try {
            $errors = $null
            $tokens = $null
            $null = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
            
            if ($errors.Count -gt 0) {
                Write-Host " Errori di sintassi in: $relativePath" -ForegroundColor Red
                foreach ($parseError in $errors) {
                    Write-Host "  └─ Linea $($parseError.Extent.StartLineNumber): $($parseError.Message)" -ForegroundColor Red
                }
                return $false
            }
        } catch {
            Write-Host " Impossibile analizzare: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    # Per file batch/cmd, verifica base
    elseif ($ScriptPath -like "*.bat" -or $ScriptPath -like "*.cmd") {
        try {
            $content = Get-Content $ScriptPath -Raw -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($content)) {
                Write-Host " File corrotto o vuoto: $relativePath" -ForegroundColor Red
                return $false
            }
        } catch {
            Write-Host " Impossibile leggere: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    # Per file di configurazione (.service, .timer, .socket, .conf, .env, .template)
    elseif ($ScriptPath -match '\.(service|timer|socket|conf|env|template)$') {
        try {
            $content = Get-Content $ScriptPath -Raw -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($content)) {
                Write-Host " File corrotto o vuoto: $relativePath" -ForegroundColor Red
                return $false
            }
        } catch {
            Write-Host " Impossibile leggere: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    # Per file bash/shell/python/altri, verifica contenuto e shebang
    else {
        try {
            $content = Get-Content $ScriptPath -Raw -ErrorAction Stop
            # Skip verifica contenuto vuoto per file nella whitelist
            if ([string]::IsNullOrWhiteSpace($content) -and -not $canBeEmpty) {
                Write-Host " File corrotto o non leggibile: $relativePath" -ForegroundColor Red
                return $false
            }
            # Per script senza estensione, avvisa se manca lo shebang ma non bloccare
            if ($ScriptPath -notlike "*.*") {
                $firstLine = ($content -split "`n")[0].Trim()
                if ($firstLine -notmatch '^#!') {
                    Write-Host " Shebang mancante (potrebbe non essere uno script): $relativePath" -ForegroundColor Yellow
                    # Non bloccare, continua la verifica
                }
            }
        } catch {
            Write-Host " Impossibile leggere: $relativePath" -ForegroundColor Red
            Write-Host "  └─ $($_.Exception.Message)" -ForegroundColor Red
            return $false
        }
    }
    
    Write-Host " $relativePath" -ForegroundColor Green
    return $true
}

Write-Host "Controllo script critici in corso...`n" -ForegroundColor Cyan

# Verifica che il percorso repository esista
if (-not (Test-Path $REPO_PATH)) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║               ERRORE CONFIGURAZIONE              ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Red
    
    Write-Host " BACKUP INTERROTTO: Percorso repository non trovato!" -ForegroundColor Red
    Write-Host "   Percorso configurato: $REPO_PATH" -ForegroundColor Yellow
    Write-Host "   Verifica la variabile `$REPO_PATH nello script.`n" -ForegroundColor Yellow
    
    exit 1
}

Write-Host " Repository: $REPO_PATH`n" -ForegroundColor Gray

$allValid = $true
$checkedScripts = 0
$corruptedScripts = 0

# Trova TUTTI i file nel repository per cartella
Write-Host "Ricerca file nel repository per cartella..." -ForegroundColor Cyan

# Ottieni tutte le cartelle principali
$mainFolders = Get-ChildItem -Path $REPO_PATH -Directory -ErrorAction SilentlyContinue | 
    Where-Object { $_.Name -notmatch '^\.git$' } | 
    Sort-Object Name

# File nella root
$rootFiles = Get-ChildItem -Path $REPO_PATH -File -ErrorAction SilentlyContinue | 
    Where-Object { 
        $_.Extension -notmatch '\.(log|tmp|cache|lock|swp|bak|zip|sha256|md5)$' -and
        $_.Name -notmatch '^\.gitignore$|^\.gitattributes$'
    }

$allScripts = @()
$folderStats = @()

# Aggiungi file root
if ($rootFiles.Count -gt 0) {
    $allScripts += $rootFiles
    $folderStats += [PSCustomObject]@{
        Folder = "(root)"
        Count = $rootFiles.Count
    }
}

# Processa ogni cartella principale
foreach ($folder in $mainFolders) {
    $folderFiles = Get-ChildItem -Path $folder.FullName -Recurse -File -ErrorAction SilentlyContinue | 
        Where-Object { 
            $_.FullName -notmatch '\\\.git\\' -and
            $_.Extension -notmatch '\.(log|tmp|cache|lock|swp|bak|zip|sha256|md5)$' -and
            $_.Name -notmatch '^\.gitignore$|^\.gitattributes$'
        }
    
    if ($folderFiles.Count -gt 0) {
        $allScripts += $folderFiles
        $folderStats += [PSCustomObject]@{
            Folder = $folder.Name
            Count = $folderFiles.Count
        }
    }
}

$totalScripts = $allScripts.Count

if ($totalScripts -eq 0) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║               NESSUN FILE TROVATO                ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Red
    
    Write-Host " BACKUP INTERROTTO: Nessun file trovato!" -ForegroundColor Red
    Write-Host "   Verifica che il percorso repository sia corretto.`n" -ForegroundColor Yellow
    
    exit 1
}

Write-Host "Trovati $totalScripts file da verificare`n" -ForegroundColor White

# Mostra statistiche per cartella
Write-Host "Distribuzione file per cartella:" -ForegroundColor Cyan
foreach ($stat in $folderStats) {
    Write-Host "   $($stat.Folder): $($stat.Count) file" -ForegroundColor Gray
}
Write-Host ""

# Verifica ogni file
foreach ($script in $allScripts) {
    $checkedScripts++
    
    # Mostra progresso ogni 25 file
    if ($checkedScripts % 25 -eq 0) {
        Write-Host "  Verificati $checkedScripts / $totalScripts file..." -ForegroundColor Gray
    }
    
    if (-not (Test-ScriptIntegrity -ScriptPath $script.FullName)) {
        $allValid = $false
        $corruptedScripts++
    }
}

Write-Host "`n" -NoNewline

# Mostra riepilogo
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Gray
Write-Host "Riepilogo controllo:" -ForegroundColor White
Write-Host "  • File verificati: $checkedScripts" -ForegroundColor Green
Write-Host "  • File validi: $($checkedScripts - $corruptedScripts)" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Yellow" })
Write-Host "  • File corrotti: $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "═══════════════════════════════════════════════════════`n" -ForegroundColor Gray

if (-not $allValid) {
    Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║               FILE CORROTTI RILEVATI             ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Red
    
    Write-Host " BACKUP INTERROTTO: $corruptedScripts file corrotti o con errori." -ForegroundColor Red
    Write-Host "   Correggi gli errori sopra indicati prima di procedere con il backup.`n" -ForegroundColor Yellow
    
    exit 1
}

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║          INTEGRITÀ VERIFICATA ($checkedScripts file)            ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

# Pausa per permettere di vedere i risultati
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Controllo integrità completato:" -ForegroundColor White
Write-Host "  • Totale file verificati: $checkedScripts" -ForegroundColor Green
Write-Host "  • File validi: $($checkedScripts - $corruptedScripts)" -ForegroundColor Green
Write-Host "  • File corrotti: $corruptedScripts" -ForegroundColor $(if ($corruptedScripts -eq 0) { "Green" } else { "Red" })
Write-Host "═══════════════════════════════════════════════════════`n" -ForegroundColor Cyan

if (-not $Unattended) {
    Write-Host "Premi un tasto per continuare con il backup..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════
# INIZIO BACKUP
# ═══════════════════════════════════════════════════════════════════

Write-Host " Repository locale: $REPO_PATH" -ForegroundColor Gray
Write-Host " Backup locale: $LOCAL_BACKUP_PATH" -ForegroundColor Gray
Write-Host " Backup rete (opzionale): $NETWORK_BACKUP_PATH`n" -ForegroundColor Gray

# Crea cartella backup locale
Write-Host " Creazione cartella backup locale..." -ForegroundColor Yellow
if (-not (Test-Path $LOCAL_BACKUP_BASE)) {
    New-Item -ItemType Directory -Path $LOCAL_BACKUP_BASE -Force | Out-Null
}
New-Item -ItemType Directory -Path $LOCAL_BACKUP_PATH -Force | Out-Null
Write-Host " Cartella creata: $LOCAL_BACKUP_PATH`n" -ForegroundColor Green

# Funzione per copiare file
function Copy-BackupFiles {
    param(
        [string]$DestinationPath
    )
    
    Write-Host " Copia file verso $DestinationPath..." -ForegroundColor Yellow
    
    $excludeDirs = @('.git', 'node_modules', '.vagrant', 'obj', 'bin')
    $excludeFiles = @('*.log', '*.tmp', '*.cache', 'Thumbs.db', '.DS_Store')

    $itemsToCopy = Get-ChildItem -Path $REPO_PATH -Recurse | Where-Object {
        $item = $_
        $exclude = $false
        
        # Escludi directory
        foreach ($dir in $excludeDirs) {
            if ($item.FullName -match [regex]::Escape("\$dir\")) {
                $exclude = $true
                break
            }
        }
        
        # Escludi file temporanei
        if (-not $exclude -and $item -is [System.IO.FileInfo]) {
            foreach ($pattern in $excludeFiles) {
                if ($item.Name -like $pattern) {
                    $exclude = $true
                    break
                }
            }
        }
        
        return -not $exclude
    }

    $totalItems = $itemsToCopy.Count
    $copied = 0

    foreach ($item in $itemsToCopy) {
        $relativePath = $item.FullName.Substring($REPO_PATH.Length + 1)
        $destPath = Join-Path $DestinationPath $relativePath
        
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $destPath -Force -ErrorAction SilentlyContinue | Out-Null
        } else {
            $destDir = Split-Path $destPath -Parent
            if (-not (Test-Path $destDir)) {
                New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            }
            Copy-Item -Path $item.FullName -Destination $destPath -Force
            $copied++
            
            if ($copied % 50 -eq 0) {
                Write-Host "  Copiati $copied / $totalItems file..." -ForegroundColor Cyan
            }
        }
    }

    Write-Host " Completato: $copied file copiati`n" -ForegroundColor Green
    return $copied
}

# Backup locale
$localCopied = Copy-BackupFiles -DestinationPath $LOCAL_BACKUP_PATH

# Backup su rete (opzionale con timeout)
Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║           BACKUP SU RETE (OPZIONALE)               ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow

if ($Unattended) {
    # In modalità automatica, salta il backup di rete per default
    $response = 'n'
    Write-Host "⊗ Backup su rete saltato (modalità automatica)" -ForegroundColor Yellow
} else {
    Write-Host "Vuoi eseguire il backup anche su $NETWORK_BACKUP_BASE?" -ForegroundColor Cyan
    $response = Read-Host "Conferma (S/N)"
}

$networkCopied = 0
if ($response -eq 's' -or $response -eq 'S') {
    Write-Host " Backup su rete confermato`n" -ForegroundColor Green
    
    # Verifica connessione rete
    Write-Host " Verifica connessione rete..." -ForegroundColor Yellow
    if (-not (Test-Path $NETWORK_BACKUP_BASE)) {
        Write-Host " Impossibile accedere a $NETWORK_BACKUP_BASE" -ForegroundColor Red
        Write-Host "  Backup locale completato, rete saltata`n" -ForegroundColor Yellow
    } else {
        Write-Host " Connessione OK`n" -ForegroundColor Green
        
        # Crea cartella backup rete
        New-Item -ItemType Directory -Path $NETWORK_BACKUP_PATH -Force | Out-Null
        
        # Esegui backup rete
        $networkCopied = Copy-BackupFiles -DestinationPath $NETWORK_BACKUP_PATH
    }
} else {
    Write-Host "⊗ Backup su rete saltato`n" -ForegroundColor Gray
}

# Statistiche
Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║               STATISTICHE BACKUP                    ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green

$localSize = (Get-ChildItem -Path $LOCAL_BACKUP_PATH -Recurse -File | Measure-Object -Property Length -Sum).Sum
$localSizeMB = [math]::Round($localSize / 1MB, 2)

Write-Host " BACKUP LOCALE:" -ForegroundColor Cyan
Write-Host "   File copiati:     $localCopied" -ForegroundColor White
Write-Host "   Dimensione:       $localSizeMB MB" -ForegroundColor White
Write-Host "   Percorso:         $LOCAL_BACKUP_PATH`n" -ForegroundColor White

if ($networkCopied -gt 0) {
    $networkSize = (Get-ChildItem -Path $NETWORK_BACKUP_PATH -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $networkSizeMB = [math]::Round($networkSize / 1MB, 2)
    
    Write-Host " BACKUP RETE:" -ForegroundColor Cyan
    Write-Host "   File copiati:     $networkCopied" -ForegroundColor White
    Write-Host "   Dimensione:       $networkSizeMB MB" -ForegroundColor White
    Write-Host "   Percorso:         $NETWORK_BACKUP_PATH`n" -ForegroundColor White
}

Write-Host " Timestamp:        $TIMESTAMP`n" -ForegroundColor Cyan

# Conta backup precedenti locali
$previousBackups = Get-ChildItem -Path $LOCAL_BACKUP_BASE -Directory | 
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}$' } |
    Sort-Object Name -Descending

Write-Host " Backup locali disponibili: $($previousBackups.Count)" -ForegroundColor Gray

# Retention automatica - mantieni solo gli ultimi 10 backup
$RETENTION_COUNT = 10

if ($previousBackups.Count -gt $RETENTION_COUNT) {
    $backupsToDelete = $previousBackups | Select-Object -Skip $RETENTION_COUNT
    $deleteCount = $backupsToDelete.Count
    
    Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
    Write-Host "║            PULIZIA BACKUP VECCHI (Retention)        ║" -ForegroundColor White
    Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Yellow
    
    Write-Host "  Trovati $($previousBackups.Count) backup, retention impostata a $RETENTION_COUNT" -ForegroundColor Yellow
    Write-Host "   Verranno eliminati $deleteCount backup più vecchi...`n" -ForegroundColor Gray
    
    foreach ($backup in $backupsToDelete) {
        try {
            Write-Host "    Eliminazione: $($backup.Name)" -ForegroundColor Gray
            Remove-Item -Path $backup.FullName -Recurse -Force -ErrorAction Stop
            Write-Host "      Eliminato" -ForegroundColor Green
        } catch {
            Write-Host "      Errore: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    
    Write-Host "`n Pulizia completata: mantenuti gli ultimi $RETENTION_COUNT backup`n" -ForegroundColor Green
}

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║           BACKUP COMPLETATO CON SUCCESSO           ║" -ForegroundColor White
Write-Host "╚═══════════════════════════════════════════════════════╝`n" -ForegroundColor Green
