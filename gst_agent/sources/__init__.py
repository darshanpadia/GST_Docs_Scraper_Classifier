from gst_agent.sources.base import DocumentSource
from gst_agent.sources.cbic import CbicSource
from gst_agent.sources.gstcouncil import GstCouncilSource
from gst_agent.sources.indiacode import IndiaCodeSource

ALL_SOURCES: dict[str, type[DocumentSource]] = {
    CbicSource.name: CbicSource,
    GstCouncilSource.name: GstCouncilSource,
    IndiaCodeSource.name: IndiaCodeSource,
}


def get_enabled_sources(enabled_names: tuple[str, ...]) -> list[DocumentSource]:
    sources = []
    for name in enabled_names:
        cls = ALL_SOURCES.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown source '{name}'. Known sources: {sorted(ALL_SOURCES)}"
            )
        sources.append(cls())
    return sources
