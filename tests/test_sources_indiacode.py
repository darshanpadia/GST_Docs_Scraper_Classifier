from unittest.mock import patch

from gst_agent.sources.indiacode import ACT_HANDLE_PAGES, IndiaCodeSource

FAKE_HANDLE_PAGE_HTML = """
<html><head>
<meta name="citation_pdf_url" content="http://indiacode.nic.in/bitstream/123456789/15689/1/A2017-12.pdf" />
</head><body>Central Goods and Services Tax Act, 2017</body></html>
"""

FAKE_HANDLE_PAGE_MISSING_META = "<html><head></head><body>No meta tag here</body></html>"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


def test_discover_resolves_citation_pdf_url_and_upgrades_to_https():
    with patch(
        "gst_agent.sources.indiacode.session.get",
        return_value=_FakeResponse(FAKE_HANDLE_PAGE_HTML),
    ):
        docs = IndiaCodeSource().discover()

    assert len(docs) == len(ACT_HANDLE_PAGES)
    cgst = next(d for d in docs if "Central Goods" in d.title)
    assert cgst.doc_url == "https://indiacode.nic.in/bitstream/123456789/15689/1/A2017-12.pdf"
    assert cgst.source_hint_category == "Act"
    assert cgst.source == "indiacode"


def test_discover_skips_pages_missing_citation_meta_tag_without_crashing():
    with patch(
        "gst_agent.sources.indiacode.session.get",
        return_value=_FakeResponse(FAKE_HANDLE_PAGE_MISSING_META),
    ):
        docs = IndiaCodeSource().discover()

    assert docs == []


def test_discover_continues_past_a_single_source_error():
    calls = {"n": 0}

    def flaky_get(url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated network failure")
        return _FakeResponse(FAKE_HANDLE_PAGE_HTML)

    with patch("gst_agent.sources.indiacode.session.get", side_effect=flaky_get):
        docs = IndiaCodeSource().discover()

    assert len(docs) == len(ACT_HANDLE_PAGES) - 1
