from gst_agent.sources.cbic import _parse_listing_table, _parse_whats_new

PAGE_URL = "https://cbic-gst.gov.in/circulars-cgst.html"

TICKER_HTML = """
<html><body>
<div id="vmarquee">
<ul>
  <li><i class="fa"></i> <a href="pdf/Circular-No-250-2025.pdf" target="_blank">Reviewing authority for
      show cause notices issued by DGGI -reg.</a></li>
  <li><i class="fa"></i> <a href="pdf/ins-gst-no-03-2025.pdf" target="_blank">Instructions for processing of
      applications for GST registration - regarding.</a></li>
  <li><i class="fa"></i> <a href="pdf/gst-ct-11-2025.pdf" target="_blank">Seeks to notify Central Goods and
      Services Tax (Second Amendment) Rules 2025</a></li>
  <li><i class="fa"></i> Seeks to appoint common adjudicating authority for GST Show cause notices. &nbsp;
      <a href="pdf/NN-31-2024-Eng.pdf" target="_blank">English</a> &nbsp;|&nbsp;
      <a href="pdf/NN-31-2024-Hindi.pdf" target="_blank">Hindi</a></li>
  <li><i class="fa"></i> <a href="pdf/Advisory022026.pdf" target="_blank">Kind Attention Central Excise
      Taxpayers: Accounting Head for Payment of HSNS Cess - Reg</a></li>
  <li><i class="fa"></i> <a href="pdf/vacancy-circular.pdf" target="_blank">Vacancy Circular for Consultant
      appointment</a></li>
</ul>
</div>
</body></html>
"""

TABLE_HTML = """
<html><body>
<table class="table table-bordered table-hover">
  <thead>
    <tr><th>Circular No.</th><th>English</th><th>हिन्दी</th><th>Date of issue</th><th>Subject</th></tr>
  </thead>
  <tbody>
    <tr>
      <td>Order-03/2017</td>
      <td><a href="pdf/Order-No-3.pdf" target="_blank">View (143 KB)</a></td>
      <td></td>
      <td>21-09-2017</td>
      <td style="text-align:left;">Extension of time limit for submitting the declaration in FORM GST TRAN-1</td>
    </tr>
    <tr>
      <td>07/2017</td>
      <td><a href="pdf/Circular_7_7_2017.pdf" target="_blank">View (371 KB)</a></td>
      <td></td>
      <td>01-09-2017</td>
      <td style="text-align:left;">System based reconciliation of information furnished in FORM GSTR-1</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_ticker_parses_simple_anchor_items():
    docs = _parse_whats_new(TICKER_HTML, PAGE_URL)
    urls = {d.doc_url for d in docs}
    assert "https://cbic-gst.gov.in/pdf/Circular-No-250-2025.pdf" in urls
    circular = next(d for d in docs if d.doc_url.endswith("Circular-No-250-2025.pdf"))
    assert circular.source_hint_category == "Circular"


def test_ticker_classifies_instruction_from_filename():
    docs = {d.doc_url.rsplit("/", 1)[-1]: d for d in _parse_whats_new(TICKER_HTML, PAGE_URL)}
    assert docs["ins-gst-no-03-2025.pdf"].source_hint_category == "Instruction"


def test_ticker_falls_back_to_other_when_neither_filename_nor_title_give_a_confident_signal():
    # This item's subject mentions "Rules" but nothing marks it a Circular/
    # Order/Notification/Act/Instruction -- "Other" is the honest answer,
    # not a guessed "Rule" (see comment in cbic.py on why Rule is excluded
    # from the ticker's keyword fallback).
    docs = {d.doc_url.rsplit("/", 1)[-1]: d for d in _parse_whats_new(TICKER_HTML, PAGE_URL)}
    assert docs["gst-ct-11-2025.pdf"].source_hint_category == "Other"


def test_ticker_handles_bilingual_pair_format_preferring_english():
    docs = _parse_whats_new(TICKER_HTML, PAGE_URL)
    match = [d for d in docs if "NN-31-2024" in d.doc_url]
    assert len(match) == 1  # Hindi duplicate must not produce a second entry
    assert match[0].doc_url.endswith("NN-31-2024-Eng.pdf")
    assert "adjudicating authority" in match[0].title.lower()


def test_ticker_excludes_non_gst_central_excise_item():
    docs = _parse_whats_new(TICKER_HTML, PAGE_URL)
    assert all("Advisory022026" not in d.doc_url for d in docs)


def test_ticker_excludes_irrelevant_vacancy_item():
    docs = _parse_whats_new(TICKER_HTML, PAGE_URL)
    assert all("vacancy" not in d.doc_url.lower() for d in docs)


def test_listing_table_parses_rows_and_reclassifies_order_prefixed_rows():
    docs = _parse_listing_table(TABLE_HTML, PAGE_URL, category_hint="Circular")
    assert len(docs) == 2

    order_doc = next(d for d in docs if d.doc_number == "Order-03/2017")
    assert order_doc.source_hint_category == "Order"
    assert order_doc.doc_date == "21-09-2017"
    assert order_doc.doc_url == "https://cbic-gst.gov.in/pdf/Order-No-3.pdf"

    circular_doc = next(d for d in docs if d.doc_number == "07/2017")
    assert circular_doc.source_hint_category == "Circular"
    assert "GSTR-1" in circular_doc.title
