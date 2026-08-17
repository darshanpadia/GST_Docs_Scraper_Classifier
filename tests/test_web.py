"""Web UI route tests via Flask's test client -- no real server/port needed.
gst_agent.web reads settings.db_path/log_dir at request time (inside each
route, not at import time), so pointing those at a tmp_path per test is
enough to isolate every test from real project state."""
from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from gst_agent import db
from gst_agent import web as web_module
from gst_agent.config import settings as real_settings
from gst_agent.models import DiscoveredDoc


@pytest.fixture
def test_settings(tmp_path):
    return dataclasses.replace(
        real_settings,
        db_path=tmp_path / "state.db",
        downloads_dir=tmp_path / "downloads",
        log_dir=tmp_path / "logs",
    )


@pytest.fixture
def client(test_settings):
    web_module.app.config["TESTING"] = True
    with patch("gst_agent.web.settings", test_settings), \
         patch("gst_agent.pipeline.settings", test_settings):
        with web_module.app.test_client() as c:
            yield c


def _seed_one_document(test_settings, *, status="done", category="Circular"):
    with db.open_db(test_settings.db_path) as conn:
        run_id = db.start_run(conn)
        doc_id = db.insert_discovered(
            conn, source="cbic", source_page="https://example.com", doc_url="https://example.com/a.pdf",
            title="Sample Circular", doc_number="1/2024", doc_date="2024-01-01",
            source_hint_category=category, run_id=run_id,
        )
        if status in ("done", "downloaded", "failed"):
            path = test_settings.downloads_dir / category
            path.mkdir(parents=True, exist_ok=True)
            file_path = path / "a.pdf"
            file_path.write_bytes(b"%PDF-fake")
            db.mark_downloaded(conn, doc_id, local_path=str(file_path), file_hash="abc")
            if status == "done":
                db.mark_extracted(conn, doc_id, ocr_used=False)
                db.mark_classified(conn, doc_id, category=category)
                db.mark_done(conn, doc_id, local_path=str(file_path))
            elif status == "failed":
                db.record_failure(conn, doc_id, stage="classify", reason="simulated failure")
        db.finish_run(conn, run_id, new_documents_downloaded=1)
    return doc_id


def test_dashboard_loads_with_no_data(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Dashboard" in response.data
    assert b"No documents yet" in response.data


def test_dashboard_shows_stats_after_seeding(client, test_settings):
    _seed_one_document(test_settings, status="done")
    response = client.get("/")
    assert response.status_code == 200
    assert b"Circular" in response.data


def test_run_now_triggers_pipeline_and_redirects(client):
    with patch("gst_agent.pipeline.get_enabled_sources", return_value=[]):
        response = client.post("/run", follow_redirects=True)
    assert response.status_code == 200
    assert b"Run #" in response.data
    assert b"complete" in response.data


class _FakeSource:
    name = "fake"

    def __init__(self, docs):
        self._docs = docs

    def discover(self):
        return self._docs


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content


def test_run_now_uses_the_web_ui_cap_not_the_real_scheduled_cap(client, test_settings):
    # A real scheduled run would use max_new_docs_per_run (set high here, as
    # it is in production); the button must still only download
    # web_ui_max_new_docs_per_run of them -- proving gst_agent.web.run_now
    # actually passes its own override rather than falling through to the
    # much larger default.
    docs = [
        DiscoveredDoc(
            source="fake", source_page="https://example.com", doc_url=f"https://example.com/{i}.pdf",
            title=f"doc {i}", doc_number=None, doc_date=None, source_hint_category="Circular",
        )
        for i in range(5)
    ]
    capped_settings = dataclasses.replace(
        test_settings, max_new_docs_per_run=100, web_ui_max_new_docs_per_run=2
    )

    with patch("gst_agent.web.settings", capped_settings), \
         patch("gst_agent.pipeline.settings", capped_settings), \
         patch("gst_agent.pipeline.get_enabled_sources", return_value=[_FakeSource(docs)]), \
         patch("gst_agent.pipeline.session.get", side_effect=lambda url, **kw: _FakeResponse(url.encode())), \
         patch("gst_agent.pipeline.extract_text") as mock_extract:
        from gst_agent.extractor import ExtractionResult
        mock_extract.return_value = ExtractionResult(text="irrelevant", ocr_used=False, page_count=1)
        response = client.post("/run", follow_redirects=True)

    assert response.status_code == 200
    assert b"2 new document(s) downloaded" in response.data
    with db.open_db(capped_settings.db_path) as conn:
        stats = db.get_stats(conn)
    assert stats["total_documents"] == 5  # discovery is never capped
    assert stats["by_status"]["done"] == 2  # but only the web-UI cap was downloaded


def test_run_now_failure_is_shown_as_flash_not_a_500(client):
    with patch("gst_agent.pipeline.get_enabled_sources", side_effect=RuntimeError("boom")):
        response = client.post("/run", follow_redirects=True)
    assert response.status_code == 200
    assert b"Run failed" in response.data


def test_retry_failed_triggers_pipeline_and_redirects(client):
    response = client.post("/retry-failed", follow_redirects=True)
    assert response.status_code == 200
    assert b"Retried 0 failed" in response.data


def test_documents_page_lists_seeded_document(client, test_settings):
    _seed_one_document(test_settings, status="done", category="Circular")
    response = client.get("/documents")
    assert response.status_code == 200
    assert b"Sample Circular" in response.data
    assert b"1 document(s)" in response.data


def test_documents_page_title_links_to_source_not_the_source_column(client, test_settings):
    # The document's name/title is what a reviewer expects to click to see
    # the document -- the link belongs there, not hidden under the source
    # label ("cbic") in its own column, which used to be the only clickable
    # element in the row.
    _seed_one_document(test_settings, status="done", category="Circular")
    response = client.get("/documents")
    html = response.data.decode()

    assert '<a href="https://example.com/a.pdf"' in html
    title_link_pos = html.index('<a href="https://example.com/a.pdf"')
    assert "Sample Circular</a>" in html[title_link_pos:title_link_pos + 200]

    # "cbic" (the source label) must appear as plain text, not as anchor text.
    assert "<a" not in html[html.index(">cbic<") - 10 : html.index(">cbic<")]


def test_documents_page_filters_by_category(client, test_settings):
    _seed_one_document(test_settings, status="done", category="Circular")
    matching = client.get("/documents?category=Circular")
    other = client.get("/documents?category=Order")
    assert b"Sample Circular" in matching.data
    assert b"Sample Circular" not in other.data
    assert b"0 document(s)" in other.data


def test_document_file_serves_the_real_pdf_bytes(client, test_settings):
    doc_id = _seed_one_document(test_settings, status="done")
    response = client.get(f"/documents/{doc_id}/file")
    assert response.status_code == 200
    assert response.data == b"%PDF-fake"
    assert response.mimetype == "application/pdf"


def test_document_file_404s_for_unknown_id(client):
    response = client.get("/documents/999/file")
    assert response.status_code == 404


def test_document_file_serves_legacy_rows_with_absolute_local_path(client, test_settings):
    # Rows written before local_path was stored relative to downloads_dir
    # (see pipeline.to_relative_download_path) have an absolute path already
    # -- those must keep working without a data migration.
    category_dir = test_settings.downloads_dir / "Circular"
    category_dir.mkdir(parents=True, exist_ok=True)
    file_path = category_dir / "legacy.pdf"
    file_path.write_bytes(b"%PDF-legacy")

    with db.open_db(test_settings.db_path) as conn:
        run_id = db.start_run(conn)
        doc_id = db.insert_discovered(
            conn, source="cbic", source_page="x", doc_url="https://example.com/legacy.pdf",
            title="Legacy doc", doc_number=None, doc_date=None, source_hint_category="Circular", run_id=run_id,
        )
        db.mark_downloaded(conn, doc_id, local_path=str(file_path), file_hash="legacyhash")
        db.finish_run(conn, run_id, new_documents_downloaded=1)

    response = client.get(f"/documents/{doc_id}/file")
    assert response.status_code == 200
    assert response.data == b"%PDF-legacy"


def test_logs_page_shows_no_entries_when_log_file_absent(client):
    response = client.get("/logs")
    assert response.status_code == 200
    assert b"No log entries yet" in response.data


def test_logs_page_shows_tail_of_real_log_file(client, test_settings):
    test_settings.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = test_settings.log_dir / "gst_agent.log"
    log_file.write_text("line one\nline two\nline three\n", encoding="utf-8")

    response = client.get("/logs?lines=2")
    assert response.status_code == 200
    assert b"line two" in response.data
    assert b"line three" in response.data
    assert b"line one" not in response.data
