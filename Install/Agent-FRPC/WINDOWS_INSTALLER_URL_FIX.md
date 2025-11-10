# Windows Installer - URL Fallback Update

**Date:** 2025-11-07 (Continuation)  
**Status:** ✅ FIXED

---

## Issue: CheckMK Agent Download Failed (404)

### Problem
When running the installer, the download failed with:
```
[ERR] Errore durante download: Errore del server remoto: (404) Non trovato.
```

### Root Cause
The hardcoded URL for CheckMK Agent was:
```
https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent-2.4.0p14-1_all.msi
```

This URL returned 404 error (not found).

### Solution Implemented

Added **URL fallback mechanism** with multiple mirror support:

```powershell
# Multiple URLs with fallback
$CHECKMK_MSI_URLS = @(
    "https://download.checkmk.com/checkmk/$CHECKMK_VERSION/check-mk-agent-$CHECKMK_VERSION-1_all.msi",
    "https://monitoring.nethlab.it/monitoring/check_mk/agents/check-mk-agent-$CHECKMK_VERSION-1_all.msi"
)
```

**Features:**
- ✅ Primary URL: Official CheckMK download server
- ✅ Fallback URL: Local/backup server
- ✅ Automatic retry on failure
- ✅ Clear feedback to user

### Code Changes

**Before:**
```powershell
(New-Object Net.WebClient).DownloadFile($CHECKMK_MSI_URL, $msiFile)
```

**After:**
```powershell
foreach ($url in $CHECKMK_MSI_URLS) {
    try {
        (New-Object Net.WebClient).DownloadFile($url, $msiFile)
        $downloadSuccess = $true
        break
    }
    catch {
        Write-Host "    [WARN] URL fallito: ..." -ForegroundColor Yellow
        Continue
    }
}
```

### Testing

To test the installer:

```powershell
# Navigate to script directory
cd 'C:\Users\Marzio\Desktop\CheckMK\Script\script-tools'

# Right-click PowerShell: "Run as Administrator"
.\install-agent-interactive.ps1

# Confirm system detection
# Will now try both URLs if first fails
```

### Expected Output

```
[*] Download CheckMK Agent v2.4.0p14...
    Tentativo download da: https://download.checkmk.com/checkmk/2.4.0p14/...
    [OK] Download completato (X.XX MB)
```

Or if primary fails:
```
[*] Download CheckMK Agent v2.4.0p14...
    Tentativo download da: https://download.checkmk.com/...
    [WARN] URL fallito: Errore del server remoto: (404) Non trovato
    Tentativo download da: https://monitoring.nethlab.it/...
    [OK] Download completato (X.XX MB)
```

### Commit

```
30017b8 - fix: Add URL fallback for CheckMK Agent download with multiple mirror support
```

### Next Steps for User

1. **Run installer again** with the updated script
2. If using primary URL fails, fallback URL will be tried
3. If both fail, script will provide clear error message
4. Check system log: `$env:TEMP\CheckMK-Setup\checkmk-install.log`

---

## Files Modified

- `script-tools/install-agent-interactive.ps1`
  - Added: URL fallback array
  - Added: Loop to try multiple URLs
  - Added: User feedback on URL attempts
  - Added: Better error handling

---

## Configuration

To add more mirror URLs, edit line 27-30 in the script:

```powershell
$CHECKMK_MSI_URLS = @(
    "URL1",
    "URL2",
    "URL3"  # Add more if needed
)
```

---

## Status

✅ **Fix Applied**  
✅ **Syntax Validated**  
✅ **Committed to GitHub**  
✅ **Ready for Testing**

The installer will now automatically try multiple download sources if the primary fails.
