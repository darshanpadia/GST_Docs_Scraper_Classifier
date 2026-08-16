"""PDF text extraction: native text first, OCR fallback per page.

Most CBIC/India Code PDFs are digitally generated (a real text layer), so
native extraction via PyMuPDF is tried first and is essentially free. Only
pages that come back with too little text (scanned/photographed notifications,
older circulars) are re-rendered to an image and OCR'd with Tesseract -- this
keeps OCR, which is slow and CPU-heavy, off the common path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz  # PyMuPDF -- `import fitz` is the deprecated alias
import pytesseract
from PIL import Image

from gst_agent.config import settings

logger = logging.getLogger("gst_agent.extractor")

if settings.tesseract_cmd:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    ocr_used: bool
    page_count: int


def extract_text(pdf_path: Path) -> ExtractionResult:
    doc = fitz.open(pdf_path)
    try:
        page_texts: list[str] = []
        ocr_used = False
        for page in doc:
            native_text = page.get_text().strip()
            if len(native_text) >= settings.ocr_min_chars_per_page:
                page_texts.append(native_text)
                continue
            ocr_text = _ocr_page(page)
            if ocr_text.strip():
                ocr_used = True
            page_texts.append(ocr_text)
        return ExtractionResult(
            text="\n\n".join(page_texts), ocr_used=ocr_used, page_count=doc.page_count
        )
    finally:
        doc.close()


def _ocr_page(page: "fitz.Page") -> str:
    # 300 DPI is the usual floor for reliable OCR accuracy on scanned
    # government documents without making images unreasonably large.
    pix = page.get_pixmap(dpi=300)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    try:
        return pytesseract.image_to_string(image)
    except Exception as exc:
        logger.warning("OCR failed for a page: %s", exc)
        return ""
