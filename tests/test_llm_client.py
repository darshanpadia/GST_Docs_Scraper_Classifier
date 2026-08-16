import json
from unittest.mock import MagicMock, patch

import pytest

from gst_agent import llm_client


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
    llm_client._client = None
    yield
    llm_client._client = None


def test_classify_document_matches_active_category():
    payload = {"matched_category": "Order", "proposed_category": ""}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(llm_client, "_get_client", return_value=fake_client):
        result = llm_client.classify_document(title="t", text="x", active_categories=["Order", "Circular"])

    assert result.matched_category == "Order"
    assert result.proposed_category is None


def test_classify_document_proposes_new_category_on_none_match():
    payload = {"matched_category": "NONE", "proposed_category": "Advisory"}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(llm_client, "_get_client", return_value=fake_client):
        result = llm_client.classify_document(title="t", text="x", active_categories=["Order"])

    assert result.matched_category is None
    assert result.proposed_category == "Advisory"


def test_classify_document_treats_hallucinated_category_as_no_match():
    # If the model names a category that isn't actually in the active list,
    # treat it as no match rather than silently filing under a bogus label.
    payload = {"matched_category": "Totally Made Up", "proposed_category": ""}
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(payload)

    with patch.object(llm_client, "_get_client", return_value=fake_client):
        result = llm_client.classify_document(title="t", text="x", active_categories=["Order"])

    assert result.matched_category is None


def test_classify_document_raises_on_refusal():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response({}, stop_reason="refusal")

    with patch.object(llm_client, "_get_client", return_value=fake_client):
        with pytest.raises(RuntimeError):
            llm_client.classify_document(title="t", text="x", active_categories=["Order"])
