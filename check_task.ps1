$taskName = "BackupSyncComplete"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Task '$taskName' exists."
    Write-Host "State: $($task.State)"
} else {
    Write-Host "Task '$taskName' does not exist."
}