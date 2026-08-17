# Removes the scheduled task created by install_scheduler.ps1.
param([string]$TaskName = "GST Law Document Agent")

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
} else {
    Write-Host "No scheduled task named '$TaskName' found -- nothing to do."
}
