from gst_agent.sources.gstcouncil import _parse_circulars_advisory, _parse_meetings

CIRCULARS_URL = "https://gstcouncil.gov.in/en/circularsadvisory"
MEETINGS_URL = "https://gstcouncil.gov.in/en/gst-council-meeting"

# Trimmed excerpts of the real, manually-verified page structure (see
# gstcouncil.py module docstring).
CIRCULARS_HTML = """
<html><body>
<table class="custum-tbl table table-bordered">
  <thead><tr><th>S No</th><th>Circulars/Advisory No.</th><th>Date</th><th>Subject</th><th>View</th></tr></thead>
  <tbody>
    <tr>
      <td>1</td>
      <td>295/CommunicationwithStatesandMinistriesofGovtofIndia/GSTC/2023</td>
      <td>25th July, 2024</td>
      <td>Advisory on Coordination Between State Tax Authorities and Central Tax Authorities.</td>
      <td>
        <a href="https://gstcouncil.gov.in/sites/default/files/2024-11/advisory_in_case_of_tobacco_products.pdf" target="_blank"><img alt="pdf" /></a>
        <p><a href="https://gstcouncil.gov.in/sites/default/files/2024-11/advisory_in_case_of_tobacco_products.pdf"> View</a> (Format: pdf, Size: 33 KB)</p>
      </td>
    </tr>
  </tbody>
</table>
</body></html>
"""

MEETINGS_HTML = """
<html><body>
<table class="table table-bordered customdatatable">
  <thead><tr><th>Meetings</th><th>Date of Meeting</th><th>Venue</th><th>Agenda</th><th>MINUTES</th></tr></thead>
  <tbody>
    <tr>
      <td>55th GST Council Meeting</td>
      <td>21-Dec-2024</td>
      <td>Jaisalmer</td>
      <td><a href="/sites/default/files/Agenda/55th_meeting_agenda_compressed_1.pdf ">View</a> (Format: pdf, Size: 22.1 MB)</td>
      <td><a href="/sites/default/files/Minutes/minutes_of_55th_gst_council_for_upload_ocred_compressed_0.pdf">View</a> (Format: pdf, Size: 27.04 MB)</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_parses_circulars_advisory_row():
    docs = _parse_circulars_advisory(CIRCULARS_HTML, CIRCULARS_URL)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.source == "gstcouncil"
    assert doc.doc_number == "295/CommunicationwithStatesandMinistriesofGovtofIndia/GSTC/2023"
    assert doc.doc_date == "25th July, 2024"
    assert doc.source_hint_category == "Circular"
    assert doc.doc_url.endswith("advisory_in_case_of_tobacco_products.pdf")


def test_parses_meeting_row_into_agenda_and_minutes_documents():
    docs = _parse_meetings(MEETINGS_HTML, MEETINGS_URL)
    assert len(docs) == 2

    labels = {d.title.split(" -- ")[1].split(" (")[0] for d in docs}
    assert labels == {"Agenda", "Minutes"}

    for doc in docs:
        assert doc.source == "gstcouncil"
        assert doc.doc_number == "55th GST Council Meeting"
        assert doc.doc_date == "21-Dec-2024"
        assert doc.source_hint_category == "Council Meeting"

    agenda = next(d for d in docs if "Agenda" in d.title)
    # The real site's href has a trailing space before the closing quote --
    # must be stripped, not carried into the URL.
    assert agenda.doc_url == "https://gstcouncil.gov.in/sites/default/files/Agenda/55th_meeting_agenda_compressed_1.pdf"


def test_meetings_parser_ignores_unrelated_tables():
    other_table_html = "<html><body><table><thead><tr><th>Foo</th><th>Bar</th></tr></thead></table></body></html>"
    assert _parse_meetings(other_table_html, MEETINGS_URL) == []
    assert _parse_circulars_advisory(other_table_html, CIRCULARS_URL) == []
