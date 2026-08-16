# GST Law Document Collection & Classification Agent

An automated agent that discovers, downloads, extracts, classifies, and
files publicly available Indian GST law documents from official government
sources, once a day, with a hard cap of 100 new documents per run.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt

python -m gst_agent.main --once          # run one pass now
python -m gst_agent.main --stats         # see current state
```

Results land in `data/downloads/<Category>/`, state lives in
`data/state.db` (SQLite), logs in `data/logs/gst_agent.log`.

Copy `.env.example` to `.env` to change any default (all settings have
sensible built-in defaults, so this is optional).

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
  llm_client.py   Thin Anthropic API wrapper (only imported if the fallback is enabled)
  pipeline.py     Orchestrates discover -> download -> extract -> classify -> file
  main.py         CLI entrypoint
  sources/
    base.py           DocumentSource interface
    cbic.py            cbic-gst.gov.in
    gstcouncil.py       gstcouncil.gov.in
    indiacode.py        indiacode.nic.in (implemented, disabled by default -- see below)
```

Adding a new official source later means writing one class in `sources/`
and registering it in `sources/__init__.py` — nothing else changes.

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

**Why an LLM at all, and which one.** Rule-based classification alone can't
handle a document type nobody anticipated when the category list was
written; an LLM can read the actual content and reason about what kind of
document it is. It's scoped narrowly (fallback only, short excerpt, low
effort, structured JSON output) to keep it cheap and to keep classification
mostly deterministic. Model is configurable via `LLM_MODEL`
(`.env.example`); it defaults to the current Claude Opus model.

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

**Windows (Task Scheduler):**

```powershell
schtasks /create /tn "GST Law Document Agent" /sc daily /st 03:00 `
  /tr "D:\path\to\.venv\Scripts\python.exe -m gst_agent.main --once" `
  /sd (Get-Date).ToString('MM/dd/yyyy')
```
Set "Start in" to the project's root directory in the task's properties
(or use `/tr "cmd /c cd /d D:\path\to\project && .venv\Scripts\python.exe -m gst_agent.main --once"`),
so relative paths resolve correctly.

**Linux/macOS (cron):**

```
0 3 * * * cd /path/to/project && .venv/bin/python -m gst_agent.main --once >> data/logs/cron.log 2>&1
```

**Manual / demo convenience (any OS, no scheduler setup):**

```bash
python -m gst_agent.main --loop --interval-hours 24
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
| `MAX_NEW_DOCS_PER_RUN` | `100` | Cap on **new** documents downloaded in a single run |
| `ENABLED_SOURCES` | `cbic,gstcouncil` | Comma-separated source modules to run |
| `ENABLE_LLM_FALLBACK` | `false` | Turn on the LLM classification fallback (needs `ANTHROPIC_API_KEY`) |
| `CATEGORY_PROMOTION_THRESHOLD` | `3` | Recurrences needed before an LLM-proposed category becomes real |
| `OCR_MIN_CHARS_PER_PAGE` | `20` | Below this, a page is treated as scanned and OCR'd |

## Testing

```bash
pytest -q
```

Unit tests cover the DB layer (dedup, lifecycle, restart-safety, category
promotion, schema migration), each source's HTML parsing (against real
page structure captured from the live sites), the extractor (real
minimal PDFs, OCR path mocked), the classifier (rule-based patterns + LLM
fallback with a mocked client), and the pipeline (discovery, the 100-doc
cap, cross-run backlog resumption, per-document failure isolation, category
promotion) — all against mocked network/LLM calls, so the suite runs
offline and fast.

`scripts_dry_run_discovery.py` is a manual, non-pytest smoke test that runs
real discovery (no downloads) against the live sites and prints a summary —
useful for confirming a source's page structure hasn't changed:

```bash
python scripts_dry_run_discovery.py
```

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
