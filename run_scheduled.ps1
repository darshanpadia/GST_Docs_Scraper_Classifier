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
# Output is appended to data/logs/cron.log -- a secondary, unstructured log
# distinct from the app's own structured data/logs/gst_agent.log, meant to
# catch anything that happens outside the app's own logging (e.g. a
# top-level crash before logging is even configured).
Set-Location $PSScriptRoot

$venvPython = ".\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m gst_agent.main --once *>> "data\logs\cron.log"
} else {
    docker run --rm -v "${PSScriptRoot}\data:/app/data" gst-law-docs-agent gst_agent.main --once *>> "data\logs\cron.log"
}
