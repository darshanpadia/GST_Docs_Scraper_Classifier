"""Anthropic provider. Not part of the default Settings.llm_provider_order
(Anthropic's API isn't free), but left implemented and tested for anyone who
does have a key -- add "anthropic" to LLM_PROVIDER_ORDER to use it.
"""
from __future__ import annotations

import json
import os

import anthropic

from gst_agent.config import settings
from gst_agent.llm_providers import _shared
from gst_agent.llm_providers.base import LLMProvider
from gst_agent.models import LLMClassification

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def is_configured(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def classify(
        self, *, title: str, text: str, active_categories: list[str]
    ) -> LLMClassification:
        prompt = _shared.build_prompt(title, text, active_categories)
        response = _get_client().messages.create(
            model=settings.llm_model,
            max_tokens=200,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": _shared.RESPONSE_SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("LLM classification request was refused")

        text_block = next(block.text for block in response.content if block.type == "text")
        data = json.loads(text_block)
        return _shared.parse_response(data, active_categories)
