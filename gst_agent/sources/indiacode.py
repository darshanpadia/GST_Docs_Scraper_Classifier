"""India Code (indiacode.nic.in) source -- Ministry of Law and Justice's
official legislative repository. Used only for canonical Act text.

Each entry below is a stable DSpace "handle" landing page (verified
manually, see README). Rather than hardcoding the PDF path directly -- which
would go stale if India Code re-uploads a newer consolidated version at a
new path -- we read the page's own `citation_pdf_url` meta tag at run time
and follow wherever it currently points.

DISABLED BY DEFAULT (not in the default ENABLED_SOURCES). robots.txt on
this domain permits crawling (only /discover and /simple-search are
disallowed), but the server itself returns HTTP 403 for our honestly
identifying User-Agent -- a WAF-level anti-bot check independent of
robots.txt. A generic browser-like User-Agent does get through, but
presenting this project as a browser to defeat that check is exactly the
kind of anti-bot bypass the assignment says not to do, so this source is
left implemented and tested but switched off until/unless there's a
legitimate way to satisfy that server's access policy.
"""
from __future__ import annotations

import logging

from bs4 import BeautifulSoup

from gst_agent.http_client import RobotsDisallowed, session
from gst_agent.models import DiscoveredDoc
from gst_agent.sources.base import DocumentSource

logger = logging.getLogger("gst_agent.sources.indiacode")

ACT_HANDLE_PAGES: dict[str, str] = {
    "Central Goods and Services Tax Act, 2017": "https://www.indiacode.nic.in/handle/123456789/15689",
    "Integrated Goods and Services Tax Act, 2017": "https://www.indiacode.nic.in/handle/123456789/2251",
    "Union Territory Goods and Services Tax Act, 2017": "https://www.indiacode.nic.in/handle/123456789/2252",
    "Goods and Services Tax (Compensation to States) Act, 2017": "https://www.indiacode.nic.in/handle/123456789/2253",
}


class IndiaCodeSource(DocumentSource):
    name = "indiacode"

    def discover(self) -> list[DiscoveredDoc]:
        docs: list[DiscoveredDoc] = []
        for title, handle_url in ACT_HANDLE_PAGES.items():
            try:
                response = session.get(handle_url)
            except RobotsDisallowed:
                raise
            except Exception as exc:
                logger.warning("Failed to fetch India Code page %s: %s", handle_url, exc)
                continue

            soup = BeautifulSoup(response.text, "lxml")
            meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
            if meta is None or not meta.get("content"):
                logger.warning(
                    "No citation_pdf_url meta tag on %s -- site layout may have changed",
                    handle_url,
                )
                continue

            pdf_url = meta["content"].strip()
            if pdf_url.startswith("http://"):
                pdf_url = "https://" + pdf_url[len("http://"):]

            docs.append(
                DiscoveredDoc(
                    source="indiacode",
                    source_page=handle_url,
                    doc_url=pdf_url,
                    title=title,
                    doc_number=None,
                    doc_date=None,
                    source_hint_category="Act",
                )
            )
        return docs
