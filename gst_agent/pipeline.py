"""End-to-end pipeline: discover -> dedupe -> download -> extract -> classify
-> file into a category folder -> mark done.

A single run downloads at most settings.max_new_docs_per_run NEW documents
(the 100-per-run cap from the assignment). A failure at any stage for any one
document is recorded against that document and the run continues with the
next one -- one bad PDF never aborts the batch. Every state change is
committed immediately via gst_agent.db, so a killed process picks up exactly
where it left off on the next run (nothing is only held in memory).
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
from pathlib import Path

from gst_agent import db
from gst_agent.classifier import classify_rule_based, classify_with_llm
from gst_agent.config import CATEGORIES, settings
from gst_agent.extractor import extract_text
from gst_agent.http_client import RobotsDisallowed, session
from gst_agent.sources import get_enabled_sources

logger = logging.getLogger("gst_agent.pipeline")


def get_active_categories(conn: sqlite3.Connection) -> list[str]:
    """Built-in categories plus any that have since been promoted from
    recurring LLM proposals (see _promote_recurring_categories)."""
    return [*CATEGORIES, *db.get_promoted_categories(conn)]


def _category_dir(category: str) -> Path:
    return settings.downloads_dir / category


def to_relative_download_path(path: Path) -> str:
    """documents.local_path is stored relative to settings.downloads_dir, not
    as an absolute path -- an absolute path baked in by one environment
    (e.g. a native Windows run) is meaningless read back from another (e.g.
    the Docker image, or downloads_dir simply moving) even though the
    underlying data/ folder is the same. Storing a relative path keeps the
    database portable across however this project is run.

    Stored with forward slashes (.as_posix()) specifically, not str(), which
    would use the writer's native separator -- a path written with Windows
    backslashes is not a path at all to a POSIX Path (backslash isn't a
    separator there), so a native Windows run's rows must still resolve
    correctly when later read inside the Linux Docker image."""
    return path.relative_to(settings.downloads_dir).as_posix()


def to_absolute_download_path(value: str) -> Path:
    """Inverse of to_relative_download_path -- also accepts an absolute path
    unchanged, so rows written before this change (already absolute) keep
    resolving correctly without a data migration."""
    path = Path(value)
    return path if path.is_absolute() else settings.downloads_dir / path


def _safe_filename(doc_url: str, doc_id: int) -> str:
    name = doc_url.rsplit("/", 1)[-1] or f"document-{doc_id}.pdf"
    name = "".join(c for c in name if c not in '\\/:*?"<>|')
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    # Prefix with the DB id so two sources that happen to serve identically
    # named files (a common CBIC pattern) never collide on disk.
    return f"{doc_id}_{name}"


def _discover_new_documents(conn: sqlite3.Connection, run_id: int) -> int:
    """Record every not-yet-seen document from each enabled source. Returns
    how many were newly discovered. Does NOT download anything -- see
    db.get_pending_documents(), which is what actually drives downloads, so
    that documents discovered here but left over when a previous run hit the
    max_new_docs_per_run cap are picked up too, not just brand-new URLs."""
    discovered_count = 0
    for source in get_enabled_sources(settings.enabled_sources):
        try:
            docs = source.discover()
        except Exception as exc:
            logger.warning("Source %s failed to discover documents: %s", source.name, exc)
            continue
        for doc in docs:
            if db.is_known_url(conn, doc.doc_url):
                continue
            db.insert_discovered(
                conn,
                source=doc.source,
                source_page=doc.source_page,
                doc_url=doc.doc_url,
                title=doc.title,
                doc_number=doc.doc_number,
                doc_date=doc.doc_date,
                source_hint_category=doc.source_hint_category,
                run_id=run_id,
            )
            discovered_count += 1
    return discovered_count


def _download(conn: sqlite3.Connection, doc_id: int, doc_url: str) -> Path | None:
    """Download and hash a document, staging it under "Other" until
    classification decides its real category folder. Returns None (after
    recording the reason) if the content duplicates an already-known file."""
    response = session.get(doc_url)
    content = response.content
    file_hash = hashlib.sha256(content).hexdigest()
    if db.is_known_hash(conn, file_hash):
        db.record_failure(
            conn, doc_id, stage="download",
            reason=f"Duplicate content of an already-downloaded document (sha256={file_hash})",
        )
        return None

    staging_dir = settings.downloads_dir / "Other"
    staging_dir.mkdir(parents=True, exist_ok=True)
    local_path = staging_dir / _safe_filename(doc_url, doc_id)
    local_path.write_bytes(content)
    db.mark_downloaded(
        conn, doc_id, local_path=to_relative_download_path(local_path), file_hash=file_hash
    )
    return local_path


def _process_document(
    conn: sqlite3.Connection, row: sqlite3.Row, active_categories: list[str]
) -> None:
    """Extract, classify, and file a single already-downloaded document."""
    doc_id = row["id"]
    local_path = to_absolute_download_path(row["local_path"])

    try:
        extraction = extract_text(local_path)
    except Exception as exc:
        logger.warning("Extraction failed for document %s: %s", doc_id, exc)
        db.record_failure(conn, doc_id, stage="extract", reason=str(exc))
        return
    db.mark_extracted(conn, doc_id, ocr_used=extraction.ocr_used)

    proposed_category: str | None = None
    try:
        category, confident = classify_rule_based(
            text=extraction.text,
            title=row["title"] or "",
            source_hint_category=row["source_hint_category"] or "Other",
        )
        if not confident:
            llm_result = classify_with_llm(
                text=extraction.text, title=row["title"] or "", active_categories=active_categories
            )
            if llm_result is not None:
                if llm_result.matched_category:
                    category = llm_result.matched_category
                elif llm_result.proposed_category:
                    proposed_category = llm_result.proposed_category
    except Exception as exc:
        logger.warning("Classification failed for document %s: %s", doc_id, exc)
        db.record_failure(conn, doc_id, stage="classify", reason=str(exc))
        return

    db.mark_classified(conn, doc_id, category=category)
    if proposed_category:
        db.record_proposed_category(conn, doc_id, proposed_category=proposed_category)

    try:
        dest_dir = _category_dir(category)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / local_path.name
        if local_path != dest_path:
            shutil.move(str(local_path), str(dest_path))
        db.mark_done(conn, doc_id, local_path=to_relative_download_path(dest_path))
    except OSError as exc:
        logger.warning("Filing failed for document %s: %s", doc_id, exc)
        db.record_failure(conn, doc_id, stage="file", reason=str(exc))


def _promote_recurring_categories(conn: sqlite3.Connection) -> None:
    """A proposed category graduates into a real, first-class folder once it
    has recurred across enough distinct documents (Settings.
    category_promotion_threshold). Promotion also retroactively sweeps in
    every document already parked under a provisional category that matches,
    so they don't stay stranded in "Other" once the category is real."""
    already_promoted = db.get_promoted_categories(conn)
    promotable = db.get_promotable_categories(
        conn, threshold=settings.category_promotion_threshold, already_promoted=already_promoted
    )
    for name, count in promotable:
        logger.info(
            "Promoting recurring proposed category %r to an active category "
            "(seen on %d documents)", name, count,
        )
        db.promote_category(conn, name, occurrence_count=count)

        dest_dir = _category_dir(name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        for doc_row in db.get_documents_with_proposed_category(conn, name):
            old_path = to_absolute_download_path(doc_row["local_path"]) if doc_row["local_path"] else None
            if old_path is None or not old_path.exists():
                continue
            new_path = dest_dir / old_path.name
            try:
                shutil.move(str(old_path), str(new_path))
                db.reclassify_document(
                    conn, doc_row["id"], category=name, local_path=to_relative_download_path(new_path)
                )
            except OSError as exc:
                logger.warning(
                    "Could not move document %s while promoting %r: %s", doc_row["id"], name, exc
                )


def run_once(conn: sqlite3.Connection, *, max_new_docs: int | None = None) -> dict:
    """max_new_docs overrides settings.max_new_docs_per_run for this call
    only -- used by the web UI's "Run now" button to cap a manually
    triggered run much lower (see Settings.web_ui_max_new_docs_per_run)
    than the real scheduled run, so clicking it repeatedly stays fast and
    doesn't burn through the day's intended download budget. Discovery
    itself is never capped either way -- it's cheap (just DB rows), and a
    larger backlog only means future runs (scheduled or manual) have more
    to work through, never a problem to leave discovered."""
    if max_new_docs is None:
        max_new_docs = settings.max_new_docs_per_run

    run_id = db.start_run(conn)
    new_downloaded = 0
    try:
        discovered_count = _discover_new_documents(conn, run_id)
        logger.info("Discovered %d new document(s) this run", discovered_count)

        # Pull the whole backlog of not-yet-downloaded documents, not just
        # this run's new ones -- anything left over from a prior run that
        # hit the cap before reaching it belongs in this run's queue too.
        pending = db.get_pending_documents(conn)
        for row in pending:
            if new_downloaded >= max_new_docs:
                logger.info(
                    "Reached max_new_docs (%d) -- stopping downloads for this run",
                    max_new_docs,
                )
                break

            doc_id = row["id"]
            doc_url = row["doc_url"]
            try:
                local_path = _download(conn, doc_id, doc_url)
            except RobotsDisallowed as exc:
                db.record_failure(conn, doc_id, stage="download", reason=str(exc))
                continue
            except Exception as exc:
                logger.warning("Download failed for %s: %s", doc_url, exc)
                db.record_failure(conn, doc_id, stage="download", reason=str(exc))
                continue
            if local_path is None:
                continue  # duplicate content, already recorded

            new_downloaded += 1
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
            active_categories = get_active_categories(conn)
            _process_document(conn, row, active_categories)

        _promote_recurring_categories(conn)
        db.finish_run(conn, run_id, new_documents_downloaded=new_downloaded, status="completed")
    except Exception as exc:
        logger.exception("Run %s failed unexpectedly", run_id)
        db.finish_run(
            conn, run_id, new_documents_downloaded=new_downloaded, status="failed", notes=str(exc)
        )
        raise

    return {"run_id": run_id, "new_documents_downloaded": new_downloaded}


def retry_failed(conn: sqlite3.Connection) -> dict:
    """Re-attempt every document currently in status='failed' that hasn't
    already hit settings.max_retry_attempts. Documents that failed at the
    download stage are re-downloaded; documents that failed later
    (extract/classify/file) already have a local file and just re-enter the
    pipeline from where they stopped.

    Documents at or beyond max_retry_attempts are skipped -- a permanently
    broken URL (a dead link on the source's own listing page, for example)
    will never succeed no matter how many times it's retried, so retrying
    it forever on every --retry-failed call would only waste real time
    without ever making progress."""
    failed = db.get_retryable_failed_documents(conn, max_attempts=settings.max_retry_attempts)
    skipped_permanent = db.get_permanently_failed_count(
        conn, max_attempts=settings.max_retry_attempts
    )
    if skipped_permanent:
        logger.info(
            "Skipping %d document(s) that have already failed %d+ times "
            "(considered permanently broken, not retried automatically)",
            skipped_permanent, settings.max_retry_attempts,
        )
    active_categories = get_active_categories(conn)
    retried = 0

    for row in failed:
        doc_id = row["id"]
        if row["failure_stage"] == "download":
            try:
                local_path = _download(conn, doc_id, row["doc_url"])
            except Exception as exc:
                logger.warning("Retry download failed for document %s: %s", doc_id, exc)
                db.record_failure(conn, doc_id, stage="download", reason=str(exc))
                continue
            if local_path is None:
                continue
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()

        _process_document(conn, row, active_categories)
        retried += 1

    return {"retried": retried, "skipped_permanent": skipped_permanent}
