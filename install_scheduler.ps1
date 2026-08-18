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
    [string]$Time = "10:00AM",
    # Register the task so it pops up a visible console window while it
    # runs, instead of running invisibly in the background. See the
    # LogonType tradeoff documented at the $principal assignment below --
    # this buys visibility at the cost of only firing while you're logged
    # in with an unlocked session, so it's for demos and watching a run
    # happen, not for the unattended daily schedule.
    [switch]$ShowWindow
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

# AllowStartIfOnBatteries / DontStopIfGoingOnBatteries explicitly -- without
# them, New-ScheduledTaskSettingsSet defaults to DisallowStartIfOnBatteries
# = True and StopIfGoingOnBatteries = True. On a laptop not plugged into AC
# at the trigger moment, Task Scheduler silently refuses to start the task
# at all -- same class of silent skip as the LogonType issue below, just a
# second, independent cause of the same "gets scheduled but never
# executes" symptom. This is a lightweight scraping task; there's no
# reason to gate it on AC power.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

# LogonType is a genuine either/or, not a setting with one right answer:
#
#   S4U (default here)  -- runs under this account in the background
#                          regardless of session state, no password stored.
#                          Fires reliably when locked/asleep/logged out.
#                          No desktop session, therefore NO visible window.
#
#   Interactive (-ShowWindow) -- pops up a real console window you can
#                          watch live, but ONLY fires if you're logged in
#                          with an unlocked session at the exact trigger
#                          moment. Otherwise Task Scheduler silently skips
#                          the run: no error, no retry, and
#                          Get-ScheduledTaskInfo just shows LastTaskResult
#                          267011 (SCHED_S_TASK_HAS_NOT_RUN) forever. That
#                          was the original "gets scheduled but never
#                          executes" bug, which is why it is not the default.
#
# Either way the run is fully logged to data/logs/cron.log, so S4U loses
# no information -- only the popup. To watch a background run live:
#   Get-Content data\logs\cron.log -Wait -Tail 20
if ($ShowWindow) {
    Write-Host "NOTE: -ShowWindow registers the task as Interactive so you can watch it run." -ForegroundColor Yellow
    Write-Host "      It will ONLY fire while you're logged in with an unlocked session." -ForegroundColor Yellow
    Write-Host "      Re-run without -ShowWindow for the reliable unattended schedule." -ForegroundColor Yellow
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
} else {
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
}

# -ErrorAction Stop explicitly, on top of the script-level preference:
# Register-ScheduledTask's CIM-provider errors have been observed NOT to
# honor $ErrorActionPreference reliably in this environment (this is
# exactly how the misleading "success" message above happened) -- explicit
# is the only way to be sure a real failure actually stops the script here.
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Daily discover/download/classify pass for $scriptPath (gst_agent.main --once)." -ErrorAction Stop | Out-Null

$mode = if ($ShowWindow) { "in a visible window (only while logged in)" } else { "in the background even when not logged in" }
Write-Host "Registered '$TaskName' -> runs $scriptPath daily at $Time, $mode."
Write-Host "Verify with:  Get-ScheduledTask -TaskName `"$TaskName`" | Select-Object State"
Write-Host "Watch a run:  Get-Content `"$PSScriptRoot\data\logs\cron.log`" -Wait -Tail 20"
Write-Host "Remove with:  .\uninstall_scheduler.ps1"
