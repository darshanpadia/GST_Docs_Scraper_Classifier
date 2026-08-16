"""CBIC GST Portal (cbic-gst.gov.in) source.

Two independent discovery mechanisms feed the same parser output, because
manual inspection (see README "Source research notes") found the site's
own category pages (Notifications/Circulars/etc.) are only reachable via a
JavaScript-driven menu with no static links -- there is no crawlable index
of them. Two things ARE reliably, statically parseable:

1. The homepage "What's New" ticker: a plain <ul> embedded directly in the
   server-rendered HTML (only its scroll animation is JS; the content
   itself needs no JS execution to read). This is the actively maintained,
   always-current feed and is what makes daily incremental discovery work.
2. A small, manually verified set of "seed" archive listing pages that were
   found to still work and contain real tabular data. These backfill
   history but are NOT actively maintained by CBIC -- treat this list as a
   floor, not a ceiling; extend it if more working pages are found.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from gst_agent.config import IRRELEVANT_KEYWORDS
from gst_agent.http_client import RobotsDisallowed, session
from gst_agent.models import DiscoveredDoc
from gst_agent.sources.base import DocumentSource

logger = logging.getLogger("gst_agent.sources.cbic")

BASE_URL = "https://cbic-gst.gov.in/"

# path -> category hint. Verified by direct fetch during development: both
# return HTTP 200 and contain a genuine <table> of Number/English-PDF/
# Hindi-PDF/Date/Subject rows (see README for how these were found).
SEED_LISTING_PAGES: dict[str, str] = {
    "circulars-cgst.html": "Circular",
    "integrated-tax-notifications.html": "Notification",
}

_LANG_LABELS = {"english", "hindi", "देखें", "view"}

# Ticker items have no structured category field, so category is inferred
# in two passes. Pass 1 (higher confidence): CBIC's own PDF filenames follow
# fairly consistent prefixes, checked against the filename only.
_FILENAME_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"press[-_]?release", re.I), "Press Release"),
    (re.compile(r"^ins[-_]|instruction", re.I), "Instruction"),
    (re.compile(r"^cir|circular", re.I), "Circular"),
    (re.compile(r"^order|^order-", re.I), "Order"),
    (re.compile(r"^nn[-_]|notfctn|notification", re.I), "Notification"),
]

# Pass 2 (lower confidence fallback): keywords in the free-text subject.
# Deliberately does NOT include "Rule" here -- a notification's subject line
# routinely mentions "...Rules 2025" while the document itself is legally a
# Notification (identified by its own notification number), so guessing
# "Rule" from that word alone would misclassify it. Dedicated Rule text only
# comes from a real Rules listing/page, not this ticker.
_TITLE_KEYWORD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"press release", re.I), "Press Release"),
    (re.compile(r"\binstructions?\b", re.I), "Instruction"),
    (re.compile(r"\bcirculars?\b", re.I), "Circular"),
    (re.compile(r"\borders?\b", re.I), "Order"),
    (re.compile(r"\bnotifications?\b", re.I), "Notification"),
    (re.compile(r"\bacts?\b", re.I), "Act"),
]

# The ticker also carries non-GST CBIC business (Central Excise, Customs,
# ICEGATE helpdesk advisories). Keep an item only if it looks GST-related.
# NOTE: checked against the item's TITLE text only -- never the doc_url,
# because every URL on this domain contains "cbic-**gst**.gov.in" and would
# trivially satisfy a GST-term check regardless of the document's content.
_GST_HINT_TERMS = (
    "gst", "goods and services tax", "cgst", "igst", "utgst",
    "compensation cess",
)
_NON_GST_TERMS = ("central excise", "customs", "icegate", "hsns")


def _classify_hint(title: str, url: str) -> str:
    filename = url.rsplit("/", 1)[-1]
    for pattern, category in _FILENAME_CATEGORY_RULES:
        if pattern.search(filename):
            return category
    for pattern, category in _TITLE_KEYWORD_RULES:
        if pattern.search(title):
            return category
    return "Other"


def _extract_doc_number(text: str) -> str | None:
    match = re.search(
        r"\b(?:No\.?|Number)?\s*(\d{1,4}[/-]\d{2,4}(?:-[A-Za-z]+)?)\b", text
    )
    return match.group(1) if match else None


def _parse_whats_new(html: str, page_url: str) -> list[DiscoveredDoc]:
    soup = BeautifulSoup(html, "lxml")
    marquee = soup.find(id="vmarquee")
    if marquee is None:
        logger.warning("Could not find #vmarquee ticker on %s -- page layout may have changed", page_url)
        return []

    docs: list[DiscoveredDoc] = []
    for li in marquee.find_all("li"):
        anchors = li.find_all("a")
        if not anchors:
            continue

        real_anchors = [a for a in anchors if a.get_text(strip=True).lower() not in _LANG_LABELS]
        if real_anchors:
            anchor = real_anchors[0]
            href = anchor.get("href")
            title = anchor.get_text(strip=True) or li.get_text(" ", strip=True)
        else:
            # Bilingual pair format: "<subject text> English | Hindi"
            english = next(
                (a for a in anchors if a.get_text(strip=True).lower() == "english"), anchors[0]
            )
            href = english.get("href")
            title = li.get_text(" ", strip=True)
            for label in ("English", "Hindi", "|"):
                title = title.replace(label, "")
            title = title.strip(" \xa0")

        if not href or not href.lower().endswith(".pdf"):
            continue

        doc_url = urljoin(page_url, href)
        title = " ".join(title.split()) or doc_url.rsplit("/", 1)[-1]

        title_lower = title.lower()
        has_gst_term = any(term in title_lower for term in _GST_HINT_TERMS)
        has_non_gst_term = any(term in title_lower for term in _NON_GST_TERMS)
        if has_non_gst_term and not has_gst_term:
            continue
        if any(kw in title_lower for kw in IRRELEVANT_KEYWORDS):
            continue

        docs.append(
            DiscoveredDoc(
                source="cbic",
                source_page=page_url,
                doc_url=doc_url,
                title=title[:500],
                doc_number=_extract_doc_number(title),
                doc_date=None,
                source_hint_category=_classify_hint(title, doc_url),
            )
        )
    return docs


def _parse_listing_table(html: str, page_url: str, category_hint: str) -> list[DiscoveredDoc]:
    soup = BeautifulSoup(html, "lxml")
    docs: list[DiscoveredDoc] = []
    date_pattern = re.compile(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$")

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any("english" in h for h in headers):
            continue  # not a document listing table

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            number_text = cells[0].get_text(strip=True)
            if not number_text:
                continue

            link = None
            for cell in cells[1:3]:
                anchor = cell.find("a", href=True)
                if anchor and anchor["href"].lower().endswith(".pdf"):
                    link = anchor
                    break
            if link is None:
                continue

            date_text = None
            subject_text = None
            for cell in cells[2:]:
                text = cell.get_text(" ", strip=True)
                if not text:
                    continue
                text = " ".join(text.split())
                if date_pattern.match(text):
                    date_text = text
                elif subject_text is None and len(text) > 10:
                    subject_text = text

            hint = category_hint
            if re.match(r"(?i)^order[-\s]?\d", number_text):
                hint = "Order"

            docs.append(
                DiscoveredDoc(
                    source="cbic",
                    source_page=page_url,
                    doc_url=urljoin(page_url, link["href"]),
                    title=(subject_text or number_text)[:500],
                    doc_number=number_text,
                    doc_date=date_text,
                    source_hint_category=hint,
                )
            )
    return docs


class CbicSource(DocumentSource):
    name = "cbic"

    def discover(self) -> list[DiscoveredDoc]:
        docs: list[DiscoveredDoc] = []

        try:
            response = session.get(BASE_URL)
            docs.extend(_parse_whats_new(response.text, BASE_URL))
        except RobotsDisallowed:
            raise
        except Exception as exc:
            logger.warning("Failed to fetch/parse CBIC homepage ticker: %s", exc)

        for path, category_hint in SEED_LISTING_PAGES.items():
            page_url = urljoin(BASE_URL, path)
            try:
                response = session.get(page_url)
                docs.extend(_parse_listing_table(response.text, page_url, category_hint))
            except RobotsDisallowed:
                raise
            except Exception as exc:
                logger.warning("Failed to fetch/parse CBIC listing page %s: %s", page_url, exc)

        return docs
