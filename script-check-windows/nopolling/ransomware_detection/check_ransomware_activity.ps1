#!/usr/bin/env powershell
<#
.SYNOPSIS
    CheckMK Local Check - Ransomware Activity Detection
    
.DESCRIPTION
    Script di monitoraggio per rilevare attività sospette di ransomware nelle share di rete.
    Monitora:
    - File modificati recentemente con estensioni sospette
    - Attività di crittografia massiva (entropy analysis)
    - Presenza di ransom notes
    - Cambio di estensioni anomale
    - Canary files (file esca)
    - Pattern di accesso sospetti
    
.NOTES
    Author: Marzio
    Date: 2025-10-22
    Version: 1.0
    CheckMK Output Format: <<<local>>>
    
.PARAMETER SharePaths
    Array di percorsi UNC o locali da monitorare
    
.PARAMETER TimeWindowMinutes
    Finestra temporale in minuti per analisi attività (default: 30)
    
.PARAMETER AlertThreshold
    Numero minimo di file modificati per considerare sospetta l'attività (default: 50)
    
.EXAMPLE
    .\check_ransomware_activity.ps1 -SharePaths @("\\server\share1", "\\server\share2")
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [string[]]$SharePaths = @(),
    
    [Parameter(Mandatory=$false)]
    [int]$TimeWindowMinutes = 30,
    
    [Parameter(Mandatory=$false)]
    [int]$AlertThreshold = 50,
    
    [Parameter(Mandatory=$false)]
    [string]$ConfigFile,
    
    [Parameter(Mandatory=$false)]
    [string]$StateFile = "$env:TEMP\ransomware_state.json",
    
    [Parameter(Mandatory=$false)]
    [switch]$VerboseLog
)

# Estensioni comuni di ransomware
$RANSOMWARE_EXTENSIONS = @(
    '.encrypted', '.locked', '.crypto', '.crypt', '.crypted',
    '.locky', '.cerber', '.zepto', '.odin', '.thor',
    '.wannacry', '.wncry', '.wcry', '.wncryt',
    '.ryuk', '.sodinokibi', '.revil', '.maze', '.conti',
    '.lockbit', '.blackcat', '.alphv', '.royal',
    '.crypz', '.enc', '.cipher', '.coded', '.sealed',
    '.kraken', '.darkness', '.dharma', '.phobos',
    '.exx', '.ezz', '.eking', '.cube', '.BTCWare',
    '.AES256', '.RSA2048', '.RSA4096', '.xtbl',
    '.vault', '.micro', '.sage', '.spora', '.mole',
    '.redrum', '.silent', '.blacksuit', '.play'
)

# Nomi comuni di ransom notes
$RANSOM_NOTE_PATTERNS = @(
    '*README*', '*DECRYPT*', '*RESTORE*', '*UNLOCK*',
    '*RECOVER*', '*HOW_TO*', '*HELP*', '*ATTENTION*',
    '*WARNING*', '*RANSOM*', '*INSTRUCTION*',
    '*.hta', '*.html' # spesso usati per ransom notes
)

# Estensioni di file da proteggere (target comuni)
$TARGET_EXTENSIONS = @(
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.pdf', '.txt', '.jpg', '.jpeg', '.png', '.gif',
    '.zip', '.rar', '.7z', '.sql', '.mdb', '.accdb',
    '.pst', '.ost', '.csv', '.rtf', '.odt', '.ods'
)

# ============================================================================
# INIZIALIZZAZIONE
# ============================================================================

# Determina il path del config file se non specificato
if (-not $ConfigFile) {
    # Prova diverse posizioni
    $possiblePaths = @(
        "$PSScriptRoot\ransomware_config.json",
        "C:\ProgramData\checkmk\agent\local\ransomware_config.json",
        "$env:ProgramData\checkmk\agent\local\ransomware_config.json"
    )
    
    foreach ($path in $possiblePaths) {
        if ($path -and (Test-Path $path)) {
            $ConfigFile = $path
            break
        }
    }
    
    # Se ancora non trovato, usa default
    if (-not $ConfigFile) {
        $ConfigFile = "C:\ProgramData\checkmk\agent\local\ransomware_config.json"
    }
}

# ============================================================================
# FUNZIONI HELPER
# ============================================================================

function Write-DebugLog {
    param([string]$Message)
    if ($VerboseLog) {
        Write-Host "[DEBUG] $Message" -ForegroundColor Cyan
    }
}

function Get-Configuration {
    <#
    .SYNOPSIS
        Carica la configurazione dal file JSON o usa i valori di default
    #>
    if (Test-Path $ConfigFile) {
        try {
            $config = Get-Content $ConfigFile -Raw | ConvertFrom-Json
            Write-DebugLog "Configurazione caricata da: $ConfigFile"
            return $config
        } catch {
            Write-DebugLog "Errore nel caricamento config, uso defaults: $_"
        }
    }
    
    # Configurazione di default
    $defaultConfig = @{
        SharePaths = @()
        TimeWindowMinutes = $TimeWindowMinutes
        AlertThreshold = $AlertThreshold
        EnableCanaryFiles = $true
        CanaryFileName = ".ransomware_canary_do_not_delete.txt"
        EnableEntropyCheck = $true
        MaxFilesToScan = 1000
        ExcludePaths = @('$RECYCLE.BIN', 'System Volume Information')
    }
    
    return $defaultConfig
}

function Save-State {
    param(
        [hashtable]$State
    )
    
    try {
        $State | ConvertTo-Json -Depth 10 | Set-Content $StateFile -Force
        Write-DebugLog "Stato salvato in: $StateFile"
    } catch {
        Write-DebugLog "Errore nel salvataggio stato: $_"
    }
}

function Get-State {
    if (Test-Path $StateFile) {
        try {
            $state = Get-Content $StateFile -Raw | ConvertFrom-Json
            # Converti da PSCustomObject a Hashtable
            $hash = @{}
            $state.PSObject.Properties | ForEach-Object {
                $hash[$_.Name] = $_.Value
            }
            return $hash
        } catch {
            Write-DebugLog "Errore nel caricamento stato: $_"
        }
    }
    
    return @{
        LastCheck = (Get-Date).AddHours(-1).ToString('o')
        LastAlertTime = $null
        CanaryFilesCreated = @()
    }
}

function Test-ShareAccessible {
    param([string]$Path)
    
    try {
        $null = Get-Item $Path -ErrorAction Stop
        return $true
    } catch {
        Write-DebugLog "Share non accessibile: $Path - $_"
        return $false
    }
}

function Get-FileEntropy {
    <#
    .SYNOPSIS
        Calcola l'entropia di un file (0-8 bits). File crittografati hanno alta entropia (>7.5)
    #>
    param(
        [string]$FilePath,
        [int]$SampleSize = 1024
    )
    
    try {
        $bytes = [System.IO.File]::ReadAllBytes($FilePath)
        if ($bytes.Length -eq 0) { return 0 }
        
        # Usa solo un campione per performance
        if ($bytes.Length -gt $SampleSize) {
            $bytes = $bytes[0..($SampleSize-1)]
        }
        
        # Calcola frequenza di ogni byte
        $freq = @{}
        foreach ($byte in $bytes) {
            if ($freq.ContainsKey($byte)) {
                $freq[$byte]++
            } else {
                $freq[$byte] = 1
            }
        }
        
        # Calcola entropia di Shannon
        $entropy = 0.0
        $length = $bytes.Length
        foreach ($count in $freq.Values) {
            $p = $count / $length
            $entropy -= $p * [Math]::Log($p, 2)
        }
        
        return [Math]::Round($entropy, 2)
    } catch {
        Write-DebugLog "Errore calcolo entropia per $FilePath : $_"
        return 0
    }
}

function New-CanaryFile {
    param(
        [string]$SharePath,
        [string]$FileName
    )
    
    $canaryPath = Join-Path $SharePath $FileName
    
    try {
        if (-not (Test-Path $canaryPath)) {
            $content = @"
ATTENZIONE: Questo è un file di monitoraggio ransomware.
NON ELIMINARE, MODIFICARE O SPOSTARE questo file.

Questo file viene utilizzato per rilevare attività sospette di ransomware.
La sua modifica o eliminazione genererà un allarme di sicurezza.

Data creazione: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Share: $SharePath
Sistema: $env:COMPUTERNAME
"@
            
            $content | Set-Content $canaryPath -Force
            
            # Imposta come hidden e readonly
            $file = Get-Item $canaryPath
            $file.Attributes = 'Hidden,ReadOnly'
            
            Write-DebugLog "Canary file creato: $canaryPath"
            return $canaryPath
        }
        return $canaryPath
    } catch {
        Write-DebugLog "Errore creazione canary file: $_"
        return $null
    }
}

function Test-CanaryFile {
    param(
        [string]$CanaryPath
    )
    
    if (-not (Test-Path $CanaryPath)) {
        return @{
            Status = 'MISSING'
            Message = "Canary file eliminato: possibile attività ransomware!"
        }
    }
    
    try {
        $file = Get-Item $CanaryPath
        $age = (Get-Date) - $file.LastWriteTime
        
        # Se modificato negli ultimi 30 minuti
        if ($age.TotalMinutes -lt 30) {
            return @{
                Status = 'MODIFIED'
                Message = "Canary file modificato recentemente: possibile attività ransomware!"
                LastModified = $file.LastWriteTime
            }
        }
        
        return @{
            Status = 'OK'
            Message = "Canary file intatto"
        }
    } catch {
        return @{
            Status = 'ERROR'
            Message = "Errore controllo canary file: $_"
        }
    }
}

function Get-SuspiciousFiles {
    param(
        [string]$SharePath,
        [datetime]$Since,
        [int]$MaxFiles = 1000,
        [string[]]$ExcludePaths = @(),
        [int]$TimeoutSeconds = 30
    )
    
    Write-DebugLog "Scansione share: $SharePath (modifiche da: $Since)"
    
    $suspiciousFiles = @()
    $totalScanned = 0
    $job = $null
    
    try {
        # Usa Job con timeout per evitare blocchi su share lente
        $job = Start-Job -ScriptBlock {
            param($path, $since, $max, $excludePaths)
            Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $shouldExclude = $false
                foreach ($exPath in $excludePaths) {
                    if ($_.FullName -like "*$exPath*") {
                        $shouldExclude = $true
                        break
                    }
                }
                -not $shouldExclude -and $_.LastWriteTime -gt $since
            } |
            Select-Object -First $max
        } -ArgumentList $SharePath, $Since, $MaxFiles, $ExcludePaths
        
        # Attendi con timeout
        Wait-Job $job -Timeout $TimeoutSeconds | Out-Null

        if ($job.State -eq 'Running') {
            Write-DebugLog "TIMEOUT: Scansione share $SharePath interrotta dopo $TimeoutSeconds secondi"
            Stop-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -Force -ErrorAction SilentlyContinue
            return @()
        }

        $recentFiles = @()
        if ($job.State -eq 'Completed') {
            $recentFiles = Receive-Job $job -ErrorAction SilentlyContinue
        }
        if ($job) {
            Remove-Job $job -Force -ErrorAction SilentlyContinue
        }

        foreach ($file in $recentFiles) {
            $totalScanned++
            $suspicionLevel = 0
            $reasons = @()
            
            # Check 1: Estensione ransomware
            $ext = $file.Extension.ToLower()
            if ($RANSOMWARE_EXTENSIONS -contains $ext) {
                $suspicionLevel += 10
                $reasons += "Estensione ransomware: $ext"
            }
            
            # Check 2: Doppia estensione sospetta (es: .pdf.encrypted)
            if ($file.Name -match '\.([a-z0-9]+)\.([a-z0-9]+)$') {
                $firstExt = ".$($matches[1])"
                $secondExt = ".$($matches[2])"
                
                if ($TARGET_EXTENSIONS -contains $firstExt -and 
                    $RANSOMWARE_EXTENSIONS -contains $secondExt) {
                    $suspicionLevel += 8
                    $reasons += "Doppia estensione sospetta: $firstExt$secondExt"
                }
            }
            
            # Check 3: File modificato molto recentemente
            $ageMinutes = ((Get-Date) - $file.LastWriteTime).TotalMinutes
            if ($ageMinutes -lt 5) {
                $suspicionLevel += 3
                $reasons += "Modificato $([Math]::Round($ageMinutes, 1)) minuti fa"
            }
            
            # Check 4: Nome file sospetto (troppo lungo o caratteri strani)
            if ($file.BaseName.Length -gt 100 -or $file.Name -match '[^\x20-\x7E]') {
                $suspicionLevel += 2
                $reasons += "Nome file anomalo"
            }
            
            if ($suspicionLevel -gt 0) {
                $suspiciousFiles += @{
                    Path = $file.FullName
                    Name = $file.Name
                    Extension = $ext
                    LastWrite = $file.LastWriteTime
                    Size = $file.Length
                    SuspicionLevel = $suspicionLevel
                    Reasons = $reasons
                }
            }
        }
        
        Write-DebugLog "File scansionati: $totalScanned, Sospetti: $($suspiciousFiles.Count)"
        
    } catch {
        Write-DebugLog "Errore scansione share $SharePath : $_"
        # Cleanup job se esiste ancora
        if ($job -and $job.State -ne 'Completed') {
            Stop-Job $job -ErrorAction SilentlyContinue
            Remove-Job $job -ErrorAction SilentlyContinue
        }
    }
    
    return $suspiciousFiles
}

function Find-RansomNotes {
    param(
        [string]$SharePath,
        [string[]]$ExcludePaths = @()
    )
    
    $ransomNotes = @()
    
    try {
        foreach ($pattern in $RANSOM_NOTE_PATTERNS) {
            $files = Get-ChildItem -Path $SharePath -Filter $pattern -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object {
                    $exclude = $false
                    foreach ($exPath in $ExcludePaths) {
                        if ($_.FullName -like "*$exPath*") {
                            $exclude = $true
                            break
                        }
                    }
                    -not $exclude
                } |
                Select-Object -First 50
            
            foreach ($file in $files) {
                # Verifica se creato recentemente (ultime 24 ore)
                $age = (Get-Date) - $file.CreationTime
                
                # Leggi prime righe per keywords
                $keywords = @('ransom', 'decrypt', 'bitcoin', 'payment', 'crypto', 'locked', 'encrypted')
                $isRansomNote = $false
                
                try {
                    $content = Get-Content $file.FullName -First 20 -ErrorAction SilentlyContinue
                    $contentText = ($content -join ' ').ToLower()
                    
                    $matchCount = 0
                    foreach ($keyword in $keywords) {
                        if ($contentText -match $keyword) {
                            $matchCount++
                        }
                    }
                    
                    if ($matchCount -ge 2) {
                        $isRansomNote = $true
                    }
                } catch {
                    # Se il file non è leggibile, potrebbe essere sospetto
                    if ($age.TotalHours -lt 24) {
                        $isRansomNote = $true
                    }
                }
                
                if ($isRansomNote) {
                    $ransomNotes += @{
                        Path = $file.FullName
                        Name = $file.Name
                        Created = $file.CreationTime
                        Size = $file.Length
                        AgeHours = [Math]::Round($age.TotalHours, 1)
                    }
                }
            }
        }
        
        Write-DebugLog "Ransom notes trovate: $($ransomNotes.Count)"
        
    } catch {
        Write-DebugLog "Errore ricerca ransom notes: $_"
    }
    
    return $ransomNotes
}

function Get-MassModificationActivity {
    param(
        [array]$SuspiciousFiles,
        [int]$Threshold
    )
    
    $activity = @{
        IsMassive = $false
        FileCount = $SuspiciousFiles.Count
        UniqueExtensions = @()
        AffectedDirectories = @()
        TimeSpan = $null
    }
    
    if ($SuspiciousFiles.Count -eq 0) {
        return $activity
    }
    
    # Conta estensioni uniche
    $extensions = $SuspiciousFiles | ForEach-Object { $_['Extension'] } | 
        Select-Object -Unique
    $activity.UniqueExtensions = @($extensions)
    
    # Conta directory coinvolte
    $dirs = $SuspiciousFiles | ForEach-Object { 
        Split-Path $_['Path'] -Parent 
    } | Select-Object -Unique
    $activity.AffectedDirectories = @($dirs)
    
    # Calcola timespan
    if ($SuspiciousFiles.Count -gt 1) {
        $times = $SuspiciousFiles | ForEach-Object { $_['LastWrite'] }
        $oldest = ($times | Measure-Object -Minimum).Minimum
        $newest = ($times | Measure-Object -Maximum).Maximum
        $activity.TimeSpan = ($newest - $oldest).TotalMinutes
    }
    
    # Determina se è attività massiva
    if ($SuspiciousFiles.Count -ge $Threshold) {
        $activity.IsMassive = $true
    }
    
    # Ulteriore check: molti file in poco tempo
    if ($activity.TimeSpan -and $activity.TimeSpan -lt 10 -and $SuspiciousFiles.Count -gt 20) {
        $activity.IsMassive = $true
    }
    
    return $activity
}

function Format-CheckMKOutput {
    param(
        [int]$Status,
        [string]$ServiceName,
        [string]$Metrics = '',
        [string]$Details = ''
    )
    
    # Status: 0=OK, 1=WARN, 2=CRIT, 3=UNKNOWN
    $output = "$Status $ServiceName"
    
    if ($Metrics) {
        $output += " $Metrics"
    }
    
    if ($Details) {
        $output += " $Details"
    }
    
    return $output
}

# ============================================================================
# MAIN
# ============================================================================

try {
    Write-DebugLog "=== Avvio Check Ransomware Activity ==="
    
    # Carica configurazione
    $config = Get-Configuration
    
    # Usa SharePaths dal parametro o dalla config
    if ($SharePaths.Count -eq 0 -and $config.SharePaths) {
        # Assicura che sia sempre un array
        if ($config.SharePaths -is [string]) {
            $SharePaths = @($config.SharePaths)
        } elseif ($config.SharePaths -is [array]) {
            $SharePaths = @($config.SharePaths)
        } else {
            $SharePaths = @($config.SharePaths)
        }
        Write-DebugLog "SharePaths dalla config: $($SharePaths.Count) elementi - $($SharePaths -join ', ')"
    }
    
    # Se ancora nessuna share configurata, esci
    if ($SharePaths.Count -eq 0) {
        Write-Host "<<<local>>>"
        Write-Host (Format-CheckMKOutput -Status 3 -ServiceName "Ransomware_Detection" `
            -Details "UNKNOWN - Nessuna share configurata. Configurare SharePaths in $ConfigFile")
        exit 0
    }
    
    # Carica stato precedente
    $state = Get-State
    $lastCheck = [datetime]::Parse($state.LastCheck)
    $timeWindow = (Get-Date).AddMinutes(-$config.TimeWindowMinutes)
    
    # Usa il più recente tra lastCheck e timeWindow
    if ($lastCheck -gt $timeWindow) {
        $since = $lastCheck
    } else {
        $since = $timeWindow
    }
    
    Write-DebugLog "Controllo modifiche dal: $since"
    
    # Inizializza risultati
    $allSuspiciousFiles = @()
    $allRansomNotes = @()
    $canaryAlerts = @()
    $accessibleShares = 0
    $totalShares = $SharePaths.Count
    
    # Output CheckMK
    Write-Host "<<<local>>>"
    
    # Analizza ogni share
    foreach ($share in $SharePaths) {
        Write-DebugLog "Analisi share: $share"
        
        # Verifica accessibilità
        if (-not (Test-ShareAccessible $share)) {
            Write-DebugLog "Share non accessibile: $share"
            $shareName = Split-Path $share -Leaf
            if ([string]::IsNullOrEmpty($shareName)) {
                $shareName = $share -replace '[\\:/]', '_'
            }
            Write-Host (Format-CheckMKOutput -Status 1 -ServiceName "Share_$shareName" `
                -Details "WARN - Share non accessibile: $share")
            continue
        }
        
        $accessibleShares++
        
        # Gestione canary files
        if ($config.EnableCanaryFiles) {
            $canaryPath = New-CanaryFile -SharePath $share -FileName $config.CanaryFileName
            
            if ($canaryPath) {
                $canaryCheck = Test-CanaryFile -CanaryPath $canaryPath
                
                if ($canaryCheck.Status -eq 'MISSING' -or $canaryCheck.Status -eq 'MODIFIED') {
                    $canaryAlerts += @{
                        Share = $share
                        Status = $canaryCheck.Status
                        Message = $canaryCheck.Message
                    }
                }
            }
        }
        
        # Cerca file sospetti (con timeout di 30 secondi)
        $suspicious = Get-SuspiciousFiles -SharePath $share -Since $since `
            -MaxFiles $config.MaxFilesToScan -ExcludePaths $config.ExcludePaths -TimeoutSeconds 30
        $allSuspiciousFiles += $suspicious
        
        # Cerca ransom notes
        $notes = Find-RansomNotes -SharePath $share -ExcludePaths $config.ExcludePaths
        $allRansomNotes += $notes
    }
    
    # Analizza attività complessiva
    $massActivity = Get-MassModificationActivity -SuspiciousFiles $allSuspiciousFiles `
        -Threshold $config.AlertThreshold
    
    # Determina stato finale
    $finalStatus = 0  # OK
    $alerts = @()
    
    # Controllo canary files
    if ($canaryAlerts.Count -gt 0) {
        $finalStatus = 2  # CRITICAL
        $alerts += "ALERT: Canary file compromessi ($($canaryAlerts.Count))"
    }
    
    # Controllo ransom notes
    if ($allRansomNotes.Count -gt 0) {
        $finalStatus = 2  # CRITICAL
        $alerts += "ALERT: Ransom notes rilevate ($($allRansomNotes.Count))"
    }
    
    # Controllo attività massiva
    if ($massActivity.IsMassive) {
        if ($finalStatus -lt 2) {
            $finalStatus = 2  # CRITICAL
        }
        $alerts += "ALERT: Attività di crittografia massiva rilevata ($($massActivity.FileCount) files)"
    } elseif ($allSuspiciousFiles.Count -gt 0) {
        if ($finalStatus -eq 0) {
            $finalStatus = 1  # WARNING
        }
        $alerts += "WARNING: File sospetti rilevati ($($allSuspiciousFiles.Count))"
    }
    
    # Costruisci metriche
    $metrics = "suspicious_files=$($allSuspiciousFiles.Count)|ransom_notes=$($allRansomNotes.Count)|canary_alerts=$($canaryAlerts.Count)|shares_ok=$accessibleShares"
    
    # Costruisci dettagli
    if ($alerts.Count -gt 0) {
        $details = ($alerts -join ', ')
        
        # Aggiungi top 5 file più sospetti
        if ($allSuspiciousFiles.Count -gt 0) {
            $topFiles = $allSuspiciousFiles | 
                Sort-Object -Property { $_['SuspicionLevel'] } -Descending | 
                Select-Object -First 5
            
            $details += " | Top files: "
            $fileDetails = $topFiles | ForEach-Object {
                "$($_['Name']) (score: $_['SuspicionLevel'])"
            }
            $details += ($fileDetails -join ', ')
        }
    } else {
        $details = "OK - Nessuna attivita' sospetta rilevata su $accessibleShares/$totalShares shares"
    }
    
    # Output finale
    Write-Host (Format-CheckMKOutput -Status $finalStatus -ServiceName "Ransomware_Detection" `
        -Metrics $metrics -Details $details)
    
    # Output dettagliato per ogni share
    foreach ($share in $SharePaths) {
        if (Test-ShareAccessible $share) {
            $shareSuspicious = $allSuspiciousFiles | Where-Object { $_['Path'] -like "$share*" }
            $shareNotes = $allRansomNotes | Where-Object { $_['Path'] -like "$share*" }
            
            $shareStatus = 0
            $shareDetails = "OK - Nessun file sospetto rilevato"
            
            if ($shareNotes.Count -gt 0) {
                $shareStatus = 2
                $shareDetails = "CRIT - Ransom notes: $($shareNotes.Count)"
            } elseif ($shareSuspicious.Count -gt 0) {
                # Ha file sospetti - verifica la gravità
                $threshold = if ($config.AlertThreshold) { $config.AlertThreshold } else { 50 }
                if ($shareSuspicious.Count -ge ($threshold / 2)) {
                    $shareStatus = 2
                    $shareDetails = "CRIT - Suspicious files: $($shareSuspicious.Count)"
                } else {
                    $shareStatus = 1
                    $shareDetails = "WARN - Suspicious files: $($shareSuspicious.Count)"
                }
            }
            
            # Estrae solo il nome della share (ultima parte del path)
            $shareName = Split-Path $share -Leaf
            if ([string]::IsNullOrEmpty($shareName)) {
                $shareName = $share -replace '[\\:/]', '_'
            }
            $shareMetrics = "suspicious=$($shareSuspicious.Count)|notes=$($shareNotes.Count)"
            
            Write-Host (Format-CheckMKOutput -Status $shareStatus `
                -ServiceName "Share_$shareName" `
                -Metrics $shareMetrics -Details $shareDetails)
        }
    }
    
    # Salva stato
    $state.LastCheck = (Get-Date).ToString('o')
    if ($finalStatus -eq 2) {
        $state.LastAlertTime = (Get-Date).ToString('o')
    }
    Save-State -State $state
    
    Write-DebugLog "=== Check completato con stato: $finalStatus ==="
    
} catch {
    Write-Host "<<<local>>>"
    Write-Host (Format-CheckMKOutput -Status 3 -ServiceName "Ransomware_Detection" `
        -Details "UNKNOWN - Errore esecuzione script: $_")
    Write-DebugLog "ERRORE CRITICO: $_"
    exit 1
}
