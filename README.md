# GST Law Document Collection & Classification Agent

An automated agent that discovers, downloads, extracts, classifies, and
files publicly available Indian GST law documents from official government
sources, once a day, with a hard cap of 100 new documents per run.

## Getting started : clone to running, every shell

You don't need any API key to see the core system work — document
discovery, downloading, OCR, and classification are all rule-based and
free by default. An LLM fallback exists for the classifier but is optional
and off unless explicitly enabled (see "LLM fallback specifically" below).

Commands below are given for **PowerShell**, **Command Prompt (cmd.exe)**,
and **bash** (Git Bash on Windows, or native on macOS/Linux) — pick
whichever matches the terminal you're actually using. Every path/quoting
variant shown has been run for real, not assumed (this project hit real
shell-specific bugs during development — see the Windows path gotcha
below — so nothing here is copy-pasted without verification).

### Prerequisites

- **Git** (to clone).
- Either **Docker Desktop** (Path A below — nothing else needed, easiest),
  **or** **Python 3.10+** (Paths B/C — native install).

### Step 1 — Clone the repository

Identical in all three shells:
```
git clone https://github.com/darshanpadia/GST_Docs_Scraper_Classifier.git
cd GST_Docs_Scraper_Classifier
```
Everything from here on assumes your terminal's current directory is this
folder (the one containing `Dockerfile`, `requirements.txt`, `gst_agent/`).

### Step 2 — Choose ONE setup path, easiest first

#### Path A — Docker (fewest moving parts: Python + Tesseract OCR are already inside the image)

**PowerShell:**
```powershell
docker build -t gst-law-docs-agent .
docker run --rm -v "${PWD}\data:/app/data" gst-law-docs-agent gst_agent.main --stats
```
**Command Prompt (cmd.exe):**
```cmd
docker build -t gst-law-docs-agent .
docker run --rm -v "%cd%\data:/app/data" gst-law-docs-agent gst_agent.main --stats
```
**Bash (macOS/Linux, or Git Bash on Windows):**
```bash
docker build -t gst-law-docs-agent .
docker run --rm -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.main --stats
```

**Windows + Git Bash path gotcha (hit this for real during development):**
`$(pwd)` gets silently mangled by Git Bash's MSYS path conversion for any
path containing a space (likely here) — Docker then mounts an *empty*
directory with no error, and `--stats` reports 0 documents even though
your real data is untouched on disk. Fix: use PowerShell or cmd.exe
instead (both verified working above), or from Git Bash prefix the
command and use an explicit path:
```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "D:/path/to/project/data:/app/data" gst-law-docs-agent gst_agent.main --stats
```

A fresh clone should show `"total_documents": 0`. From here, in any
shell: `docker run --rm -v "<same -v as above>" gst-law-docs-agent` runs a
real pass (default `--once`); add `gst_agent.web` instead of
`gst_agent.main --stats` for the web UI (see "Web UI" below).

#### Path B — One-shot setup script (native venv, no Docker)

**PowerShell:**
```powershell
.\setup.ps1
gst-agent --stats
```
**Command Prompt (cmd.exe)** — `.ps1` scripts don't run directly in cmd,
so invoke it through PowerShell, then drop back to cmd for the rest:
```cmd
powershell -ExecutionPolicy Bypass -File setup.ps1
.venv\Scripts\activate.bat
gst-agent --stats
```
**Bash (macOS/Linux/WSL/Git Bash):**
```bash
./setup.sh
source .venv/bin/activate     # macOS/Linux/WSL
source .venv/Scripts/activate # Git Bash on Windows
gst-agent --stats
```
This creates `.venv` and installs everything (including the LLM extras).
OCR needs a separate one-time Tesseract install on this path — see "OCR
setup" below; the agent runs fine without it regardless (OCR failures
degrade gracefully, they don't crash anything). Docker (Path A) avoids
that step entirely.

#### Path C — Manual venv (full control, no new files run)

**PowerShell:**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m gst_agent.main --stats
```
**Command Prompt (cmd.exe):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
python -m gst_agent.main --stats
```
**Bash (macOS/Linux/WSL/Git Bash):**
```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux/WSL
source .venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
python -m gst_agent.main --stats
```

### Step 3 — Confirm it worked

Whichever path you chose, `--stats` on a fresh clone should print:
```json
{"total_documents": 0, "by_status": {}, "by_category": {}, "failed": []}
```
That confirms a working install with no leftover state. All three paths
produce identical results from here: downloads in
`data/downloads/<Category>/`, state in `data/state.db` (SQLite), logs in
`data/logs/gst_agent.log`.

Copy `.env.example` to `.env` to change any default (optional — every
setting has a sensible built-in default; not used by Docker unless you
also pass `--env-file .env` to `docker run`).

### Step 4 — Set up the daily schedule

Running automatically once every 24 hours is a core requirement of this
project, not an optional extra — do this regardless of which Path A/B/C
you set up in Step 2 (the scheduler works with either, see "Running on a
schedule" for how it picks between them).

**Windows:** run this from an **elevated (Administrator) PowerShell** —
right-click PowerShell, "Run as administrator" — the script checks this
itself and refuses with a clear message otherwise. Elevation is only
needed to *register* the task; the task itself then runs at standard
rights, not elevated.
```powershell
.\install_scheduler.ps1                        # daily at 10:00 AM by default
.\install_scheduler.ps1 -Time "03:00AM"         # or pick your own time
```
One command, works the same after Docker (Path A), the setup script (Path
B), or a manual venv (Path C) — see "Running on a schedule" for exactly
how it picks between a native venv and the Docker image, and how to
verify a run actually fired.

**Linux/macOS:** add the appropriate `cron` line from "Running on a
schedule" (native venv or Docker, matching whichever path you set up in
Step 2) via `crontab -e`.

Next: **"Testing guide"** below has a numbered walkthrough of every way to
verify it's actually working — starting with the automated test suite (no
network, seconds to run) before anything that touches real government
sites.

## Web UI

A small local dashboard for operating and inspecting the agent visually,
instead of via the CLI — useful for a reviewer to click through rather than
type commands. It's a thin layer over the same `gst_agent.db`/`gst_agent.pipeline`
the CLI uses; it changes no behavior, it only calls the same functions
`--once` and `--retry-failed` already call.

```
gst-agent-ui                              # after setup.sh/setup.ps1, or:
python -m gst_agent.web                   # after the manual venv path
```
Docker (see "Getting started" for the shell-specific `-v` syntax):
```powershell
docker run --rm -p 5000:5000 -v "${PWD}\data:/app/data" gst-law-docs-agent gst_agent.web    # PowerShell
```
```cmd
docker run --rm -p 5000:5000 -v "%cd%\data:/app/data" gst-law-docs-agent gst_agent.web      REM cmd.exe
```
```bash
docker run --rm -p 5000:5000 -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.web    # bash
```
Then open **http://127.0.0.1:5000**.

- **Dashboard** — live counts (total/done/pending/failed), a breakdown by
  category, a "Run now" button (triggers a real pass — confirmed before
  running, since it contacts real government sites), a "Retry failed"
  button, recent run history, and full detail on any failed documents.
  Both buttons show a spinner and disable themselves for as long as the
  request is in flight, so a multi-minute real pass reads as "working," not
  as a hung page. **"Run now" is deliberately capped much lower than a real
  scheduled run** (`WEB_UI_MAX_NEW_DOCS_PER_RUN`, default 2, vs
  `MAX_NEW_DOCS_PER_RUN`, default 100) — it's a "confirm the agent is alive
  and working" button, not a way to do the day's real download work from
  the browser. Discovery itself is never capped either way, so clicking it
  repeatedly still builds up a full backlog for the next real scheduled
  run to work through.
- **Documents** — every discovered document, filterable by category and
  status. The document's **title is the link to its original source URL**;
  a separate "Open PDF" link serves the actual downloaded file straight
  from disk when one exists.
- **Logs** — tails `data/logs/gst_agent.log` so you can see exactly what
  happened during the last run without leaving the browser.

Binds to `127.0.0.1` only and has no authentication — it's a local operator
console for whoever is at the machine, not a service meant to be exposed to
a network. No JS framework, no CSS framework: server-rendered HTML and one
hand-written stylesheet, plus one small vanilla-JS function for the
run-in-progress spinner — kept intentionally simple.

## What it does

1. **Discovers** documents from official GST sources (below), using each
   source's own real, statically-crawlable listing pages.
2. **Downloads** new ones, deduplicating by URL and by content hash (so a
   PDF re-published under a new URL, e.g. a corrigendum, isn't re-saved).
3. **Stops after 100 new documents in a single run** — the cap is per run,
   not lifetime: run again (manually or on the daily schedule) and it picks
   up where it left off, downloading up to 100 more.
4. **Extracts text** from each PDF (native text layer first, OCR fallback
   for scanned pages).
5. **Classifies** each document by type (Act, Rule, Notification, Circular,
   Order, Instruction, Press Release, Council Meeting, Other, or a category
   introduced by the LLM fallback — see below) and files it into the
   matching `data/downloads/<Category>/` folder.
6. **Records everything** in SQLite — every discovery, download, extraction,
   classification, and failure, with the document's original source URL
   always kept — so the agent is restart-safe: if the process dies mid-run,
   the next run resumes from exactly where it stopped, with no duplicate
   downloads and no lost documents.

## Architecture

```
gst_agent/
  config.py       Central settings, all overridable via env/.env, no hardcoded secrets
  models.py       Shared data types (DiscoveredDoc, LLMClassification)
  db.py           SQLite state store: dedup, lifecycle tracking, restart-safety
  http_client.py  Polite HTTP: robots.txt enforcement, rate limiting, retries
  extractor.py    PDF text extraction (PyMuPDF) + OCR fallback (Tesseract)
  classifier.py   Rule-based classification + LLM fallback orchestration
  llm_providers/  One module per LLM provider (gemini.py, groq_provider.py,
                  anthropic_provider.py), all implementing the same interface
                  (base.py) so classifier.py can try them in a configured
                  order -- only imported if the fallback is enabled
  pipeline.py     Orchestrates discover -> download -> extract -> classify -> file
  main.py         CLI entrypoint
  web.py          Web UI (Flask) -- thin visual layer over db.py/pipeline.py, see "Web UI"
  templates/      Server-rendered HTML for the web UI (Jinja2, no JS framework)
  static/         One hand-written stylesheet
  sources/
    base.py           DocumentSource interface
    cbic.py            cbic-gst.gov.in
    gstcouncil.py       gstcouncil.gov.in
    indiacode.py        indiacode.nic.in (implemented, disabled by default -- see below)
```

Adding a new official source later means writing one class in `sources/`
and registering it in `sources/__init__.py` — nothing else changes.

Packaging/deployment files at the project root: `pyproject.toml` (gives the
`gst-agent` console command), `setup.sh`/`setup.ps1` (one-shot native
install), `Dockerfile`/`.dockerignore` (containerized run with Tesseract
pre-installed), `run_scheduled.ps1`/`install_scheduler.ps1`/`uninstall_scheduler.ps1`
(Windows Task Scheduler, see "Running on a schedule"). None of them affect
`gst_agent/`'s code — all three setup paths in "Getting started" execute
the exact same pipeline.

### Data flow per document

```
discovered -> downloaded -> extracted -> classified -> done
                  \-> failed (any stage) -- recorded, run continues
```

Every transition is committed to SQLite immediately (WAL mode), so a killed
process never loses track of a document mid-flight.

## Technical decisions and why

**Sources: research, not assumption.** Both enabled sources were manually
inspected before writing any scraping code. CBIC and GST Council both run
JavaScript-driven category menus with no crawlable index — but each also
has real, statically-server-rendered listing pages that *are* crawlable
(CBIC's homepage "What's New" ticker plus a few verified archive listing
pages; GST Council's `/en/gst-council-meeting` and `/en/circularsadvisory`).
Those are what's used. `indiacode.nic.in` (Ministry of Law and Justice,
canonical Act text) is implemented and tested but **disabled by default**:
its robots.txt permits crawling, but the server itself returns HTTP 403 to
an honestly-identifying User-Agent — a WAF check independent of robots.txt.
This project does not spoof a browser User-Agent to get past that; doing so
is exactly the kind of anti-bot bypass the assignment rules out. It's left
in the codebase, off, for anyone with a legitimate way to satisfy that
server's access policy.

**Politeness is centralized, not per-source.** `http_client.py` is the only
place any source is allowed to make an HTTP request. It enforces, for every
single request including PDFs: a robots.txt check (hard failure if
disallowed — `RobotsDisallowed` is never caught and retried around), a fixed
delay between requests, bounded retries with backoff, and an identifying
User-Agent with a contact email.

**Extraction: native text first, OCR only when needed.** Most CBIC and GST
Council PDFs are digitally generated, so PyMuPDF's native text extraction
is tried first (fast, free, exact). Only pages whose native text falls below
`OCR_MIN_CHARS_PER_PAGE` are rendered to an image and OCR'd with Tesseract —
this keeps OCR, which is slow, off the common path.

**Classification: rule-based first, LLM as a fallback, never the primary.**
GST legal documents follow predictable boilerplate ("in exercise of the
powers conferred by section... hereby makes the following rules", "Circular
No. .../2024", etc.), so a deterministic, free, reliable rule-based pass
(`classifier.classify_rule_based`) handles the large majority of documents.
Only for the minority it can't confidently place does the optional LLM
fallback (`ENABLE_LLM_FALLBACK=true`, off by default) get a turn — and any
failure there (no API key, network error, refusal) is caught and simply
leaves the document as `Other`, never fails the run.

**LLM fallback can introduce new categories, but only once they recur.**
When the LLM fallback doesn't think any active category fits, it can
propose a new one instead of forcing a bad match. That proposal is *not*
acted on immediately — a single LLM guess creating a new folder would be
noise, not signal. The document stays `Other` and the proposal is logged
(`documents.proposed_category`). Once the **same** proposed name has been
independently suggested for `CATEGORY_PROMOTION_THRESHOLD` (default 3)
distinct documents — cumulative across all runs, not just one — the agent
promotes it: creates the real folder, adds it to the active category list,
and retroactively sweeps in every document that had been parked under
`Other` with that same proposal. This is deliberately conservative: it
takes a genuinely recurring, previously-unanticipated document type to earn
a folder, not a one-off hallucination.

**Why an LLM at all, and which ones.** Rule-based classification alone can't
handle a document type nobody anticipated when the category list was
written; an LLM can read the actual content and reason about what kind of
document it is. It's scoped narrowly (fallback only, short excerpt,
structured JSON output) to keep it cheap and to keep classification mostly
deterministic.

Two genuinely free providers (no credit card) are configured by default, in
order — **Gemini first, Groq second**
(`LLM_PROVIDER_ORDER=gemini,groq` in `.env.example`):

| Provider | Free tier | Sign up |
|---|---|---|
| Gemini (`gemini-flash-latest`) | 1,500 requests/day, no expiry | aistudio.google.com/apikey |
| Groq (`openai/gpt-oss-20b`) | 14,400 requests/day, 30/min | console.groq.com/keys |

`classify_with_llm()` tries each configured provider in order and only
gives up once every one of them has failed or is unconfigured — so Gemini's
tighter daily limit or a transient outage doesn't take the fallback down as
long as Groq can still answer. Each provider module
(`gst_agent/llm_providers/`) implements the same small interface
(`is_configured()`, `classify()`), so adding a 4th provider later is one new
file. Anthropic is also implemented (`anthropic_provider.py`) but isn't in
the default order since it isn't free — add `anthropic` to
`LLM_PROVIDER_ORDER` yourself if you have a key.

**Scheduling: OS scheduler invoking `--once`, not a resident process.**
`python -m gst_agent.main --once` is a single self-contained pass — every
piece of state it needs is already in SQLite, so it doesn't need to keep
running. That makes an OS-level scheduler (Windows Task Scheduler, cron)
the natural fit: no long-running process to babysit or restart, and it's
inherently restart-safe by construction (there's no in-memory state to lose
between invocations). A thin `--loop` mode is also included purely as a
demo/portability convenience (`sleep(interval)` between `--once` calls) —
it is **not** the recommended production mechanism.

**Storage: SQLite, not a server.** One process, modest volume (hundreds to
low thousands of documents), no concurrent writers — SQLite in WAL mode
gives restart-safety and simple querying with zero operational overhead. A
real server-backed database would be pure overhead for what this actually
needs to do.

**Dedup: two independent keys.** `doc_url` (exact link already seen) and a
SHA-256 `file_hash` of the downloaded bytes (catches the same PDF
re-published under a different URL — a genuinely common pattern for
corrigenda). Both are enforced before anything is written to a category
folder.

## Running on a schedule

The documented production path is an OS scheduler invoking `--once` once a
day; no long-running process is required.

**Windows (Task Scheduler):** run `install_scheduler.ps1` once, from an
**elevated (Administrator) PowerShell**, inside the project folder:

```powershell
.\install_scheduler.ps1                        # daily at 10:00 AM by default
.\install_scheduler.ps1 -Time "03:00AM"         # or pick your own time
.\install_scheduler.ps1 -ShowWindow             # visible console window (see tradeoff below)
```

**Watching a run happen.** By default the task runs in the background with
no visible window — that's precisely *why* it fires reliably when the
machine is locked or you're logged out. Nothing is lost: every run is
fully captured in `data/logs/cron.log`. To watch one live:
```powershell
Get-Content data\logs\cron.log -Wait -Tail 20
```
If you specifically want a console window to pop up, `-ShowWindow`
registers the task as `Interactive` instead — but that mode **only fires
while you're logged in with an unlocked session**, so use it for demos and
switch back (re-run without the switch) for the real unattended schedule.

**Must be elevated, and here's the real bug that requirement fixes:**
`Register-ScheduledTask` without an explicit principal defaults to
`LogonType=Interactive`, which only fires the task if you're actively
logged into an unlocked session at the exact trigger moment — locked,
asleep, or logged out at 10 AM, and Task Scheduler silently skips the run
with no error and no retry. Discovered this exact way: a task that showed
`State: Ready` for days, that had genuinely never executed even once
(`Get-ScheduledTaskInfo` showed `LastTaskResult 267011`, Windows' code for
"has not run"). Fixed by registering with `LogonType S4U` instead, which
runs the task under your account in the background regardless of session
state, with no password to store — but configuring S4U itself needs local
admin rights, even though the task then runs at standard rights afterward
(`RunLevel Limited`), never elevated. The script checks elevation itself
and refuses early with a clear message if you're not admin, rather than
the silent partial failure that shipped before this was caught: an
unprivileged run used to throw "Access is denied" on registration but
kept going anyway and printed a false "Registered..." success message.

A Task Scheduler entry is **not** part of the git repo — cloning this
project to a new machine or folder does not bring the schedule with it, so
this is a one-time step anyone running the project needs to do themselves
(this includes you again, if you ever move or re-clone this folder). The
script resolves its own location automatically (`$PSScriptRoot`), so it
always points the task at wherever it's actually being run from — no
path to edit by hand, and safe to re-run (replaces any existing task of
the same name rather than erroring or duplicating it).

It targets `run_scheduled.ps1` (also at the project root) rather than
`python.exe` directly, because of something verified empirically: `data/`,
the SQLite DB path, etc. resolve correctly regardless of working directory
(they're derived from this project's own file location) — but **`.env` is
only loaded when the process's working directory is the project root**,
which Task Scheduler does not set by default. `run_scheduled.ps1` does
`Set-Location` to its own folder before running, so this isn't something
you need to get right by hand either.

**Works with either "Getting started" setup path, automatically.**
`run_scheduled.ps1` checks whether a native `.venv` exists (from
`setup.ps1`/`setup.sh` or a manual venv) and uses it directly if so;
otherwise it falls back to running the Docker image instead (which must
already be built once — `docker build -t gst-law-docs-agent .`). This
matters because a **Docker-only setup has no `.venv` on the host at all**
— without this fallback, a scheduled task on a Docker-only install would
silently fail every time it fired, since `.venv\Scripts\python.exe`
wouldn't exist. Verified both branches directly: the venv path (a real
scheduled-style run against the live project) and the Docker fallback
command (run standalone) each independently confirmed working.

Output is appended to `data/logs/cron.log` (in addition to the app's own
structured `data/logs/gst_agent.log`). Verify it's registered with
`Get-ScheduledTask -TaskName "GST Law Document Agent" | Select-Object State`,
and remove it with `.\uninstall_scheduler.ps1`.

**Linux/macOS (cron):**

```
0 3 * * * cd /path/to/project && .venv/bin/python -m gst_agent.main --once >> data/logs/cron.log 2>&1
```

**Linux/macOS (cron, Docker instead of a venv):**

```
0 3 * * * docker run --rm -v /path/to/project/data:/app/data gst-law-docs-agent --once >> /path/to/project/data/logs/cron.log 2>&1
```

**Manual / demo convenience (any OS, no scheduler setup):**

```bash
python -m gst_agent.main --loop --interval-hours 24
# or, if built: docker run -v "$(pwd)/data:/app/data" gst-law-docs-agent --loop --interval-hours 24
```

## Recovering from failures

Every failure is recorded per-document (stage + reason) and never aborts
the run — one bad PDF doesn't take down the batch. To re-attempt everything
currently stuck in a failed state:

```bash
python -m gst_agent.main --retry-failed
```

`python -m gst_agent.main --stats` shows current counts by status and
category, plus every failed document's stage and reason.

**Retries are bounded on two levels, not indefinite.** A single HTTP
request retries up to `MAX_RETRIES` times, but only for *transient*
failures (a 5xx server error, a genuine network exception, or a 429 rate
limit) — a 404/403/400 fails immediately on the first attempt instead,
since retrying a permanently dead or forbidden URL can never succeed and
previously wasted real time doing so. Separately, `--retry-failed` itself
stops re-attempting a specific document once it has failed
`MAX_RETRY_ATTEMPTS` times total (default 3) — a document that's proven
permanently broken (e.g. a dead link on the source's own listing page,
which does happen — see `gst_agent/sources/cbic.py`) is skipped on future
`--retry-failed` calls rather than retried forever, and the skip count is
reported alongside how many were actually retried.

## Configuration

All settings live in `gst_agent/config.py` with sensible defaults, and are
overridable via environment variables or a `.env` file (see
`.env.example` for the full list with explanations). Nothing is hardcoded;
no secrets are committed.

Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `MAX_NEW_DOCS_PER_RUN` | `100` | Cap on **new** documents per run for the CLI/scheduler (the real budget) |
| `WEB_UI_MAX_NEW_DOCS_PER_RUN` | `2` | Separate, lower cap only for the web UI's "Run now" button |
| `MAX_RETRY_ATTEMPTS` | `3` | A document stops being auto-retried by `--retry-failed` after this many total failures |
| `ENABLED_SOURCES` | `cbic,gstcouncil` | Comma-separated source modules to run |
| `ENABLE_LLM_FALLBACK` | `false` | Turn on the LLM classification fallback |
| `LLM_PROVIDER_ORDER` | `gemini,groq` | Providers tried in order (needs `GEMINI_API_KEY`/`GROQ_API_KEY`) |
| `CATEGORY_PROMOTION_THRESHOLD` | `3` | Recurrences needed before an LLM-proposed category becomes real |
| `OCR_MIN_CHARS_PER_PAGE` | `20` | Below this, a page is treated as scanned and OCR'd |

## Testing guide

Every way to verify this project, from fastest/safest to most realistic.
Do them roughly in this order — each one builds confidence before the next
does something more real (more network, more side effects).

### 1. Automated test suite (seconds, no network, no side effects)

```bash
pytest -q                    # native venv (activate first) or Docker: docker run --rm --entrypoint pytest gst-law-docs-agent -q
```
84 tests, all against mocked network/LLM calls. Covers: the DB layer
(dedup, lifecycle, restart-safety, category promotion, schema migration,
failure-count tracking), the polite HTTP client (permanent 4xx errors fail
fast without retrying; genuine transient failures -- 5xx, 429, network
exceptions -- still retry), each source's HTML parsing (against real page
structure captured from the live sites), the extractor (real minimal
PDFs, OCR path mocked), the classifier + all 3 LLM providers (rule-based
patterns, provider fallback chain, hallucinated-category handling), the
pipeline (discovery, the 100-doc cap, cross-run backlog resumption,
per-document failure isolation, the retry-attempt cap, category
promotion), and the web UI (every route via Flask's test client --
rendering, filtering, real PDF byte-serving). Expect `NN passed` with no
failures; a stray `DeprecationWarning` from inside a third-party SDK is
harmless.

### 2. Live discovery dry-run (real network, zero downloads)

```bash
python scripts_dry_run_discovery.py
```
Runs real discovery against the live CBIC/GST Council/India Code sites and
prints a per-source, per-category count summary — no files written, no
database touched. Good first real-world check: confirms the sites are
reachable and their page structure hasn't drifted, without risking anything.

### 3. Native CLI (terminal) — the most direct way to watch it work

Activate using whichever Path B/C command matched your shell in "Getting
started," then (identical in PowerShell/cmd/bash once the venv is active):
```
python -m gst_agent.main --stats                   # see current state (empty on a fresh clone)
python -m gst_agent.main --once                    # run a real pass -- prints {"run_id": N, "new_documents_downloaded": N}
python -m gst_agent.main --stats                   # confirm the numbers changed as expected
python -m gst_agent.main --retry-failed             # if --stats showed any "failed" documents
```
Run it in your own terminal (not detached/backgrounded) to see the live
log output scroll by as it happens — the clearest way to watch discovery,
downloads, OCR, and classification decisions in real time. After a run,
open a few files in `data/downloads/<Category>/` and check they actually
match their category.

### 4. Web UI — click-through verification

```
gst-agent-ui                                        # after setup.sh/setup.ps1, or:
python -m gst_agent.web                             # after the manual venv path
```
(Docker equivalent is in "Web UI" above — same three-shell `-v` syntax as
"Getting started" Path A.) Open **http://127.0.0.1:5000**. Click "Run now"
(confirms first — this is a real pass against real government sites);
once running you can open a *second* browser tab to the Logs page and it
stays responsive throughout (the server is multi-threaded specifically so
a long run doesn't block everything else). Use the Documents page to
filter by category/status and open a few real PDFs to sanity-check
classification by eye.

### 5. Docker — the "does this work from a clean environment" check

Same build/run commands as "Getting started" Path A (all three shells
verified there); add these two variants once you've confirmed `--stats`
works:
```powershell
docker run --rm -v "${PWD}\data:/app/data" gst-law-docs-agent                              # PowerShell: --once
docker run --rm -p 5000:5000 -v "${PWD}\data:/app/data" gst-law-docs-agent gst_agent.web    # PowerShell: web UI
```
```bash
docker run --rm -v "$(pwd)/data:/app/data" gst-law-docs-agent                              # bash: --once
docker run --rm -p 5000:5000 -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.web    # bash: web UI
```
See the Windows + Git Bash gotcha in "Getting started" if `-v
"$(pwd)/data:..."` reports 0 documents from Git Bash specifically. This
reads/writes the *same* `data/` folder as the native path — running
native and Docker against the same project directory is expected to (and
does) produce identical, consistent results.

### 6. The daily schedule — core requirement, not an extra

Running automatically once every 24 hours (Windows Task Scheduler, or
`cron` on Linux/macOS) is one of this project's core requirements, done in
Step 4 of "Getting started" — this step is about *verifying* that already-
registered schedule actually fires and does the right thing, not setting
it up for the first time.

```powershell
.\install_scheduler.ps1                        # if you haven't already done Step 4
Get-ScheduledTask -TaskName "GST Law Document Agent" | Select-Object State
```
Works the same regardless of which "Getting started" path you used — it
auto-detects a native `.venv` and uses it if present, otherwise falls back
to the built Docker image (see "Running on a schedule" for details). To
confirm it fires without waiting for the scheduled time:
```powershell
Start-ScheduledTask -TaskName "GST Law Document Agent"
```

Windows Task Scheduler doesn't make it obvious a task actually *ran*
successfully without checking:
```powershell
(Get-ScheduledTaskInfo -TaskName "GST Law Document Agent") | Select-Object LastRunTime, LastTaskResult, NextRunTime
```
`LastTaskResult` of `0` means success. Also check `data/logs/cron.log`
(wrapper script output, timestamped per run) and `data/logs/gst_agent.log` (the app's own log)
for that run's timestamp. Remove it with `.\uninstall_scheduler.ps1`.

### 7. LLM fallback specifically

With `ENABLE_LLM_FALLBACK=true` and at least one of `GEMINI_API_KEY` /
`GROQ_API_KEY` set in `.env`, the easiest way to force the fallback to
actually fire (rather than waiting for a document the rule-based pass
can't confidently place) is a quick one-off script:
```bash
python -c "from gst_agent.llm_providers import get_ordered_providers; \
p = [p for p in get_ordered_providers() if p.is_configured()][0]; \
print(p.classify(title='Unusual GST Advisory XYZ', text='some unrecognized document text', active_categories=['Act','Rule','Notification','Circular','Order']))"
```
A working call returns an `LLMClassification(...)` with either a real
`matched_category` or a `proposed_category` — not an exception.

## OCR setup

Extraction works out of the box for the (large majority of) digitally
generated PDFs. For genuinely scanned pages, install the Tesseract OCR
engine separately (it's a system binary, not a Python package):

- Windows: https://github.com/UB-Mannheim/tesseract/wiki, then set
  `TESSERACT_CMD` in `.env` if it isn't on `PATH`.
- macOS: `brew install tesseract`
- Linux: `apt install tesseract-ocr` (or your distro's equivalent)

Without it, OCR failures are caught and logged per-page rather than
crashing the run — affected pages simply extract no text, which is safe
degradation.

## CI/CD

**CI (run the test suite automatically on push/PR): recommended.** The repo
already lives on GitHub, so GitHub Actions is the natural, zero-extra-setup
choice — free for the test suite's scope (a few seconds per run), no
account linking beyond what already exists. A minimal workflow just runs
`pytest -q` on every push/PR.

**CD (run the actual daily scrape from the cloud instead of locally): not
recommended for this project's architecture.** GitHub Actions runners are
ephemeral -- a fresh, empty filesystem every run -- but this project's
restart-safety and dedup depend on `data/state.db` and `data/downloads/`
persisting *locally* between runs. Making that work from Actions would mean
either committing a growing SQLite file and PDFs back into git history (bad
practice) or standing up real external persistent storage (blob storage, a
mounted disk) -- infrastructure scope beyond what this assignment calls
for. The already-working Windows Task Scheduler (see "Running on a
schedule") is the right mechanism for the actual daily run; Docker on any
always-on host is the natural next step if this ever needed to run
somewhere other than this machine, using the same volume-mount pattern
already documented above.

**Why not Azure DevOps Pipelines:** it would require connecting an Azure
DevOps organization to this GitHub repo for no benefit GitHub Actions
doesn't already provide for free, given the code already lives on GitHub.
Azure becomes the right call specifically if the daily *scrape itself*
ever needs to run somewhere always-on in the cloud (a small VM or
Container Instance with a persistent disk, running the same Docker image)
-- that's a real infrastructure decision, not a CI/CD one, and not
something this project currently needs.

## Safety / compliance notes

- Only publicly accessible pages and documents are accessed.
- robots.txt is checked before every single request (including PDFs);
  disallowed requests raise and are never bypassed.
- A fixed delay is enforced between requests to every domain.
- The User-Agent identifies the project and includes a contact email
  (`USER_AGENT_CONTACT` in `.env`).
- No CAPTCHA, authentication, or anti-bot mechanism is ever bypassed —
  where a site's own access policy (not robots.txt) blocks an honest
  User-Agent (see `indiacode.py`), that source stays disabled rather than
  spoofing a browser to get through.
- Every downloaded document's original source URL is stored permanently.
