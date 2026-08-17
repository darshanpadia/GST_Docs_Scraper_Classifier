"""Prompt/schema/response-parsing logic shared by every provider, so the
three SDK-specific modules only differ in how they actually call their API,
not in what they ask or how they interpret the answer."""
from __future__ import annotations

from gst_agent.models import LLMClassification

NO_MATCH = "NONE"

RESPONSE_SCHEMA: dict = {
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


def build_prompt(
    title: str, text: str, active_categories: list[str], *, include_json_instructions: bool = False
) -> str:
    """include_json_instructions=True is for providers with no native
    structured-output schema parameter (Groq's JSON mode just guarantees
    *valid* JSON, not a particular shape -- the desired keys have to be
    spelled out in the prompt itself). Gemini and Anthropic pass their own
    schema to the API directly, so they leave this off to avoid a redundant
    wall of JSON schema in the prompt text."""
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
    if include_json_instructions:
        prompt += (
            '\n\nRespond with a single JSON object, no other text, exactly '
            'in this shape: {"matched_category": "<one of the active '
            'categories, or NONE>", "proposed_category": "<short new '
            'category name if NONE, else empty string>"}'
        )
    return prompt


def parse_response(data: dict, active_categories: list[str]) -> LLMClassification:
    matched = data.get("matched_category") or None
    if matched == NO_MATCH or (matched is not None and matched not in active_categories):
        matched = None  # hallucinated category name -> treat as no match, not a bogus filing
    proposed = data.get("proposed_category") or None
    return LLMClassification(matched_category=matched, proposed_category=proposed)
