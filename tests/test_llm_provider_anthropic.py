import json
from unittest.mock import MagicMock, patch

import pytest

from gst_agent.llm_providers import anthropic_provider


def _fake_response(payload: dict, *, stop_reason: str = "end_turn"):
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = stop_reason
    return response


@pytest.fixture(autouse=True)
def _reset_client_singleton():
    anthropic_provider._client = None
    yield
    anthropic_provider._client = None


def test_is_configured_reflects_env_var(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert anthropic_provider.AnthropicProvider().is_configured() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    assert anthropic_provider.AnthropicProvider().is_configured() is True


def test_classify_matches_active_category():
    payload = {"matched_category": "Order", "proposed_category": ""}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(anthropic_provider, "_get_client", return_value=fake_client):
        result = anthropic_provider.AnthropicProvider().classify(
            title="t", text="x", active_categories=["Order", "Circular"]
        )

    assert result.matched_category == "Order"
    assert result.proposed_category is None


def test_classify_proposes_new_category_on_none_match():
    payload = {"matched_category": "NONE", "proposed_category": "Advisory"}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(anthropic_provider, "_get_client", return_value=fake_client):
        result = anthropic_provider.AnthropicProvider().classify(
            title="t", text="x", active_categories=["Order"]
        )

    assert result.matched_category is None
    assert result.proposed_category == "Advisory"


def test_classify_treats_hallucinated_category_as_no_match():
    payload = {"matched_category": "Totally Made Up", "proposed_category": ""}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(anthropic_provider, "_get_client", return_value=fake_client):
        result = anthropic_provider.AnthropicProvider().classify(
            title="t", text="x", active_categories=["Order"]
        )

    assert result.matched_category is None


def test_classify_raises_on_refusal():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response({}, stop_reason="refusal")

    with patch.object(anthropic_provider, "_get_client", return_value=fake_client):
        with pytest.raises(RuntimeError):
            anthropic_provider.AnthropicProvider().classify(
                title="t", text="x", active_categories=["Order"]
            )
