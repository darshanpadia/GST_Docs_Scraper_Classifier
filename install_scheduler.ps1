# Registers the daily Windows Task Scheduler entry for wherever THIS repo
# currently lives -- run this once after cloning (or after moving the
# project folder). Unlike a one-off `Register-ScheduledTask` command typed
# into a terminal, this resolves its own path dynamically ($PSScriptRoot),
# so the same script produces a correctly-pointed task on any machine or
# clone location, instead of a hardcoded path that only worked on the
# machine it was originally set up on.
#
# Safe to re-run: replaces any existing task of the same name rather than
# erroring or creating a duplicate.
param(
    [string]$TaskName = "GST Law Document Agent",
    [string]$Time = "10:00AM"
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "run_scheduled.ps1"

if (-not (Test-Path $scriptPath)) {
    throw "run_scheduled.ps1 not found next to this script -- run install_scheduler.ps1 from inside the project folder."
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing task '$TaskName' found -- replacing it."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Daily discover/download/classify pass for $scriptPath (gst_agent.main --once)." | Out-Null

Write-Host "Registered '$TaskName' -> runs $scriptPath daily at $Time."
Write-Host "Verify with: Get-ScheduledTask -TaskName `"$TaskName`" | Select-Object State"
Write-Host "Remove with: .\uninstall_scheduler.ps1"
