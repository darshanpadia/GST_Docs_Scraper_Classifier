"""GST Council Secretariat (gstcouncil.gov.in) source.

robots.txt on this domain (manually verified) only disallows /admin/,
/search/, and /user/* paths -- nothing on the two pages used here.

Two pages provide real, static, server-rendered content:

1. /en/gst-council-meeting -- the full history of GST Council meetings, each
   with an Agenda PDF and a Minutes PDF. This is the actively maintained one
   (through the 55th meeting, Dec 2024, at time of writing) and the reason
   this source is worth having: meeting minutes/agendas are official GST
   Council records that don't fit any of the assignment's example
   categories, so they're filed under "Council Meeting" (see config.py).
2. /en/circularsadvisory -- circulars and advisories issued by the GST
   Council Secretariat itself (distinct from CBIC's own circulars). Small
   (3 entries at time of writing) but real.

The homepage's "What's New" ticker and /press-release were also inspected
but are populated client-side (the press-release table renders "No Data
Found!" in the static HTML) -- not usable without executing JavaScript,
which this project deliberately doesn't do (see cbic.py for the same
reasoning about CBIC's own category pages).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from gst_agent.http_client import RobotsDisallowed, session
from gst_agent.models import DiscoveredDoc
from gst_agent.sources.base import DocumentSource

logger = logging.getLogger("gst_agent.sources.gstcouncil")

BASE_URL = "https://gstcouncil.gov.in/"
CIRCULARS_URL = urljoin(BASE_URL, "en/circularsadvisory")
MEETINGS_URL = urljoin(BASE_URL, "en/gst-council-meeting")


def _first_pdf_href(cell) -> str | None:
    for anchor in cell.find_all("a", href=True):
        href = anchor["href"].strip()
        if href.lower().endswith(".pdf"):
            return href
    return None


def _parse_circulars_advisory(html: str, page_url: str) -> list[DiscoveredDoc]:
    soup = BeautifulSoup(html, "lxml")
    docs: list[DiscoveredDoc] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any("circulars/advisory" in h for h in headers):
            continue  # not the table we're looking for

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            doc_number = cells[1].get_text(strip=True)
            date_text = cells[2].get_text(strip=True)
            subject = cells[3].get_text(" ", strip=True)
            href = _first_pdf_href(cells[4])
            if not href or not doc_number:
                continue

            docs.append(
                DiscoveredDoc(
                    source="gstcouncil",
                    source_page=page_url,
                    doc_url=urljoin(page_url, href),
                    title=subject[:500] or doc_number,
                    doc_number=doc_number,
                    doc_date=date_text or None,
                    source_hint_category="Circular",
                )
            )
    return docs


def _parse_meetings(html: str, page_url: str) -> list[DiscoveredDoc]:
    soup = BeautifulSoup(html, "lxml")
    docs: list[DiscoveredDoc] = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "agenda" not in headers or "minutes" not in [h.lower() for h in headers]:
            continue

        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            meeting_name = cells[0].get_text(strip=True)
            date_text = cells[1].get_text(strip=True)
            venue = cells[2].get_text(strip=True)
            if not meeting_name:
                continue

            for label, cell in (("Agenda", cells[3]), ("Minutes", cells[4])):
                href = _first_pdf_href(cell)
                if not href:
                    continue
                docs.append(
                    DiscoveredDoc(
                        source="gstcouncil",
                        source_page=page_url,
                        doc_url=urljoin(page_url, href),
                        title=f"{meeting_name} -- {label} ({venue})"[:500],
                        doc_number=meeting_name,
                        doc_date=date_text or None,
                        source_hint_category="Council Meeting",
                    )
                )
    return docs


class GstCouncilSource(DocumentSource):
    name = "gstcouncil"

    def discover(self) -> list[DiscoveredDoc]:
        docs: list[DiscoveredDoc] = []

        for url, parser in ((CIRCULARS_URL, _parse_circulars_advisory), (MEETINGS_URL, _parse_meetings)):
            try:
                response = session.get(url)
                docs.extend(parser(response.text, url))
            except RobotsDisallowed:
                raise
            except Exception as exc:
                logger.warning("Failed to fetch/parse GST Council page %s: %s", url, exc)

        return docs
