# Entry point for Windows Task Scheduler (see README "Running on a
# schedule"). Sets the working directory to this script's own folder before
# running -- verified empirically that .env is only picked up when the
# process's CWD is the project root, even though data/ and the SQLite DB
# path resolve correctly regardless of CWD (they're derived from this
# project's own file location, not the working directory).
#
# Supports both setup paths from the README's "Quick start": if a native
# .venv exists (setup.sh/setup.ps1 or manual venv), it's used directly.
# Otherwise this falls back to running the Docker image -- so a
# Docker-only setup (no .venv on the host at all) still gets a working
# scheduled task, not a silent failure because .venv\Scripts\python.exe
# doesn't exist. The Docker fallback requires the image to already be
# built once (`docker build -t gst-law-docs-agent .`).
#
# Output is captured to BOTH the console (Task Scheduler's own window, if
# it opens one -- visible for real-time watching) and data/logs/cron.log,
# via Start-Transcript rather than a `2>&1 | Tee-Object` pipeline -- in
# PowerShell 5.1, redirecting a native exe's stderr with 2>&1 wraps every
# line as a NativeCommandError (this app's own logging writes to stderr by
# design, not because anything crashed), which is confusing/wrong to show
# for a normal run. Start-Transcript records the console session to a file
# without touching the native process's streams at all, avoiding that.
Set-Location $PSScriptRoot
New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null

$venvPython = ".\.venv\Scripts\python.exe"
$usingVenv = Test-Path $venvPython

Start-Transcript -Path "data\logs\cron.log" -Append -IncludeInvocationHeader | Out-Null
try {
    Write-Host "=== Scheduled run starting: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (path: $(if ($usingVenv) { 'native venv' } else { 'Docker fallback' })) ==="

    if ($usingVenv) {
        & $venvPython -m gst_agent.main --once
    } else {
        docker run --rm -v "${PSScriptRoot}\data:/app/data" gst-law-docs-agent gst_agent.main --once
    }

    Write-Host "=== Scheduled run finished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (exit code: $LASTEXITCODE) ==="
} finally {
    Stop-Transcript | Out-Null
}
