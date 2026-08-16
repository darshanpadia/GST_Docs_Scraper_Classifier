"""Shared data types passed between source modules and the pipeline."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveredDoc:
    """A document found on a source site, before it has been downloaded.

    source_hint_category is the category implied by *where* the document was
    found (e.g. "this came from the Circulars listing page"). The classifier
    later confirms or overrides this using the document's actual extracted
    text -- source_hint_category is a strong prior, not the final answer.
    """

    source: str
    source_page: str
    doc_url: str
    title: str
    doc_number: str | None
    doc_date: str | None
    source_hint_category: str


@dataclass(frozen=True)
class LLMClassification:
    """Result of asking the LLM fallback classifier to categorize a document.

    matched_category is set when the LLM picked one of the currently active
    categories. proposed_category is set instead when the LLM judged that no
    active category is a genuine fit and suggested a new one -- the document
    stays "Other" until that proposal recurs often enough to be promoted (see
    gst_agent.pipeline._promote_recurring_categories).
    """

    matched_category: str | None
    proposed_category: str | None
