# Entry point for Windows Task Scheduler (see README "Running on a
# schedule"). Sets the working directory to this script's own folder before
# running -- verified empirically that .env is only picked up when the
# process's CWD is the project root, even though data/ and the SQLite DB
# path resolve correctly regardless of CWD (they're derived from this
# project's own file location, not the working directory).
#
# Output is appended to data/logs/cron.log -- a secondary, unstructured log
# distinct from the app's own structured data/logs/gst_agent.log, meant to
# catch anything that happens outside the app's own logging (e.g. a
# top-level crash before logging is even configured).
Set-Location $PSScriptRoot
& ".\.venv\Scripts\python.exe" -m gst_agent.main --once *>> "data\logs\cron.log"
