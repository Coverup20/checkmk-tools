#Requires -RunAsAdministrator

$taskName = "BackupSyncComplete"
$scriptPath = "C:\Users\Marzio\Desktop\CheckMK\Script\backup-sync-complete.ps1"

$launcherPath = "C:\Users\Marzio\Desktop\CheckMK\Script\backup-sync-complete-launcher.bat"
$action = New-ScheduledTaskAction -Execute $launcherPath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 90) -RepetitionDuration (New-TimeSpan -Days 365)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force