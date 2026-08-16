"""Manual live smoke test: run discovery against the real sites (no
downloads) and print a summary. Not part of the pytest suite on purpose --
it depends on live network/government servers, which is exactly what real
unit tests should NOT depend on. Run it by hand:

    .venv/Scripts/python.exe scripts_dry_run_discovery.py
"""
from collections import Counter

from gst_agent.sources.cbic import CbicSource
from gst_agent.sources.gstcouncil import GstCouncilSource
from gst_agent.sources.indiacode import IndiaCodeSource

for source_cls in (CbicSource, GstCouncilSource, IndiaCodeSource):
    source = source_cls()
    docs = source.discover()
    print(f"\n=== {source.name} ({len(docs)} documents discovered) ===")
    by_category = Counter(d.source_hint_category for d in docs)
    for category, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        print(f"  {category:15s} {count}")
    print("  -- sample --")
    for doc in docs[:5]:
        print(f"  [{doc.source_hint_category}] {doc.title[:70]!r} -> {doc.doc_url}")
