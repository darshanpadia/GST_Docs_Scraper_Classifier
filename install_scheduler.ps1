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

# LogonType S4U (below) needs local admin rights to *configure* -- even
# though the task itself then runs at standard/Limited rights, not
# elevated. Checked explicitly, before touching any existing task, so a
# non-elevated run fails fast with a clear message instead of silently
# leaving no task registered at all (which is what happened before this
# check existed: Register-ScheduledTask threw "Access is denied", but the
# script kept going and printed a false "Registered..." success message
# anyway -- a real bug, not just the elevation requirement itself).
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $isAdmin) {
    throw "install_scheduler.ps1 must be run from an elevated (Administrator) PowerShell -- " +
        "right-click PowerShell, 'Run as administrator', then re-run this script from the project folder. " +
        "This is only needed to register the task; the task itself runs at standard rights afterward (RunLevel Limited), not elevated."
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Existing task '$TaskName' found -- replacing it."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

# Explicit principal, LogonType S4U specifically -- Register-ScheduledTask's
# default (no -Principal at all) creates a task with LogonType=Interactive,
# which only fires if you're actively logged into an unlocked session at
# the exact trigger moment. Locked, asleep, or logged out at 10 AM and
# Task Scheduler silently skips the run -- no error, no retry, and
# Get-ScheduledTaskInfo then shows LastTaskResult 267011 (SCHED_S_TASK_HAS_NOT_RUN)
# forever, which is exactly the "gets scheduled but never executes" bug
# this fixes. S4U runs it under this account in the background regardless
# of session state, with no password to store.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited

# -ErrorAction Stop explicitly, on top of the script-level preference:
# Register-ScheduledTask's CIM-provider errors have been observed NOT to
# honor $ErrorActionPreference reliably in this environment (this is
# exactly how the misleading "success" message above happened) -- explicit
# is the only way to be sure a real failure actually stops the script here.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Daily discover/download/classify pass for $scriptPath (gst_agent.main --once)." -ErrorAction Stop | Out-Null

Write-Host "Registered '$TaskName' -> runs $scriptPath daily at $Time, in the background even when not logged in."
Write-Host "Verify with: Get-ScheduledTask -TaskName `"$TaskName`" | Select-Object State"
Write-Host "Remove with: .\uninstall_scheduler.ps1"
