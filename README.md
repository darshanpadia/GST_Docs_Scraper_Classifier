# GST Law Document Collection & Classification Agent

An automated agent that discovers, downloads, extracts, classifies, and
files publicly available Indian GST law documents from official government
sources, once a day, with a hard cap of 100 new documents per run.

## For reviewers: how to run this, easiest first

You don't need any API key to see the core system work — document
discovery, downloading, OCR, and classification are all rule-based and
free by default. An LLM fallback exists for the classifier but is optional
and off unless explicitly enabled (see "LLM fallback specifically" below).

Pick **one** path based on what you have available, roughly easiest first:

1. **Have Docker?** → Section "Quick start," option 1. One `docker build`,
   then one `docker run`. Python, Tesseract OCR, and every dependency are
   already inside the image — nothing else to install.
2. **Have Python 3.10+ but not Docker?** → Section "Quick start," option 2
   (`setup.sh`/`setup.ps1`). One script creates a virtual environment and
   installs everything; OCR needs a separate one-time Tesseract install
   (see "OCR setup") if you want to test scanned-PDF handling specifically
   — the agent runs fine without it either way (OCR failures degrade
   gracefully, they don't crash anything).
3. **Want full manual control, or the above doesn't fit your setup?** →
   Section "Quick start," option 3 (plain `venv` + `pip install`).

Whichever you pick, then go to **"Testing guide"** below for a numbered
walkthrough of every way to verify it's actually working — starting with
the automated test suite (no network, seconds to run) before anything that
touches real government sites.

## Quick start

Three ways to run this, in increasing order of setup effort:

**1. Docker (fewest moving parts — Python and Tesseract OCR both come
pre-installed in the image):**

```bash
docker build -t gst-law-docs-agent .
docker run --rm -v "$(pwd)/data:/app/data" gst-law-docs-agent                        # default: one pass (--once)
docker run --rm -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.main --stats
docker run --rm -p 5000:5000 -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.web  # web UI at http://127.0.0.1:5000
```
The `-v` mount is what makes results/state/logs land in `./data` on your
host and survive between runs — without it, everything is lost when the
container exits.

**Windows path gotcha (verified the hard way):** if you're running these
from Git Bash, `$(pwd)` gets silently mangled by MSYS's path conversion for
any path containing a space (very likely here, e.g. `...\SHVM\...`), and
Docker ends up mounting an empty directory with no error — `--stats` will
report 0 documents even though your real data is untouched on disk. Fix:
either run from **PowerShell** (`-v "${PWD}\data:C:/app/data"` isn't
needed — just `-v "${PWD}\data:/app/data"` works correctly there), or from
Git Bash prefix the command with `MSYS_NO_PATHCONV=1` and use an explicit
path:
```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "D:/path/to/project/data:/app/data" gst-law-docs-agent gst_agent.main --stats
```

**2. One-shot setup script (native venv, no Docker):**

```bash
./setup.sh          # macOS/Linux/WSL
.\setup.ps1          # Windows PowerShell
```
This creates `.venv`, installs the project, and gives you a short `gst-agent`
command:
```bash
gst-agent --once          # run one pass now
gst-agent --stats         # see current state
```
(OCR still needs Tesseract installed separately on this path — see "OCR
setup" below. Docker avoids that step entirely.)

**3. Manual venv (full control, no new files):**

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt

python -m gst_agent.main --once          # run one pass now
python -m gst_agent.main --stats         # see current state
```

All three produce the same result: downloads in
`data/downloads/<Category>/`, state in `data/state.db` (SQLite), logs in
`data/logs/gst_agent.log`.

Copy `.env.example` to `.env` to change any default (all settings have
sensible built-in defaults, so this is optional; not used by the Docker
path unless you also pass `--env-file .env` to `docker run`).

## Web UI

A small local dashboard for operating and inspecting the agent visually,
instead of via the CLI — useful for a reviewer to click through rather than
type commands. It's a thin layer over the same `gst_agent.db`/`gst_agent.pipeline`
the CLI uses; it changes no behavior, it only calls the same functions
`--once` and `--retry-failed` already call.

```bash
gst-agent-ui                              # after setup.sh/setup.ps1, or:
python -m gst_agent.web                   # after the manual venv path
# Docker: docker run -p 5000:5000 -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.web
```
Then open **http://127.0.0.1:5000**.

- **Dashboard** — live counts (total/done/pending/failed), a breakdown by
  category, a "Run now" button (triggers a real pass — confirmed before
  running, since it contacts real government sites), a "Retry failed"
  button, recent run history, and full detail on any failed documents.
  **"Run now" is deliberately capped much lower than a real scheduled
  run** (`WEB_UI_MAX_NEW_DOCS_PER_RUN`, default 2, vs `MAX_NEW_DOCS_PER_RUN`,
  default 100) — it's a "confirm the agent is alive and working" button,
  not a way to do the day's real download work from the browser. Discovery
  itself is never capped either way, so clicking it repeatedly still builds
  up a full backlog for the next real scheduled run to work through.
- **Documents** — every discovered document, filterable by category and
  status, with a link to the original source URL and an "Open PDF" link
  that serves the actual downloaded file straight from disk.
- **Logs** — tails `data/logs/gst_agent.log` so you can see exactly what
  happened during the last run without leaving the browser.

Binds to `127.0.0.1` only and has no authentication — it's a local operator
console for whoever is at the machine, not a service meant to be exposed to
a network. No JS framework, no CSS framework: server-rendered HTML with one
small hand-written stylesheet, kept intentionally simple.

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
`gst_agent/`'s code — all three ways of running the project in "Quick
start" execute the exact same pipeline.

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

**Windows (Task Scheduler):** run `install_scheduler.ps1` once, from
inside the project folder:

```powershell
.\install_scheduler.ps1                        # daily at 10:00 AM by default
.\install_scheduler.ps1 -Time "03:00AM"         # or pick your own time
```
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
72 tests, all against mocked network/LLM calls. Covers: the DB layer
(dedup, lifecycle, restart-safety, category promotion, schema migration),
each source's HTML parsing (against real page structure captured from the
live sites), the extractor (real minimal PDFs, OCR path mocked), the
classifier + all 3 LLM providers (rule-based patterns, provider fallback
chain, hallucinated-category handling), the pipeline (discovery, the
100-doc cap, cross-run backlog resumption, per-document failure isolation,
category promotion), and the web UI (every route via Flask's test client —
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

```bash
python -m venv .venv                              # or: ./setup.sh / .\setup.ps1 (also installs LLM extras)
.venv\Scripts\activate                             # Windows; source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

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

```bash
gst-agent-ui                                        # after setup.sh/setup.ps1, or:
python -m gst_agent.web                             # after the manual venv path
```
Open **http://127.0.0.1:5000**. Click "Run now" (confirms first — this is
a real pass against real government sites); once running you can open a
*second* browser tab to the Logs page and it stays responsive throughout
(the server is multi-threaded specifically so a long run doesn't block
everything else). Use the Documents page to filter by category/status and
open a few real PDFs to sanity-check classification by eye.

### 5. Docker — the "does this work from a clean environment" check

```bash
docker build -t gst-law-docs-agent .
docker run --rm -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.main --stats
docker run --rm -v "$(pwd)/data:/app/data" gst-law-docs-agent                        # --once
docker run --rm -p 5000:5000 -v "$(pwd)/data:/app/data" gst-law-docs-agent gst_agent.web
```
See the Windows path gotcha above if `-v "$(pwd)/data:..."` reports 0
documents from Git Bash. This reads/writes the *same* `data/` folder as the
native path — running native and Docker against the same project directory
is expected to (and does) produce identical, consistent results.

### 6. Verifying the daily schedule actually fires

Windows Task Scheduler doesn't make it obvious a task ran successfully
without checking:
```powershell
Get-ScheduledTask -TaskName "GST Law Document Agent" | Select-Object State
(Get-ScheduledTaskInfo -TaskName "GST Law Document Agent") | Select-Object LastRunTime, LastTaskResult, NextRunTime
```
`LastTaskResult` of `0` means success. Also check `data/logs/cron.log`
(wrapper script output) and `data/logs/gst_agent.log` (the app's own log)
for that run's timestamp.

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
