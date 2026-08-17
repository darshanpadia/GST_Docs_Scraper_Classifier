import dataclasses
from unittest.mock import patch

from gst_agent.config import settings as real_settings
from gst_agent.llm_providers import get_ordered_providers
from gst_agent.llm_providers.anthropic_provider import AnthropicProvider
from gst_agent.llm_providers.gemini import GeminiProvider
from gst_agent.llm_providers.groq_provider import GroqProvider


def test_default_order_is_gemini_then_groq():
    providers = get_ordered_providers()
    assert [type(p) for p in providers] == [GeminiProvider, GroqProvider]


def test_order_is_configurable_via_settings():
    custom = dataclasses.replace(real_settings, llm_provider_order="anthropic,gemini")
    with patch("gst_agent.llm_providers.settings", custom):
        providers = get_ordered_providers()
    assert [type(p) for p in providers] == [AnthropicProvider, GeminiProvider]


def test_unknown_provider_names_are_skipped_not_errors():
    custom = dataclasses.replace(real_settings, llm_provider_order="groq,not-a-real-provider")
    with patch("gst_agent.llm_providers.settings", custom):
        providers = get_ordered_providers()
    assert [type(p) for p in providers] == [GroqProvider]
