"""Category classification: rule-based first, LLM fallback for the rest.

Rule-based is the primary classifier -- deterministic, free, and reliable for
GST legal documents, which follow predictable boilerplate phrasing ("in
exercise of the powers conferred by section... hereby makes the following
rules", "Circular No. .../2024", etc). It runs on every document.

The LLM fallback (gst_agent.llm_client, disabled by default -- see
Settings.enable_llm_fallback) only runs for the minority the rules can't
confidently place. It can either confirm one of the currently active
categories or propose a brand-new one; proposals are not filed immediately
(see gst_agent.pipeline._promote_recurring_categories) -- a category only
becomes real once it has been independently proposed for enough different
documents to be a genuine recurring pattern, not a one-off guess.
"""
from __future__ import annotations

import logging
import re

from gst_agent.config import settings
from gst_agent.models import LLMClassification

logger = logging.getLogger("gst_agent.classifier")

# Boilerplate phrasing that reliably marks a document's legal type,
# independent of which source it came from. Checked only when the source's
# own hint was "Other" -- these patterns are a fallback signal, not a
# override of a source that already had a confident, cheap answer.
_TEXT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"hereby makes? the following rules", re.I), "Rule"),
    (re.compile(r"in exercise of the powers conferred by section.{0,120}\brules\b", re.I), "Rule"),
    (re.compile(r"\border no\.?\s*\d", re.I), "Order"),
    (re.compile(r"hereby directs? that", re.I), "Order"),
    (re.compile(r"\bcircular no\.?\s*\d", re.I), "Circular"),
    (re.compile(r"\bnotification no\.?\s*\d", re.I), "Notification"),
    (re.compile(r"hereby notifies", re.I), "Notification"),
    (re.compile(r"\ban act to\b", re.I), "Act"),
    (re.compile(r"be it enacted by parliament", re.I), "Act"),
    (re.compile(r"\binstructions? no\.?\s*\d", re.I), "Instruction"),
    (re.compile(r"\bpress release\b", re.I), "Press Release"),
]


def classify_rule_based(
    *, text: str, title: str, source_hint_category: str
) -> tuple[str, bool]:
    """Return (category, confident).

    source_hint_category comes from the source module (filename/listing-page
    context) and is trusted as-is whenever it isn't "Other" -- the source
    already had a strong, cheap signal from where the document was found.
    Only when that's absent do we fall back to boilerplate phrasing in the
    extracted text itself.
    """
    if source_hint_category and source_hint_category != "Other":
        return source_hint_category, True

    haystack = f"{title}\n{text[:3000]}"
    for pattern, category in _TEXT_PATTERNS:
        if pattern.search(haystack):
            return category, True

    return "Other", False


def classify_with_llm(
    *, text: str, title: str, active_categories: list[str]
) -> LLMClassification | None:
    """Ask the LLM to classify a document the rule-based pass couldn't place
    confidently. Returns None if the fallback is disabled, unavailable, or
    the call fails for any reason -- callers must treat that as "leave it
    Other", not as an error that aborts the document.
    """
    if not settings.enable_llm_fallback:
        return None

    from gst_agent import llm_client  # local import: keep `anthropic` optional

    try:
        return llm_client.classify_document(
            title=title, text=text, active_categories=active_categories
        )
    except Exception as exc:
        logger.warning("LLM classification fallback failed: %s", exc)
        return None
