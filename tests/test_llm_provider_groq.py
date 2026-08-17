import dataclasses
import json
from unittest.mock import MagicMock, patch

from gst_agent.config import settings as real_settings
from gst_agent.llm_providers.groq_provider import GroqProvider


def _configured_settings(**overrides):
    return dataclasses.replace(real_settings, groq_api_key="fake-key", **overrides)


def _fake_groq_response(payload: dict):
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    return response


def test_is_configured_reflects_api_key():
    with patch("gst_agent.llm_providers.groq_provider.settings", _configured_settings()):
        assert GroqProvider().is_configured() is True
    with patch("gst_agent.llm_providers.groq_provider.settings", dataclasses.replace(real_settings, groq_api_key=None)):
        assert GroqProvider().is_configured() is False


def test_classify_matches_active_category():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_groq_response(
        {"matched_category": "Circular", "proposed_category": ""}
    )

    with patch("gst_agent.llm_providers.groq_provider.settings", _configured_settings()), \
         patch("gst_agent.llm_providers.groq_provider.Groq", return_value=fake_client):
        result = GroqProvider().classify(title="t", text="x", active_categories=["Circular", "Order"])

    assert result.matched_category == "Circular"
    assert result.proposed_category is None
    # JSON mode must actually be requested -- Groq's response otherwise
    # isn't guaranteed to even be valid JSON.
    _, kwargs = fake_client.chat.completions.create.call_args
    assert kwargs["response_format"] == {"type": "json_object"}


def test_classify_proposes_new_category_on_none_match():
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _fake_groq_response(
        {"matched_category": "NONE", "proposed_category": "Advisory"}
    )

    with patch("gst_agent.llm_providers.groq_provider.settings", _configured_settings()), \
         patch("gst_agent.llm_providers.groq_provider.Groq", return_value=fake_client):
        result = GroqProvider().classify(title="t", text="x", active_categories=["Order"])

    assert result.matched_category is None
    assert result.proposed_category == "Advisory"


def test_classify_raises_when_not_configured():
    unconfigured = dataclasses.replace(real_settings, groq_api_key=None)
    with patch("gst_agent.llm_providers.groq_provider.settings", unconfigured):
        try:
            GroqProvider().classify(title="t", text="x", active_categories=["Order"])
            assert False, "expected an exception"
        except Exception:
            pass
