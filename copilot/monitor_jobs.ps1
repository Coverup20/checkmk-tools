#!/usr/bin/env pwsh
#
# Copyright (C) 2025 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-2.0-only
#
# monitor_jobs.ps1 - Background jobs and daily baseline checks for monitoring servers
#
# Usage:
#   .\copilot\monitor_jobs.ps1 daily [sp|us|all]
#   .\copilot\monitor_jobs.ps1 notify [sp|us|all] [-Minutes 60] [-Interval 15]
#   .\copilot\monitor_jobs.ps1 status
#   .\copilot\monitor_jobs.ps1 stop

param(
    [Parameter(Position=0)][string]$Command = "help",
    [Parameter(Position=1)][string]$Target  = "all",
    [int]$Minutes  = 60,
    [int]$Interval = 15
)

$VERSION   = "1.0.0"
$WORKSPACE = Split-Path -Parent $PSScriptRoot
$LOG_FILE  = Join-Path $WORKSPACE "monitor-jobs.log"

$SSH_HOSTS = @{
    sp = "srv-monitoring-sp"
    us = "srv-monitoring-us"
}

# --- Remote Python script for daily checks ---
$DAILY_PY = @'
import subprocess, datetime, urllib.request

def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)

def sec(t):
    print(f"\n{'='*55}\n  {t}\n{'='*55}")

# SYSTEM
sec("SYSTEM")
_, out = run(["uptime", "-p"])
print(f"  Uptime:   {out}")
_, out = run(["hostname", "-f"])
print(f"  Hostname: {out}")
rc, out = run(["df", "-h", "/"])
rows = [r for r in out.split("\n") if r.strip()]
if len(rows) > 1:
    row = rows[-1].split()
    if len(row) >= 5:
        print(f"  Disk /:   {row[3]} free / {row[1]} total ({row[4]} used)")
rc, out = run(["free", "-h"])
rows = [r for r in out.split("\n") if r.strip()]
if len(rows) > 1:
    row = rows[1].split()
    if len(row) >= 3:
        print(f"  Memory:   {row[2]} used / {row[1]} total")

# OMD STATUS
sec("OMD STATUS")
rc, out = run(["omd", "status", "monitoring"])
for line in out.split("\n"):
    line = line.strip()
    if not line:
        continue
    prefix = "!!! " if "stopped" in line.lower() and "Overall" not in line else ""
    print(f"  {prefix}{line}")

# KEY SERVICES
sec("KEY SERVICES")
for svc in ["cron", "systemd-resolved", "rsyslog", "fail2ban"]:
    rc, out = run(["systemctl", "is-active", svc])
    mark = "" if rc == 0 else "  !!!"
    print(f"  {svc}: {out.strip()}{mark}")

# STOPPED SERVICES (all failed/inactive)
sec("STOPPED SERVICES (systemctl --failed)")
rc, out = run(["systemctl", "--failed", "--no-legend", "--no-pager"])
lines = [l.strip() for l in out.split("\n") if l.strip() and "0 loaded" not in l]
if lines:
    for l in lines:
        print(f"  !!! {l}")
else:
    print("  none")

# CRONTAB root
sec("CRONTAB (root)")
rc, out = run(["crontab", "-l"])
lines = [l for l in out.split("\n") if l.strip() and not l.startswith("#")]
if lines:
    for l in lines:
        print(f"  {l}")
else:
    print("  (none)")

# CRONTAB monitoring user
sec("CRONTAB (monitoring user)")
rc, out = run(["su", "-", "monitoring", "-c", "crontab -l"])
lines = [l for l in out.split("\n") if l.strip() and not l.startswith("#")]
if lines:
    for l in lines:
        print(f"  {l}")
else:
    print("  (none)")

# REPO
sec("REPO /opt/checkmk-tools")
rc, out = run(["git", "-C", "/opt/checkmk-tools", "log", "--oneline", "-1"])
print(f"  Last commit:  {out if rc == 0 else 'NOT FOUND - repo missing?'}")
rc, out = run(["git", "-C", "/opt/checkmk-tools", "status", "--short"])
print(f"  Working tree: {'clean' if not out.strip() else out.strip()}")
rc, out = run(["git", "-C", "/opt/checkmk-tools", "remote", "get-url", "origin"])
print(f"  Remote:       {out if rc == 0 else '?'}")
rc, out = run(["stat", "-c", "%y", "/opt/checkmk-tools/.git/FETCH_HEAD"])
if rc == 0:
    print(f"  Last pull:    {out.split('.')[0]}")

# LOCAL CHECKS
sec("LOCAL CHECKS (/usr/lib/check_mk_agent/local)")
rc, out = run(["ls", "/usr/lib/check_mk_agent/local/"])
files = [f for f in out.split("\n") if f.strip() and f != "__pycache__"]
print(f"  Deployed: {len(files)} checks")
for f in sorted(files):
    print(f"    {f}")

# TELEGRAM CONNECTIVITY
sec("TELEGRAM CONNECTIVITY")
try:
    r = urllib.request.urlopen("https://api.telegram.org", timeout=5)
    print(f"  api.telegram.org: OK (http {r.status})")
except Exception as e:
    print(f"  api.telegram.org: FAIL !!!  ({e})")

# FALLBACK DNS
import subprocess as sp2
rc2, dns_out = run(["resolvectl", "status"])
fallback = [l.strip() for l in dns_out.split("\n") if "Fallback" in l]
if fallback:
    print(f"  FallbackDNS: {fallback[0]}")
else:
    print("  FallbackDNS: !!! NOT CONFIGURED")

# NOTIFY LOG - ERRORS last 24h
sec("NOTIFY LOG - ERRORS (last 24h)")
log_path = "/omd/sites/monitoring/var/log/notify.log"
try:
    today     = datetime.date.today().strftime("%Y-%m-%d")
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    with open(log_path) as f:
        lines = f.readlines()
    errors = [
        l.strip() for l in lines
        if (today in l or yesterday in l)
        and any(k in l for k in ["ERROR", "Traceback", "Unauthorized", "FAIL", "failed"])
    ]
    print(f"  Error count (24h): {len(errors)}")
    for e in errors[-5:]:
        print(f"    {e[:120]}")
except Exception as e:
    print(f"  Cannot read log: {e}")

print(f"\n{'='*55}\n  CHECK COMPLETE\n{'='*55}\n")
'@

# --- Helper functions ---

function Get-Hosts {
    if ($Target -eq "all") { return $SSH_HOSTS.Keys | Sort-Object }
    if ($SSH_HOSTS.ContainsKey($Target)) { return @($Target) }
    Write-Host "Unknown target '$Target'. Use: sp, us, all" -ForegroundColor Red
    exit 1
}

function Invoke-Daily {
    $b64 = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($DAILY_PY))
    foreach ($key in Get-Hosts) {
        $alias = $SSH_HOSTS[$key]
        Write-Host "`n$('#'*60)" -ForegroundColor Cyan
        Write-Host "  DAILY CHECK: $($key.ToUpper()) - $alias" -ForegroundColor Cyan
        Write-Host "$('#'*60)" -ForegroundColor Cyan
        $out = wsl -d kali-linux bash -c "ssh $alias 'echo $b64 | base64 -d | python3 2>&1'" 2>&1
        Write-Host ($out -join "`n")
    }
}

function Invoke-NotifyMonitor {
    $hosts    = @(Get-Hosts)
    $sshHosts = $SSH_HOSTS
    $logFile  = $LOG_FILE
    $mins     = $Minutes
    $ivl      = $Interval
    $jobName  = "NotifyMonitor_$(Get-Date -Format 'HHmm')"

    $job = Start-Job -Name $jobName -ScriptBlock {
        param($hosts, $sshHosts, $mins, $ivl, $logFile)
        $total = [math]::Ceiling($mins / $ivl)
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content $logFile ""
        Add-Content $logFile "[$ts] === MONITOR STARTED - hosts: $($hosts -join ',') - ${mins}min every ${ivl}min ==="
        for ($i = 0; $i -le $total; $i++) {
            $ts = Get-Date -Format "HH:mm:ss"
            Add-Content $logFile "[$ts] --- check $($i+1)/$($total+1) ---"
            foreach ($key in $hosts) {
                $alias = $sshHosts[$key]
                $out = wsl -d kali-linux bash -c "ssh $alias 'tail -30 /omd/sites/monitoring/var/log/notify.log 2>/dev/null | grep -E ""ERROR|Traceback|Unauthorized|Telegram OK|failed"" | tail -5'" 2>&1
                $line = if ($out) { ($out -join " ").Trim() } else { "OK - no errors" }
                Add-Content $logFile "  [$($key.ToUpper())] $line"
            }
            Add-Content $logFile ""
            if ($i -lt $total) { Start-Sleep -Seconds ($ivl * 60) }
        }
        Add-Content $logFile "[$( Get-Date -Format 'HH:mm:ss')] === MONITOR COMPLETED ==="
    } -ArgumentList $hosts, $sshHosts, $mins, $ivl, $logFile

    Write-Host "Monitor job started: $jobName" -ForegroundColor Green
    Write-Host "  Servers:   $($hosts -join ', ')"
    Write-Host "  Duration:  $Minutes min, check every $Interval min"
    Write-Host "  Total:     $([math]::Ceiling($Minutes / $Interval) + 1) checks"
    Write-Host "  Log:       $LOG_FILE"
    Write-Host "`nRun '.\copilot\monitor_jobs.ps1 status' to follow progress"
}

function Show-Status {
    Write-Host "`n=== RUNNING JOBS ===" -ForegroundColor Cyan
    $jobs = Get-Job | Where-Object { $_.Name -like "NotifyMonitor*" }
    if ($jobs) {
        $jobs | Format-Table Id, Name, State, HasMoreData -AutoSize
    } else {
        Write-Host "  No monitor jobs running"
    }
    Write-Host "`n=== RECENT LOG (last 40 lines) ===" -ForegroundColor Cyan
    if (Test-Path $LOG_FILE) {
        Get-Content $LOG_FILE -Tail 40
    } else {
        Write-Host "  No log file yet ($LOG_FILE)"
    }
}

function Stop-AllJobs {
    $jobs = Get-Job | Where-Object { $_.Name -like "NotifyMonitor*" }
    if ($jobs) {
        $jobs | Stop-Job
        $jobs | Remove-Job
        Write-Host "Stopped $($jobs.Count) job(s)" -ForegroundColor Yellow
    } else {
        Write-Host "No monitor jobs running"
    }
}

# --- Main ---
switch ($Command.ToLower()) {
    "daily"  { Invoke-Daily }
    "notify" { Invoke-NotifyMonitor }
    "status" { Show-Status }
    "stop"   { Stop-AllJobs }
    default  {
        Write-Host "monitor_jobs.ps1 v$VERSION"
        Write-Host ""
        Write-Host "Usage:"
        Write-Host "  .\copilot\monitor_jobs.ps1 daily  [sp|us|all]"
        Write-Host "  .\copilot\monitor_jobs.ps1 notify [sp|us|all] [-Minutes 60] [-Interval 15]"
        Write-Host "  .\copilot\monitor_jobs.ps1 status"
        Write-Host "  .\copilot\monitor_jobs.ps1 stop"
        Write-Host ""
        Write-Host "Daily checks include:"
        Write-Host "  system (uptime, disk, memory)"
        Write-Host "  OMD status (all components)"
        Write-Host "  key services + stopped services"
        Write-Host "  crontab (root + monitoring user)"
        Write-Host "  repo /opt/checkmk-tools (commit, status, last pull)"
        Write-Host "  deployed local checks"
        Write-Host "  Telegram connectivity + FallbackDNS"
        Write-Host "  notify log errors (last 24h)"
    }
}
