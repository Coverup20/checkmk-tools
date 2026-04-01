# Wrapper for performing backups in unattended mode with logging
$ErrorActionPreference = "Continue"

$SCRIPT_PATH = Join-Path $PSScriptRoot "backup-simple.ps1"
$LOG_PATH = "C:\CheckMK-Backups\logs"
$LOG_FILE = Join-Path $LOG_PATH "backup_$(Get-Date -Format 'yyyy-MM-dd').log"

# Create log folder if it does not exist
if (-not (Test-Path $LOG_PATH)) {
    New-Item -ItemType Directory -Path $LOG_PATH -Force | Out-Null
}

# Record start of execution
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Inizio backup automatico..." | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8

# Wait for the network share to be available (max 60 seconds)
$NETWORK_SHARE = "\\192.168.10.132\usbshare"
$maxRetries = 12
$retryDelay = 5

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Verifica accessibilità share di rete..." | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8

for ($i = 1; $i -le $maxRetries; $i++) {
    if (Test-Path $NETWORK_SHARE) {
        "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Share di rete accessibile (tentativo $i/$maxRetries)" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
        break
    }
    
    if ($i -eq $maxRetries) {
        "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ATTENZIONE: Share di rete non raggiungibile dopo $maxRetries tentativi. Continuo solo con backup locale." | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    } else {
        "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Tentativo $i/$maxRetries fallito, attendo $retryDelay secondi..." | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
        Start-Sleep -Seconds $retryDelay
    }
}

# Run backups
try {
    & $SCRIPT_PATH -Unattended 2>&1 | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    $exitCode = $LASTEXITCODE
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Backup completato (exit code: $exitCode)" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    exit $exitCode
} catch {
    "ERRORE: $_" | Out-File -FilePath $LOG_FILE -Append -Encoding UTF8
    exit 1
}
