"""LLM providers for the classifier's fallback path (see gst_agent.classifier).

Multiple providers exist so a free-tier API's rate limit or outage doesn't
take the fallback down entirely -- classify_with_llm() tries each configured
provider in order (see Settings.llm_provider_order) and only gives up once
all of them have failed, at which point the document simply stays "Other"
(never a run-ending error, consistent with the rest of this project's
failure handling).
"""
from __future__ import annotations

from gst_agent.config import settings
from gst_agent.llm_providers.anthropic_provider import AnthropicProvider
from gst_agent.llm_providers.base import LLMProvider
from gst_agent.llm_providers.gemini import GeminiProvider
from gst_agent.llm_providers.groq_provider import GroqProvider

_ALL_PROVIDERS: dict[str, type[LLMProvider]] = {
    GeminiProvider.name: GeminiProvider,
    GroqProvider.name: GroqProvider,
    AnthropicProvider.name: AnthropicProvider,
}


def get_ordered_providers() -> list[LLMProvider]:
    """Providers in Settings.llm_provider_order, skipping unknown names.
    Does NOT filter by is_configured() here -- classify_with_llm() checks
    that per-provider so it can log which ones were skipped and why."""
    names = [p.strip() for p in settings.llm_provider_order.split(",") if p.strip()]
    return [_ALL_PROVIDERS[name]() for name in names if name in _ALL_PROVIDERS]
