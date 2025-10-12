# CheckMK Agent Plugin for Windows Client Systems
# This plugin collects standard Windows client metrics and security status
# Deploy to: C:\ProgramData\checkmk\agent\plugins\
# Requires: PowerShell 5.1 or later

# Set error action preference
$ErrorActionPreference = "SilentlyContinue"

Write-Host "<<<windows_client_info>>>"
$OS = Get-CimInstance Win32_OperatingSystem
$CS = Get-CimInstance Win32_ComputerSystem
Write-Host "hostname: $($CS.Name)"
Write-Host "os_version: $($OS.Caption)"
Write-Host "os_build: $($OS.BuildNumber)"
Write-Host "uptime_hours: $([math]::Round((New-TimeSpan -Start $OS.LastBootUpTime -End (Get-Date)).TotalHours, 2))"
Write-Host "domain: $($CS.Domain)"

# Check Windows Updates
Write-Host "<<<windows_client_updates>>>"
try {
    $UpdateSession = New-Object -ComObject Microsoft.Update.Session
    $UpdateSearcher = $UpdateSession.CreateUpdateSearcher()
    $SearchResult = $UpdateSearcher.Search("IsInstalled=0")
    $TotalUpdates = $SearchResult.Updates.Count
    $SecurityUpdates = ($SearchResult.Updates | Where-Object { $_.MsrcSeverity -ne $null }).Count
    Write-Host "updates_available: $TotalUpdates"
    Write-Host "security_updates: $SecurityUpdates"
} catch {
    Write-Host "updates_available: unavailable"
}

# Check critical services
Write-Host "<<<windows_client_services>>>"
$CriticalServices = @("WinDefend", "BITS", "wuauserv", "EventLog", "Dhcp", "Dnscache")
foreach ($ServiceName in $CriticalServices) {
    $Service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($Service) {
        Write-Host "${ServiceName}: $($Service.Status)"
    }
}

# Check Windows Defender status
Write-Host "<<<windows_client_defender>>>"
try {
    $DefenderStatus = Get-MpComputerStatus
    Write-Host "defender_enabled: $($DefenderStatus.AntivirusEnabled)"
    Write-Host "realtime_protection: $($DefenderStatus.RealTimeProtectionEnabled)"
    Write-Host "signature_age_days: $((New-TimeSpan -Start $DefenderStatus.AntivirusSignatureLastUpdated -End (Get-Date)).Days)"
    Write-Host "last_scan: $($DefenderStatus.LastFullScanEndTime)"
    Write-Host "quick_scan_age_days: $((New-TimeSpan -Start $DefenderStatus.LastQuickScanEndTime -End (Get-Date)).Days)"
} catch {
    Write-Host "defender_status: unavailable"
}

# Check Windows Firewall
Write-Host "<<<windows_client_firewall>>>"
try {
    $FirewallProfiles = Get-NetFirewallProfile
    foreach ($Profile in $FirewallProfiles) {
        Write-Host "$($Profile.Name): $($Profile.Enabled)"
    }
} catch {
    Write-Host "firewall_status: unavailable"
}

# Check disk usage
Write-Host "<<<windows_client_disk>>>"
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
    $UsedGB = [math]::Round(($_.Size - $_.FreeSpace) / 1GB, 2)
    $FreeGB = [math]::Round($_.FreeSpace / 1GB, 2)
    $TotalGB = [math]::Round($_.Size / 1GB, 2)
    $UsedPercent = [math]::Round(($UsedGB / $TotalGB) * 100, 1)
    Write-Host "$($_.DeviceID): used=$UsedPercent% free=$FreeGB GB total=$TotalGB GB"
}

# Check BitLocker status
Write-Host "<<<windows_client_bitlocker>>>"
try {
    $BitLockerVolumes = Get-BitLockerVolume
    foreach ($Volume in $BitLockerVolumes) {
        Write-Host "$($Volume.MountPoint): protection=$($Volume.ProtectionStatus) encryption=$($Volume.EncryptionPercentage)%"
    }
} catch {
    Write-Host "bitlocker: unavailable"
}

# Check failed login attempts (last 24 hours)
Write-Host "<<<windows_client_security_events>>>"
try {
    $FailedLogins = Get-WinEvent -FilterHashtable @{
        LogName='Security'
        Id=4625
        StartTime=(Get-Date).AddDays(-1)
    } -MaxEvents 1000 -ErrorAction SilentlyContinue
    Write-Host "failed_logins_24h: $($FailedLogins.Count)"
} catch {
    Write-Host "failed_logins_24h: 0"
}

# Check pending reboot
Write-Host "<<<windows_client_reboot>>>"
$RebootPending = $false
if (Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending") {
    $RebootPending = $true
}
if (Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired") {
    $RebootPending = $true
}
Write-Host "reboot_pending: $RebootPending"

# Check system performance
Write-Host "<<<windows_client_performance>>>"
$CPU = Get-CimInstance Win32_Processor
$CPULoad = ($CPU | Measure-Object -Property LoadPercentage -Average).Average
Write-Host "cpu_load_percent: $CPULoad"

$Memory = Get-CimInstance Win32_OperatingSystem
$MemoryUsedPercent = [math]::Round((($Memory.TotalVisibleMemorySize - $Memory.FreePhysicalMemory) / $Memory.TotalVisibleMemorySize) * 100, 2)
Write-Host "memory_used_percent: $MemoryUsedPercent"

# Check installed applications (count)
Write-Host "<<<windows_client_applications>>>"
$InstalledApps = Get-ItemProperty "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*" | Where-Object { $_.DisplayName }
Write-Host "installed_applications: $($InstalledApps.Count)"

# Check Event Log errors (last 24 hours)
Write-Host "<<<windows_client_eventlog>>>"
try {
    $SystemErrors = Get-WinEvent -FilterHashtable @{
        LogName='System'
        Level=2
        StartTime=(Get-Date).AddDays(-1)
    } -MaxEvents 1000 -ErrorAction SilentlyContinue
    Write-Host "system_errors_24h: $($SystemErrors.Count)"
    
    $AppErrors = Get-WinEvent -FilterHashtable @{
        LogName='Application'
        Level=2
        StartTime=(Get-Date).AddDays(-1)
    } -MaxEvents 1000 -ErrorAction SilentlyContinue
    Write-Host "application_errors_24h: $($AppErrors.Count)"
} catch {
    Write-Host "eventlog_errors: unavailable"
}

# Check network adapters
Write-Host "<<<windows_client_network>>>"
Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
    Write-Host "$($_.Name): $($_.Status) - $($_.LinkSpeed)"
}

# Check certificate expiration (system certificates)
Write-Host "<<<windows_client_certificates>>>"
try {
    $ExpiringCerts = Get-ChildItem Cert:\LocalMachine\My | Where-Object { 
        $_.NotAfter -lt (Get-Date).AddDays(30) -and $_.NotAfter -gt (Get-Date)
    }
    Write-Host "expiring_certificates_30d: $($ExpiringCerts.Count)"
} catch {
    Write-Host "certificates: unavailable"
}

# Check Windows license activation
Write-Host "<<<windows_client_license>>>"
try {
    $LicenseStatus = Get-CimInstance SoftwareLicensingProduct -Filter "ApplicationID = '55c92734-d682-4d71-983e-d6ec3f16059f' AND PartialProductKey <> null"
    Write-Host "license_status: $($LicenseStatus.LicenseStatus)"
} catch {
    Write-Host "license_status: unavailable"
}

# Check last Windows Update installation
Write-Host "<<<windows_client_last_update>>>"
try {
    $Session = New-Object -ComObject "Microsoft.Update.Session"
    $Searcher = $Session.CreateUpdateSearcher()
    $HistoryCount = $Searcher.GetTotalHistoryCount()
    if ($HistoryCount -gt 0) {
        $History = $Searcher.QueryHistory(0, 1)
        Write-Host "last_update_date: $($History[0].Date)"
    }
} catch {
    Write-Host "last_update_date: unavailable"
}
