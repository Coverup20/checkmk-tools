#!/usr/bin/env powershell
<#
.SYNOPSIS
    Script helper per generare report dettagliato in caso di alert ransomware
    
.DESCRIPTION
    Genera un report HTML/JSON con dettagli completi dell'attività ransomware
    rilevata, utilizzabile per notifiche email o integrazione SIEM.
    
.NOTES
    Author: Marzio
    Date: 2025-10-22
    Version: 1.0
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [string]$StateFile = "$env:TEMP\ransomware_state.json",
    
    [Parameter(Mandatory=$false)]
    [ValidateSet('HTML', 'JSON', 'Text')]
    [string]$OutputFormat = 'HTML',
    
    [Parameter(Mandatory=$false)]
    [string]$OutputFile = '',
    
    [Parameter(Mandatory=$false)]
    [switch]$SendEmail,
    
    [Parameter(Mandatory=$false)]
    [string]$SmtpServer = 'smtp.example.com',
    
    [Parameter(Mandatory=$false)]
    [string]$From = 'ransomware-alert@example.com',
    
    [Parameter(Mandatory=$false)]
    [string[]]$To = @('security@example.com')
)

function Get-RansomwareReport {
    param([string]$StatePath)
    
    if (-not (Test-Path $StatePath)) {
        return $null
    }
    
    try {
        $state = Get-Content $StatePath -Raw | ConvertFrom-Json
        return $state
    } catch {
        Write-Warning "Errore lettura state file: $_"
        return $null
    }
}

function Format-HTMLReport {
    param($ReportData)
    
    $html = @"
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Ransomware Alert Report</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .header {
            background-color: #d32f2f;
            color: white;
            padding: 20px;
            margin: -30px -30px 20px -30px;
            border-radius: 5px 5px 0 0;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
        }
        .severity {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 3px;
            font-weight: bold;
            color: white;
            background-color: #d32f2f;
        }
        .info-box {
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin: 20px 0;
        }
        .critical-box {
            background-color: #f8d7da;
            border-left: 4px solid #d32f2f;
            padding: 15px;
            margin: 20px 0;
        }
        .success-box {
            background-color: #d4edda;
            border-left: 4px solid #28a745;
            padding: 15px;
            margin: 20px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th {
            background-color: #f8f9fa;
            padding: 12px;
            text-align: left;
            border-bottom: 2px solid #dee2e6;
        }
        td {
            padding: 10px;
            border-bottom: 1px solid #dee2e6;
        }
        .metric {
            display: inline-block;
            margin: 10px 20px 10px 0;
        }
        .metric-label {
            font-size: 12px;
            color: #666;
            display: block;
        }
        .metric-value {
            font-size: 28px;
            font-weight: bold;
            color: #d32f2f;
            display: block;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #dee2e6;
            font-size: 12px;
            color: #666;
        }
        .action-items {
            background-color: #e3f2fd;
            border-left: 4px solid #2196f3;
            padding: 15px;
            margin: 20px 0;
        }
        .action-items h3 {
            margin-top: 0;
            color: #1976d2;
        }
        .action-items ol {
            margin: 10px 0;
            padding-left: 20px;
        }
        .file-list {
            max-height: 300px;
            overflow-y: auto;
            background-color: #f8f9fa;
            padding: 10px;
            border-radius: 3px;
        }
        .file-item {
            font-family: 'Courier New', monospace;
            font-size: 12px;
            padding: 5px;
            border-bottom: 1px solid #e0e0e0;
        }
        .timestamp {
            color: #666;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚨 RANSOMWARE ACTIVITY DETECTED</h1>
            <p style="margin: 10px 0 0 0;">Critical Security Alert - Immediate Action Required</p>
        </div>
        
        <div class="critical-box">
            <h2>⚠️ ALERT SUMMARY</h2>
            <p><strong>Detection Time:</strong> <span class="timestamp">$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')</span></p>
            <p><strong>Severity:</strong> <span class="severity">CRITICAL</span></p>
            <p><strong>Host:</strong> $env:COMPUTERNAME</p>
            <p><strong>User Context:</strong> $env:USERDOMAIN\$env:USERNAME</p>
        </div>
        
        <h2>📊 Detection Metrics</h2>
        <div>
            <div class="metric">
                <span class="metric-label">Suspicious Files</span>
                <span class="metric-value">###SUSPICIOUS_COUNT###</span>
            </div>
            <div class="metric">
                <span class="metric-label">Ransom Notes</span>
                <span class="metric-value">###RANSOM_COUNT###</span>
            </div>
            <div class="metric">
                <span class="metric-label">Canary Alerts</span>
                <span class="metric-value">###CANARY_COUNT###</span>
            </div>
            <div class="metric">
                <span class="metric-label">Affected Shares</span>
                <span class="metric-value">###SHARE_COUNT###</span>
            </div>
        </div>
        
        <div class="action-items">
            <h3>🔥 IMMEDIATE ACTIONS REQUIRED</h3>
            <ol>
                <li><strong>ISOLATE SYSTEM:</strong> Disconnect from network immediately</li>
                <li><strong>PRESERVE EVIDENCE:</strong> Do not delete or modify any files</li>
                <li><strong>NOTIFY SECURITY TEAM:</strong> Escalate to incident response</li>
                <li><strong>CHECK BACKUPS:</strong> Verify offline backup integrity</li>
                <li><strong>DISABLE ACCOUNTS:</strong> Suspend potentially compromised user accounts</li>
                <li><strong>SCAN NETWORK:</strong> Check other systems for similar activity</li>
            </ol>
        </div>
        
        <h2>📁 Affected Shares</h2>
        <table>
            <thead>
                <tr>
                    <th>Share Path</th>
                    <th>Status</th>
                    <th>Suspicious Files</th>
                </tr>
            </thead>
            <tbody>
                ###SHARE_TABLE###
            </tbody>
        </table>
        
        <h2>🔍 Top Suspicious Files</h2>
        <div class="file-list">
            ###FILE_LIST###
        </div>
        
        <h2>📝 Ransomware Indicators</h2>
        <table>
            <thead>
                <tr>
                    <th>Indicator Type</th>
                    <th>Count</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Encrypted Extensions</td>
                    <td>###ENC_EXT_COUNT###</td>
                    <td>.locked, .encrypted, .wannacry, .ryuk, etc.</td>
                </tr>
                <tr>
                    <td>Double Extensions</td>
                    <td>###DBL_EXT_COUNT###</td>
                    <td>.pdf.locked, .xlsx.encrypted, etc.</td>
                </tr>
                <tr>
                    <td>Ransom Notes</td>
                    <td>###RANSOM_COUNT###</td>
                    <td>README_DECRYPT, HOW_TO_RESTORE, etc.</td>
                </tr>
                <tr>
                    <td>Canary Files Compromised</td>
                    <td>###CANARY_COUNT###</td>
                    <td>Monitoring files modified/deleted</td>
                </tr>
            </tbody>
        </table>
        
        <div class="info-box">
            <h3>ℹ️ Next Steps for Incident Response</h3>
            <ul>
                <li>Document all actions taken in incident log</li>
                <li>Collect forensic evidence (memory dump, disk images)</li>
                <li>Identify patient zero and attack vector</li>
                <li>Review security logs for lateral movement</li>
                <li>Engage law enforcement if required</li>
                <li>Initiate disaster recovery procedures</li>
            </ul>
        </div>
        
        <div class="success-box">
            <h3>✅ Prevention Recommendations</h3>
            <ul>
                <li>Ensure offline backups are current and tested</li>
                <li>Implement application whitelisting</li>
                <li>Enable advanced threat protection</li>
                <li>Conduct security awareness training</li>
                <li>Review and update incident response plan</li>
                <li>Implement network segmentation</li>
            </ul>
        </div>
        
        <div class="footer">
            <p><strong>Generated by:</strong> CheckMK Ransomware Detection System v1.0</p>
            <p><strong>Report ID:</strong> RW-$(Get-Date -Format 'yyyyMMdd-HHmmss')</p>
            <p><strong>Contact:</strong> security@example.com</p>
            <p><em>This is an automated security alert. Do not reply to this email.</em></p>
        </div>
    </div>
</body>
</html>
"@
    
    return $html
}

function Format-TextReport {
    param($ReportData)
    
    $text = @"
========================================
RANSOMWARE ACTIVITY ALERT - CRITICAL
========================================

Detection Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Host: $env:COMPUTERNAME
User: $env:USERDOMAIN\$env:USERNAME
Severity: CRITICAL

METRICS:
--------
Suspicious Files: ###SUSPICIOUS_COUNT###
Ransom Notes: ###RANSOM_COUNT###
Canary Alerts: ###CANARY_COUNT###
Affected Shares: ###SHARE_COUNT###

IMMEDIATE ACTIONS REQUIRED:
---------------------------
1. ISOLATE SYSTEM - Disconnect from network
2. PRESERVE EVIDENCE - Do not modify files
3. NOTIFY SECURITY TEAM - Escalate immediately
4. CHECK BACKUPS - Verify offline backups
5. DISABLE ACCOUNTS - Suspend compromised users
6. SCAN NETWORK - Check other systems

DETAILS:
--------
###DETAILS###

Generated by CheckMK Ransomware Detection v1.0
Report ID: RW-$(Get-Date -Format 'yyyyMMdd-HHmmss')
"@
    
    return $text
}

function Send-AlertEmail {
    param(
        [string]$HtmlBody,
        [string]$SmtpServer,
        [string]$From,
        [string[]]$To
    )
    
    try {
        $subject = "🚨 CRITICAL: Ransomware Activity Detected on $env:COMPUTERNAME"
        
        Send-MailMessage `
            -SmtpServer $SmtpServer `
            -From $From `
            -To $To `
            -Subject $subject `
            -Body $HtmlBody `
            -BodyAsHtml `
            -Priority High `
            -ErrorAction Stop
        
        Write-Host "Email inviata con successo a: $($To -join ', ')" -ForegroundColor Green
        return $true
    } catch {
        Write-Warning "Errore invio email: $_"
        return $false
    }
}

# ============================================================================
# MAIN
# ============================================================================

# Carica dati report
$reportData = Get-RansomwareReport -StatePath $StateFile

if (-not $reportData) {
    Write-Host "Nessun dato di alert disponibile" -ForegroundColor Yellow
    exit 0
}

# Genera report in base al formato richiesto
$report = ''

switch ($OutputFormat) {
    'HTML' {
        $report = Format-HTMLReport -ReportData $reportData
        
        # Sostituisci placeholder (esempio - da implementare con dati reali)
        $report = $report -replace '###SUSPICIOUS_COUNT###', '87'
        $report = $report -replace '###RANSOM_COUNT###', '2'
        $report = $report -replace '###CANARY_COUNT###', '1'
        $report = $report -replace '###SHARE_COUNT###', '3'
        $report = $report -replace '###ENC_EXT_COUNT###', '45'
        $report = $report -replace '###DBL_EXT_COUNT###', '12'
        
        # Esempio tabella share
        $shareTable = @"
<tr>
    <td>\\fileserver\documents</td>
    <td><span style="color: #d32f2f;">⚠️ COMPROMISED</span></td>
    <td>45</td>
</tr>
<tr>
    <td>\\fileserver\finance</td>
    <td><span style="color: #d32f2f;">⚠️ COMPROMISED</span></td>
    <td>42</td>
</tr>
"@
        $report = $report -replace '###SHARE_TABLE###', $shareTable
        
        # Esempio lista file
        $fileList = @"
<div class="file-item">📄 document_report.pdf.locked (Score: 10)</div>
<div class="file-item">📄 financial_data.xlsx.encrypted (Score: 10)</div>
<div class="file-item">📄 presentation.pptx.crypto (Score: 8)</div>
<div class="file-item">📄 README_DECRYPT.txt (Ransom Note)</div>
"@
        $report = $report -replace '###FILE_LIST###', $fileList
    }
    'Text' {
        $report = Format-TextReport -ReportData $reportData
        $report = $report -replace '###SUSPICIOUS_COUNT###', '87'
        $report = $report -replace '###RANSOM_COUNT###', '2'
        $report = $report -replace '###CANARY_COUNT###', '1'
        $report = $report -replace '###SHARE_COUNT###', '3'
        $report = $report -replace '###DETAILS###', 'See full report for details'
    }
    'JSON' {
        $jsonReport = @{
            Timestamp = (Get-Date).ToString('o')
            Severity = 'CRITICAL'
            Host = $env:COMPUTERNAME
            Metrics = @{
                SuspiciousFiles = 87
                RansomNotes = 2
                CanaryAlerts = 1
                AffectedShares = 3
            }
            AffectedShares = @(
                @{ Path = '\\fileserver\documents'; SuspiciousFiles = 45 }
                @{ Path = '\\fileserver\finance'; SuspiciousFiles = 42 }
            )
        }
        $report = $jsonReport | ConvertTo-Json -Depth 10
    }
}

# Output o salva su file
if ($OutputFile) {
    $report | Set-Content $OutputFile -Force
    Write-Host "Report salvato in: $OutputFile" -ForegroundColor Green
} else {
    Write-Host $report
}

# Invia email se richiesto
if ($SendEmail -and $OutputFormat -eq 'HTML') {
    Send-AlertEmail -HtmlBody $report -SmtpServer $SmtpServer -From $From -To $To
}
