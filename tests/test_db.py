from pathlib import Path

import pytest

from gst_agent import db


@pytest.fixture
def conn(tmp_path: Path):
    with db.open_db(tmp_path / "test_state.db") as connection:
        yield connection


def _insert_sample(conn, run_id: int, url: str = "https://cbic-gst.gov.in/pdf/sample.pdf"):
    return db.insert_discovered(
        conn,
        source="cbic",
        source_page="https://cbic-gst.gov.in/circulars-cgst.html",
        doc_url=url,
        title="Sample Circular",
        doc_number="1/2024",
        doc_date="2024-01-01",
        source_hint_category="Circular",
        run_id=run_id,
    )


def test_new_db_has_no_documents(conn):
    stats = db.get_stats(conn)
    assert stats["total_documents"] == 0


def test_insert_and_dedupe_by_url(conn):
    run_id = db.start_run(conn)
    url = "https://cbic-gst.gov.in/pdf/sample.pdf"

    assert db.is_known_url(conn, url) is False
    doc_id = _insert_sample(conn, run_id, url)
    assert doc_id is not None
    assert db.is_known_url(conn, url) is True

    # Attempting to insert the same URL again must fail loudly (UNIQUE
    # constraint) rather than silently duplicate -- callers are expected to
    # check is_known_url() first.
    with pytest.raises(Exception):
        _insert_sample(conn, run_id, url)


def test_full_lifecycle_transitions(conn, tmp_path: Path):
    run_id = db.start_run(conn)
    doc_id = _insert_sample(conn, run_id)

    fake_path = str(tmp_path / "Circular" / "sample.pdf")
    db.mark_downloaded(conn, doc_id, local_path=fake_path, file_hash="abc123")
    assert db.is_known_hash(conn, "abc123") is True

    db.mark_extracted(conn, doc_id, ocr_used=False)
    db.mark_classified(conn, doc_id, category="Circular")
    db.mark_done(conn, doc_id, local_path=fake_path)

    stats = db.get_stats(conn)
    assert stats["total_documents"] == 1
    assert stats["by_status"]["done"] == 1
    assert stats["by_category"]["Circular"] == 1

    db.finish_run(conn, run_id, new_documents_downloaded=1)


def test_record_failure_keeps_document_and_continues(conn):
    run_id = db.start_run(conn)
    doc_id = _insert_sample(conn, run_id)

    db.record_failure(conn, doc_id, stage="download", reason="Connection timed out")

    stats = db.get_stats(conn)
    assert stats["by_status"]["failed"] == 1
    assert stats["failed"][0]["failure_stage"] == "download"


def test_restart_safety_reopening_same_db_preserves_state(tmp_path: Path):
    db_path = tmp_path / "restart_test.db"

    with db.open_db(db_path) as conn1:
        run_id = db.start_run(conn1)
        _insert_sample(conn1, run_id)
        db.finish_run(conn1, run_id, new_documents_downloaded=1)

    # Simulate the process restarting: open a fresh connection to the same
    # file and confirm the previously discovered document is still known,
    # which is exactly what prevents re-downloading it.
    with db.open_db(db_path) as conn2:
        assert db.is_known_url(conn2, "https://cbic-gst.gov.in/pdf/sample.pdf") is True
        stats = db.get_stats(conn2)
        assert stats["total_documents"] == 1


def test_old_database_without_proposed_category_column_is_migrated(tmp_path: Path):
    # Simulate a database created by an older version of this project, before
    # proposed_category existed, to prove init_db() upgrades it in place
    # rather than requiring users to delete their history.
    db_path = tmp_path / "legacy.db"
    conn = db.get_connection(db_path)
    conn.executescript(
        """
        CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
            finished_at TEXT, new_documents_downloaded INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running', notes TEXT
        );
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
            source_page TEXT, doc_url TEXT NOT NULL UNIQUE, title TEXT,
            doc_number TEXT, doc_date TEXT, source_hint_category TEXT,
            category TEXT, file_hash TEXT, local_path TEXT,
            status TEXT NOT NULL DEFAULT 'discovered', failure_stage TEXT,
            failure_reason TEXT, ocr_used INTEGER NOT NULL DEFAULT 0,
            run_id INTEGER, discovered_at TEXT NOT NULL, downloaded_at TEXT,
            processed_at TEXT
        );
        """
    )
    conn.close()

    with db.open_db(db_path) as conn:
        run_id = db.start_run(conn)
        doc_id = _insert_sample(conn, run_id)
        # Would raise sqlite3.OperationalError before migration.
        db.record_proposed_category(conn, doc_id, proposed_category="Advisory")
        row = conn.execute("SELECT proposed_category FROM documents WHERE id = ?", (doc_id,)).fetchone()
        assert row["proposed_category"] == "Advisory"

        # Same legacy table also predates failure_count -- must migrate too.
        db.record_failure(conn, doc_id, stage="download", reason="x")
        assert db.get_document(conn, doc_id)["failure_count"] == 1


def test_category_promotion_flow(tmp_path: Path):
    with db.open_db(tmp_path / "state.db") as conn:
        run_id = db.start_run(conn)
        doc_ids = []
        for i in range(3):
            doc_id = _insert_sample(conn, run_id, url=f"https://cbic-gst.gov.in/pdf/sample{i}.pdf")
            db.mark_downloaded(conn, doc_id, local_path=f"/tmp/sample{i}.pdf", file_hash=f"hash{i}")
            db.mark_classified(conn, doc_id, category="Other")
            db.record_proposed_category(conn, doc_id, proposed_category="Advisory")
            doc_ids.append(doc_id)

        # Below the threshold, nothing is promotable yet.
        assert db.get_promotable_categories(conn, threshold=4, already_promoted=[]) == []

        promotable = db.get_promotable_categories(conn, threshold=3, already_promoted=[])
        assert promotable == [("Advisory", 3)]

        db.promote_category(conn, "Advisory", occurrence_count=3)
        assert db.get_promoted_categories(conn) == ["Advisory"]

        # Already-promoted categories are excluded from future promotion scans.
        assert db.get_promotable_categories(conn, threshold=3, already_promoted=["Advisory"]) == []

        docs = db.get_documents_with_proposed_category(conn, "Advisory")
        assert {row["id"] for row in docs} == set(doc_ids)

        db.reclassify_document(conn, doc_ids[0], category="Advisory", local_path="/tmp/moved.pdf")
        moved = db.get_documents_with_proposed_category(conn, "Advisory")
        assert doc_ids[0] not in {row["id"] for row in moved}  # now category == "Advisory", filtered out


def test_get_recent_runs_orders_newest_first_and_respects_limit(conn):
    run_ids = [db.start_run(conn) for _ in range(5)]
    for run_id in run_ids:
        db.finish_run(conn, run_id, new_documents_downloaded=0)

    recent = db.get_recent_runs(conn, limit=3)
    assert [r["id"] for r in recent] == list(reversed(run_ids))[:3]


def test_get_document_returns_row_or_none(conn):
    run_id = db.start_run(conn)
    doc_id = _insert_sample(conn, run_id)

    assert db.get_document(conn, doc_id)["doc_url"] == "https://cbic-gst.gov.in/pdf/sample.pdf"
    assert db.get_document(conn, 999999) is None


def test_get_documents_filters_by_category_and_status_with_pagination(conn):
    run_id = db.start_run(conn)
    for i in range(3):
        doc_id = _insert_sample(conn, run_id, url=f"https://cbic-gst.gov.in/pdf/c{i}.pdf")
        db.mark_downloaded(conn, doc_id, local_path=f"/tmp/c{i}.pdf", file_hash=f"h{i}")
        db.mark_classified(conn, doc_id, category="Circular")
        db.mark_done(conn, doc_id, local_path=f"/tmp/c{i}.pdf")
    other_id = _insert_sample(conn, run_id, url="https://cbic-gst.gov.in/pdf/order.pdf")
    db.record_failure(conn, other_id, stage="download", reason="x")

    circulars, total = db.get_documents(conn, category="Circular", limit=50, offset=0)
    assert total == 3
    assert len(circulars) == 3

    failed, failed_total = db.get_documents(conn, status="failed", limit=50, offset=0)
    assert failed_total == 1
    assert failed[0]["id"] == other_id

    page1, total_all = db.get_documents(conn, limit=2, offset=0)
    page2, _ = db.get_documents(conn, limit=2, offset=2)
    assert total_all == 4
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})


def test_record_failure_increments_failure_count(conn):
    run_id = db.start_run(conn)
    doc_id = _insert_sample(conn, run_id)

    db.record_failure(conn, doc_id, stage="download", reason="attempt 1")
    assert db.get_document(conn, doc_id)["failure_count"] == 1
    db.record_failure(conn, doc_id, stage="download", reason="attempt 2")
    assert db.get_document(conn, doc_id)["failure_count"] == 2


def test_get_retryable_failed_documents_excludes_ones_past_max_attempts(conn):
    run_id = db.start_run(conn)
    still_retryable = _insert_sample(conn, run_id, url="https://cbic-gst.gov.in/pdf/a.pdf")
    permanently_broken = _insert_sample(conn, run_id, url="https://cbic-gst.gov.in/pdf/b.pdf")

    db.record_failure(conn, still_retryable, stage="download", reason="x")  # failure_count=1
    for _ in range(3):
        db.record_failure(conn, permanently_broken, stage="download", reason="x")  # failure_count=3

    retryable = db.get_retryable_failed_documents(conn, max_attempts=3)
    assert {r["id"] for r in retryable} == {still_retryable}
    assert db.get_permanently_failed_count(conn, max_attempts=3) == 1
