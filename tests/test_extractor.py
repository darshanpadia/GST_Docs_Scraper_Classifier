from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from gst_agent.extractor import extract_text


def _make_pdf(path: Path, *, with_text: bool) -> None:
    doc = fitz.open()
    page = doc.new_page()
    if with_text:
        page.insert_text((72, 72), "This is a genuine digitally generated GST circular with real text.")
    doc.save(path)
    doc.close()


def test_extracts_native_text_without_ocr(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    _make_pdf(pdf_path, with_text=True)

    with patch("gst_agent.extractor._ocr_page") as mock_ocr:
        result = extract_text(pdf_path)

    assert "digitally generated" in result.text
    assert result.ocr_used is False
    assert result.page_count == 1
    mock_ocr.assert_not_called()


def test_falls_back_to_ocr_for_near_empty_page(tmp_path: Path):
    pdf_path = tmp_path / "scanned.pdf"
    _make_pdf(pdf_path, with_text=False)  # blank page -- looks scanned

    with patch("gst_agent.extractor._ocr_page", return_value="OCR RECOVERED TEXT") as mock_ocr:
        result = extract_text(pdf_path)

    assert result.ocr_used is True
    assert "OCR RECOVERED TEXT" in result.text
    mock_ocr.assert_called_once()


def test_ocr_failure_on_a_page_does_not_raise():
    # _ocr_page itself swallows OCR engine errors and returns "" -- verified
    # directly since it needs a real fitz.Page, which pytesseract failures
    # shouldn't require us to construct.
    class _BoomImage:
        width = 10
        height = 10
        samples = b"\x00" * 300

    class _BoomPage:
        def get_pixmap(self, dpi):
            return _BoomImage()

    from gst_agent.extractor import _ocr_page

    with patch("gst_agent.extractor.pytesseract.image_to_string", side_effect=RuntimeError("tesseract not found")):
        assert _ocr_page(_BoomPage()) == ""
