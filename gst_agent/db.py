"""SQLite-backed state store.

This is what makes the agent restart-safe and duplicate-free across runs:
every discovered document is recorded here, and every state change (download,
extraction, classification, failure) is committed immediately. If the process
is killed mid-run, the next run simply re-reads this database and picks up
where it left off -- nothing is held only in memory.

Dedup works on two independent keys:
  - doc_url: the exact source URL (catches "we've already seen this link").
  - file_hash: a SHA-256 of the downloaded bytes (catches the same PDF being
    re-published under a different URL, e.g. a corrigendum re-upload).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    new_documents_downloaded INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_page TEXT,
    doc_url TEXT NOT NULL UNIQUE,
    title TEXT,
    doc_number TEXT,
    doc_date TEXT,
    source_hint_category TEXT,
    category TEXT,
    proposed_category TEXT,
    file_hash TEXT,
    local_path TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    failure_stage TEXT,
    failure_reason TEXT,
    ocr_used INTEGER NOT NULL DEFAULT 0,
    run_id INTEGER,
    discovered_at TEXT NOT NULL,
    downloaded_at TEXT,
    processed_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents(file_hash);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
-- idx_documents_proposed_category is created in init_db() below, *after* the
-- proposed_category migration guard -- an older database's `documents` table
-- won't have that column yet at the time this script runs, and an index
-- statement referencing a nonexistent column fails the whole script.

-- Categories the LLM fallback classifier has proposed and that have since
-- recurred often enough (see Settings.category_promotion_threshold) to be
-- promoted into a real, first-class category with its own download folder.
CREATE TABLE IF NOT EXISTS promoted_categories (
    name TEXT PRIMARY KEY,
    promoted_at TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL
);
"""

# Valid lifecycle values for documents.status. Enforced in application code
# (not a DB CHECK constraint) so it stays easy to extend in one place.
STATUS_DISCOVERED = "discovered"
STATUS_DOWNLOADED = "downloaded"
STATUS_EXTRACTED = "extracted"
STATUS_CLASSIFIED = "classified"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL = readers don't block the writer and vice versa; also survives a
    # hard kill mid-write better than the default rollback journal.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "documents", "proposed_category", "TEXT")
    with conn:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_proposed_category "
            "ON documents(proposed_category)"
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """Add a column to an existing table if it isn't there yet.

    CREATE TABLE IF NOT EXISTS only helps for tables that don't exist yet --
    a database created by an older version of this project already has
    `documents` without newer columns, and SQLite has no ADD COLUMN IF NOT
    EXISTS. This keeps old state.db files usable across upgrades instead of
    requiring users to delete their history.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        with conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


# --- runs -------------------------------------------------------------


def start_run(conn: sqlite3.Connection) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            (_now(),),
        )
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    new_documents_downloaded: int,
    status: str = "completed",
    notes: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE runs
            SET finished_at = ?, new_documents_downloaded = ?, status = ?, notes = ?
            WHERE id = ?
            """,
            (_now(), new_documents_downloaded, status, notes, run_id),
        )


# --- documents: discovery / dedupe -------------------------------------


def is_known_url(conn: sqlite3.Connection, doc_url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM documents WHERE doc_url = ? LIMIT 1", (doc_url,)
    ).fetchone()
    return row is not None


def is_known_hash(conn: sqlite3.Connection, file_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM documents WHERE file_hash = ? LIMIT 1", (file_hash,)
    ).fetchone()
    return row is not None


def insert_discovered(
    conn: sqlite3.Connection,
    *,
    source: str,
    source_page: str,
    doc_url: str,
    title: str,
    doc_number: str | None,
    doc_date: str | None,
    source_hint_category: str,
    run_id: int,
) -> int:
    """Record a newly discovered document. Caller must already have checked
    is_known_url() -- this will raise if doc_url is a duplicate, since a
    silent INSERT OR IGNORE would hide bugs in the caller's dedupe logic."""
    with conn:
        cur = conn.execute(
            """
            INSERT INTO documents (
                source, source_page, doc_url, title, doc_number, doc_date,
                source_hint_category, status, run_id, discovered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                source_page,
                doc_url,
                title,
                doc_number,
                doc_date,
                source_hint_category,
                STATUS_DISCOVERED,
                run_id,
                _now(),
            ),
        )
    return cur.lastrowid


# --- documents: state transitions ---------------------------------------


def mark_downloaded(
    conn: sqlite3.Connection, doc_id: int, *, local_path: str, file_hash: str
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE documents
            SET status = ?, local_path = ?, file_hash = ?, downloaded_at = ?
            WHERE id = ?
            """,
            (STATUS_DOWNLOADED, local_path, file_hash, _now(), doc_id),
        )


def mark_extracted(conn: sqlite3.Connection, doc_id: int, *, ocr_used: bool) -> None:
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, ocr_used = ? WHERE id = ?",
            (STATUS_EXTRACTED, int(ocr_used), doc_id),
        )


def mark_classified(conn: sqlite3.Connection, doc_id: int, *, category: str) -> None:
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, category = ? WHERE id = ?",
            (STATUS_CLASSIFIED, category, doc_id),
        )


def mark_done(conn: sqlite3.Connection, doc_id: int, *, local_path: str) -> None:
    with conn:
        conn.execute(
            "UPDATE documents SET status = ?, local_path = ?, processed_at = ? WHERE id = ?",
            (STATUS_DONE, local_path, _now(), doc_id),
        )


def record_failure(
    conn: sqlite3.Connection, doc_id: int, *, stage: str, reason: str
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE documents
            SET status = ?, failure_stage = ?, failure_reason = ?, processed_at = ?
            WHERE id = ?
            """,
            (STATUS_FAILED, stage, reason[:2000], _now(), doc_id),
        )


def reclassify_document(
    conn: sqlite3.Connection, doc_id: int, *, category: str, local_path: str
) -> None:
    """Retroactively move a document into a category that was just promoted
    (see promote_category). Distinct from mark_classified/mark_done: this
    only fires once, after the fact, for documents that were already filed
    under "Other" while their proposed category was still unconfirmed."""
    with conn:
        conn.execute(
            "UPDATE documents SET category = ?, local_path = ? WHERE id = ?",
            (category, local_path, doc_id),
        )


# --- dynamic category discovery (LLM fallback) --------------------------


def record_proposed_category(
    conn: sqlite3.Connection, doc_id: int, *, proposed_category: str
) -> None:
    with conn:
        conn.execute(
            "UPDATE documents SET proposed_category = ? WHERE id = ?",
            (proposed_category, doc_id),
        )


def get_promotable_categories(
    conn: sqlite3.Connection, *, threshold: int, already_promoted: list[str]
) -> list[tuple[str, int]]:
    """Proposed categories that have recurred on >= threshold distinct
    documents and aren't already promoted. Cumulative across the database's
    whole history, not just the current run."""
    query = (
        "SELECT proposed_category, COUNT(*) AS n FROM documents "
        "WHERE proposed_category IS NOT NULL"
    )
    params: list = []
    if already_promoted:
        placeholders = ",".join("?" * len(already_promoted))
        query += f" AND proposed_category NOT IN ({placeholders})"
        params.extend(already_promoted)
    query += " GROUP BY proposed_category HAVING COUNT(*) >= ?"
    params.append(threshold)
    return [(row["proposed_category"], row["n"]) for row in conn.execute(query, params)]


def promote_category(
    conn: sqlite3.Connection, name: str, *, occurrence_count: int
) -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO promoted_categories (name, promoted_at, occurrence_count) "
            "VALUES (?, ?, ?)",
            (name, _now(), occurrence_count),
        )


def get_promoted_categories(conn: sqlite3.Connection) -> list[str]:
    return [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM promoted_categories ORDER BY promoted_at"
        )
    ]


def get_documents_with_proposed_category(
    conn: sqlite3.Connection, name: str
) -> list[sqlite3.Row]:
    """Documents parked under a provisional category (usually "Other") whose
    proposed_category is the one that was just promoted -- these get their
    files moved and their category corrected retroactively."""
    return conn.execute(
        "SELECT * FROM documents WHERE proposed_category = ? AND category != ?",
        (name, name),
    ).fetchall()


# --- reporting ------------------------------------------------------------


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    by_status = dict(
        conn.execute(
            "SELECT status, COUNT(*) FROM documents GROUP BY status"
        ).fetchall()
    )
    by_category = dict(
        conn.execute(
            "SELECT COALESCE(category, '(unclassified)'), COUNT(*) FROM documents GROUP BY 1"
        ).fetchall()
    )
    failed = conn.execute(
        "SELECT id, doc_url, failure_stage, failure_reason FROM documents WHERE status = ?",
        (STATUS_FAILED,),
    ).fetchall()
    return {
        "total_documents": total,
        "by_status": by_status,
        "by_category": by_category,
        "failed": [dict(row) for row in failed],
    }


def get_failed_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM documents WHERE status = ?", (STATUS_FAILED,)
    ).fetchall()


def get_pending_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Documents discovered but never downloaded -- either newly found this
    run, or left over from a previous run that hit the max_new_docs_per_run
    cap before reaching them. Oldest-discovered first, so the queue is fair
    across runs instead of always favoring whatever a source lists first."""
    return conn.execute(
        "SELECT * FROM documents WHERE status = ? ORDER BY discovered_at ASC",
        (STATUS_DISCOVERED,),
    ).fetchall()
