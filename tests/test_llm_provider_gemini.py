import dataclasses
import json
from unittest.mock import MagicMock, patch

from gst_agent.config import settings as real_settings
from gst_agent.llm_providers.gemini import GeminiProvider


def _configured_settings(**overrides):
    return dataclasses.replace(real_settings, gemini_api_key="fake-key", **overrides)


def test_is_configured_reflects_api_key():
    with patch("gst_agent.llm_providers.gemini.settings", _configured_settings()):
        assert GeminiProvider().is_configured() is True
    with patch("gst_agent.llm_providers.gemini.settings", dataclasses.replace(real_settings, gemini_api_key=None)):
        assert GeminiProvider().is_configured() is False


def test_classify_matches_active_category():
    fake_response = MagicMock()
    fake_response.text = json.dumps({"matched_category": "Circular", "proposed_category": ""})
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("gst_agent.llm_providers.gemini.settings", _configured_settings()), \
         patch("gst_agent.llm_providers.gemini.genai.Client", return_value=fake_client):
        result = GeminiProvider().classify(
            title="t", text="x", active_categories=["Circular", "Order"]
        )

    assert result.matched_category == "Circular"
    assert result.proposed_category is None
    # Structured output must actually be requested, not left to luck.
    _, kwargs = fake_client.models.generate_content.call_args
    assert kwargs["config"]["response_mime_type"] == "application/json"


def test_classify_proposes_new_category_on_none_match():
    fake_response = MagicMock()
    fake_response.text = json.dumps({"matched_category": "NONE", "proposed_category": "Advisory"})
    fake_client = MagicMock()
    fake_client.models.generate_content.return_value = fake_response

    with patch("gst_agent.llm_providers.gemini.settings", _configured_settings()), \
         patch("gst_agent.llm_providers.gemini.genai.Client", return_value=fake_client):
        result = GeminiProvider().classify(title="t", text="x", active_categories=["Order"])

    assert result.matched_category is None
    assert result.proposed_category == "Advisory"


def test_classify_raises_when_not_configured():
    unconfigured = dataclasses.replace(real_settings, gemini_api_key=None)
    with patch("gst_agent.llm_providers.gemini.settings", unconfigured):
        try:
            GeminiProvider().classify(title="t", text="x", active_categories=["Order"])
            assert False, "expected an exception"
        except Exception:
            pass
