"""Groq provider (free tier via console.groq.com -- no credit card, see
README). Secondary/fallback provider in the default Settings.llm_provider_order,
tried only if Gemini is unconfigured or fails.

Module name is groq_provider.py, not groq.py, so it doesn't shadow the
`groq` package it imports from within this same package.
"""
from __future__ import annotations

import json

from groq import Groq

from gst_agent.config import settings
from gst_agent.llm_providers import _shared
from gst_agent.llm_providers.base import LLMProvider
from gst_agent.models import LLMClassification

# Groq's JSON object mode is only guaranteed on specific models (see
# console.groq.com/docs/structured-outputs) -- openai/gpt-oss-20b is one of
# them: fast, capable, and free-tier eligible.
_DEFAULT_MODEL = "openai/gpt-oss-20b"


class GroqProvider(LLMProvider):
    name = "groq"

    def is_configured(self) -> bool:
        return bool(settings.groq_api_key)

    def classify(
        self, *, title: str, text: str, active_categories: list[str]
    ) -> LLMClassification:
        if not self.is_configured():
            raise RuntimeError("GROQ_API_KEY is not set")

        client = Groq(api_key=settings.groq_api_key)
        prompt = _shared.build_prompt(
            title, text, active_categories, include_json_instructions=True
        )
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return _shared.parse_response(data, active_categories)
