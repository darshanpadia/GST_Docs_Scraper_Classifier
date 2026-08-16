"""Thin wrapper around the Anthropic API for the classifier's LLM fallback.

Only imported when ENABLE_LLM_FALLBACK is set (see gst_agent.classifier), so
the `anthropic` package and an API key stay optional for anyone who only
wants the rule-based classifier. The Anthropic client reads ANTHROPIC_API_KEY
from the environment itself -- no key handling lives in this project.
"""
from __future__ import annotations

import json

import anthropic

from gst_agent.config import settings
from gst_agent.models import LLMClassification

_client: anthropic.Anthropic | None = None

_NO_MATCH = "NONE"

_SCHEMA = {
    "type": "object",
    "properties": {
        "matched_category": {
            "type": "string",
            "description": (
                "The single best-fitting category from the provided list of "
                "active categories, or the literal string NONE if none of "
                "them genuinely fit."
            ),
        },
        "proposed_category": {
            "type": "string",
            "description": (
                "A short (1-3 word) name for a new category, only when "
                "matched_category is NONE. Empty string otherwise."
            ),
        },
    },
    "required": ["matched_category", "proposed_category"],
    "additionalProperties": False,
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def classify_document(
    *, title: str, text: str, active_categories: list[str]
) -> LLMClassification:
    excerpt = text[:4000]
    prompt = (
        "You classify Indian GST law documents (e.g. Acts, Rules, "
        "Notifications, Circulars, Orders, Instructions, Press Releases) by "
        "document type, based on their title and content.\n\n"
        f"Active categories: {', '.join(active_categories)}\n\n"
        f"Title: {title}\n\nText excerpt:\n{excerpt}\n\n"
        "Pick the single best-fitting active category. Only if none of them "
        "genuinely fit -- this is a real, distinct kind of document, not "
        "just an awkward match -- set matched_category to NONE and propose "
        "a short new category name instead."
    )
    response = _get_client().messages.create(
        model=settings.llm_model,
        max_tokens=200,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("LLM classification request was refused")

    text_block = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text_block)

    matched = data.get("matched_category") or None
    if matched == _NO_MATCH or (matched is not None and matched not in active_categories):
        matched = None
    proposed = data.get("proposed_category") or None

    return LLMClassification(matched_category=matched, proposed_category=proposed)
