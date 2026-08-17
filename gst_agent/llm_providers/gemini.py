"""Google Gemini provider (free tier via Google AI Studio -- no credit card,
see README). Primary provider in the default Settings.llm_provider_order."""
from __future__ import annotations

import json

from google import genai

from gst_agent.config import settings
from gst_agent.llm_providers import _shared
from gst_agent.llm_providers.base import LLMProvider
from gst_agent.models import LLMClassification


class GeminiProvider(LLMProvider):
    name = "gemini"

    def is_configured(self) -> bool:
        return bool(settings.gemini_api_key)

    def classify(
        self, *, title: str, text: str, active_categories: list[str]
    ) -> LLMClassification:
        if not self.is_configured():
            raise RuntimeError("GEMINI_API_KEY is not set")

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = _shared.build_prompt(title, text, active_categories)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": _shared.RESPONSE_SCHEMA,
            },
        )
        data = json.loads(response.text)
        return _shared.parse_response(data, active_categories)
