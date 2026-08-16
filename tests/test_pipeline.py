"""Pipeline integration tests. Network, PDF extraction, and the LLM fallback
are mocked -- this module tests the orchestration logic (dedupe, the 100-doc
cap, per-document failure isolation, category promotion), not the individual
building blocks, which have their own unit tests (test_extractor.py,
test_classifier.py, test_llm_client.py)."""
from __future__ import annotations

import dataclasses
from pathlib import Path
from unittest.mock import patch

import pytest

from gst_agent import db, pipeline
from gst_agent.config import settings as real_settings
from gst_agent.extractor import ExtractionResult
from gst_agent.models import DiscoveredDoc, LLMClassification


class _FakeSource:
    name = "fake"

    def __init__(self, docs):
        self._docs = docs

    def discover(self):
        return self._docs


class _FakeResponse:
    def __init__(self, content: bytes = b"%PDF-fake-bytes"):
        self.content = content


def _get_by_url(url: str, **kwargs) -> _FakeResponse:
    # Content must differ per URL -- the pipeline dedupes downloads by
    # content hash (catching the same PDF re-published under a different
    # URL), so identical fake bytes across documents would trip that dedup
    # and make these tests fail for the wrong reason.
    return _FakeResponse(content=f"%PDF-fake-bytes-for-{url}".encode())


def _doc(url: str, category_hint: str = "Circular", title: str = "Sample doc") -> DiscoveredDoc:
    return DiscoveredDoc(
        source="fake",
        source_page="https://example.com",
        doc_url=url,
        title=title,
        doc_number=None,
        doc_date=None,
        source_hint_category=category_hint,
    )


def _no_ocr_extraction(_path):
    return ExtractionResult(text="irrelevant extracted text", ocr_used=False, page_count=1)


@pytest.fixture
def conn(tmp_path):
    with db.open_db(tmp_path / "state.db") as connection:
        yield connection


@pytest.fixture
def test_settings(tmp_path):
    # dataclasses.replace() rather than monkeypatching attributes directly --
    # Settings is a frozen dataclass, so in-place mutation isn't possible.
    return dataclasses.replace(real_settings, downloads_dir=tmp_path / "downloads", max_new_docs_per_run=2)


def test_relative_download_path_round_trip(test_settings):
    with patch("gst_agent.pipeline.settings", test_settings):
        absolute = test_settings.downloads_dir / "Circular" / "1_sample.pdf"
        relative = pipeline.to_relative_download_path(absolute)
        # Always forward slashes (.as_posix()), regardless of the writer's
        # OS -- a backslash-separated value wouldn't resolve when later read
        # by a POSIX Path (e.g. inside the Docker image).
        assert relative == "Circular/1_sample.pdf"
        assert pipeline.to_absolute_download_path(relative) == absolute


def test_to_absolute_download_path_still_accepts_legacy_absolute_values(test_settings):
    # Rows written before this project stored local_path relative to
    # downloads_dir -- those already-absolute values must keep resolving
    # correctly without a data migration.
    with patch("gst_agent.pipeline.settings", test_settings):
        legacy_absolute = str(test_settings.downloads_dir / "Circular" / "1_sample.pdf")
        assert pipeline.to_absolute_download_path(legacy_absolute) == Path(legacy_absolute)


def test_run_once_downloads_extracts_classifies_and_files(conn, test_settings):
    docs = [_doc("https://example.com/a.pdf", category_hint="Circular")]
    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=_get_by_url), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
        result = pipeline.run_once(conn)

    assert result["new_documents_downloaded"] == 1
    stats = db.get_stats(conn)
    assert stats["by_status"]["done"] == 1
    assert stats["by_category"]["Circular"] == 1
    filed = list((test_settings.downloads_dir / "Circular").glob("*.pdf"))
    assert len(filed) == 1

    # local_path must be stored RELATIVE to downloads_dir, not as an absolute
    # path -- an absolute path baked in by one environment (e.g. a native
    # Windows run) is meaningless read back from another (e.g. the Docker
    # image mounting the same data/ folder). See pipeline.to_relative_download_path.
    row = conn.execute("SELECT local_path FROM documents").fetchone()
    stored_path = Path(row["local_path"])
    assert not stored_path.is_absolute()
    assert stored_path == Path("Circular") / filed[0].name


def test_run_once_stops_at_max_new_docs_per_run(conn, test_settings):
    docs = [_doc(f"https://example.com/{i}.pdf") for i in range(5)]
    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=_get_by_url), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
        result = pipeline.run_once(conn)

    assert result["new_documents_downloaded"] == test_settings.max_new_docs_per_run
    stats = db.get_stats(conn)
    assert stats["total_documents"] == 5  # all 5 discovered and recorded...
    assert stats["by_status"]["done"] == 2  # ...but only the cap was downloaded and processed


def test_run_once_does_not_redownload_an_already_done_document(conn, test_settings):
    run_id = db.start_run(conn)
    doc_id = db.insert_discovered(
        conn, source="fake", source_page="x", doc_url="https://example.com/dup.pdf",
        title="dup", doc_number=None, doc_date=None, source_hint_category="Circular", run_id=run_id,
    )
    db.mark_downloaded(conn, doc_id, local_path="/tmp/dup.pdf", file_hash="existing-hash")
    db.mark_extracted(conn, doc_id, ocr_used=False)
    db.mark_classified(conn, doc_id, category="Circular")
    db.mark_done(conn, doc_id, local_path="/tmp/dup.pdf")
    db.finish_run(conn, run_id, new_documents_downloaded=1)

    # Source lists the already-done URL again (a stale ticker entry) plus a
    # genuinely new one.
    docs = [_doc("https://example.com/dup.pdf"), _doc("https://example.com/new.pdf")]
    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=_get_by_url), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
        result = pipeline.run_once(conn)

    assert result["new_documents_downloaded"] == 1  # only "new.pdf"
    assert db.get_stats(conn)["total_documents"] == 2  # "dup.pdf" was never re-inserted


def test_run_once_resumes_a_backlog_left_over_by_a_prior_capped_run(conn, test_settings):
    # First run: 3 documents discovered, but the cap (2) only lets 2 download.
    docs = [_doc(f"https://example.com/{i}.pdf") for i in range(3)]
    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=_get_by_url), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
        first = pipeline.run_once(conn)

    assert first["new_documents_downloaded"] == 2
    assert db.get_stats(conn)["by_status"]["discovered"] == 1  # 1 left pending

    # Second run: the source no longer lists anything (e.g. it scrolled off
    # the ticker) -- but the pending document from run 1 must still get
    # downloaded, not be stuck forever.
    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource([])]), \
         patch("gst_agent.pipeline.session.get", side_effect=_get_by_url), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
        second = pipeline.run_once(conn)

    assert second["new_documents_downloaded"] == 1
    stats = db.get_stats(conn)
    assert stats["by_status"]["done"] == 3
    assert stats["by_status"].get("discovered", 0) == 0


def test_run_once_isolates_a_single_document_failure(conn, test_settings):
    docs = [_doc("https://example.com/bad.pdf"), _doc("https://example.com/good.pdf")]

    def flaky_get(url, **kwargs):
        if "bad" in url:
            raise ConnectionError("simulated network failure")
        return _FakeResponse()

    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=flaky_get), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
        result = pipeline.run_once(conn)

    # The failure on "bad.pdf" must not abort the run -- "good.pdf" still
    # gets downloaded and counted.
    assert result["new_documents_downloaded"] == 1
    stats = db.get_stats(conn)
    assert stats["by_status"]["failed"] == 1
    assert stats["by_status"]["done"] == 1


def test_category_promotion_after_recurring_llm_suggestions(conn, test_settings):
    test_settings = dataclasses.replace(
        test_settings, max_new_docs_per_run=10, category_promotion_threshold=3, enable_llm_fallback=True
    )
    docs = [
        _doc(f"https://example.com/{i}.pdf", category_hint="Other", title="An unusual advisory document")
        for i in range(3)
    ]

    with patch("gst_agent.pipeline.settings", test_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=_get_by_url), \
         patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction), \
         patch("gst_agent.classifier.settings", test_settings), \
         patch("gst_agent.llm_client.classify_document",
               return_value=LLMClassification(matched_category=None, proposed_category="Advisory")):
        result = pipeline.run_once(conn)

    assert result["new_documents_downloaded"] == 3
    assert db.get_promoted_categories(conn) == ["Advisory"]
    filed = list((test_settings.downloads_dir / "Advisory").glob("*.pdf"))
    assert len(filed) == 3
    stats = db.get_stats(conn)
    assert stats["by_category"]["Advisory"] == 3


def test_retry_failed_reprocesses_a_download_failure(conn, test_settings):
    with patch("gst_agent.pipeline.settings", test_settings):
        run_id = db.start_run(conn)
        doc_id = db.insert_discovered(
            conn, source="fake", source_page="x", doc_url="https://example.com/retry.pdf",
            title="retry me", doc_number=None, doc_date=None, source_hint_category="Circular", run_id=run_id,
        )
        db.record_failure(conn, doc_id, stage="download", reason="simulated earlier failure")
        db.finish_run(conn, run_id, new_documents_downloaded=0, status="completed")

        with patch("gst_agent.pipeline.session.get", return_value=_FakeResponse()), \
             patch("gst_agent.pipeline.extract_text", side_effect=_no_ocr_extraction):
            result = pipeline.retry_failed(conn)

    assert result["retried"] == 1
    stats = db.get_stats(conn)
    assert stats["by_status"]["done"] == 1
    assert stats["by_status"].get("failed", 0) == 0
