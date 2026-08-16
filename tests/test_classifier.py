from unittest.mock import patch

from gst_agent import classifier
from gst_agent.models import LLMClassification


def test_uses_source_hint_when_not_other():
    category, confident = classifier.classify_rule_based(
        text="irrelevant", title="irrelevant", source_hint_category="Circular"
    )
    assert category == "Circular"
    assert confident is True


def test_falls_back_to_text_patterns_when_hint_is_other():
    text = (
        "In exercise of the powers conferred by section 164, the Central "
        "Government hereby makes the following rules further to amend the "
        "Central Goods and Services Tax Rules, 2017."
    )
    category, confident = classifier.classify_rule_based(
        text=text, title="Some title", source_hint_category="Other"
    )
    assert category == "Rule"
    assert confident is True


def test_returns_other_when_nothing_matches():
    category, confident = classifier.classify_rule_based(
        text="no legal boilerplate here at all", title="mystery doc", source_hint_category="Other"
    )
    assert category == "Other"
    assert confident is False


def test_llm_fallback_disabled_by_default_returns_none():
    # ENABLE_LLM_FALLBACK defaults to False -- no patching needed to prove
    # the fallback stays off unless explicitly enabled.
    result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])
    assert result is None


def test_llm_fallback_matches_an_existing_category():
    fake_settings = type("S", (), {"enable_llm_fallback": True})()
    fake_result = LLMClassification(matched_category="Order", proposed_category=None)

    with patch("gst_agent.classifier.settings", fake_settings), \
         patch("gst_agent.llm_client.classify_document", return_value=fake_result):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result.matched_category == "Order"
    assert result.proposed_category is None


def test_llm_fallback_proposes_a_new_category():
    fake_settings = type("S", (), {"enable_llm_fallback": True})()
    fake_result = LLMClassification(matched_category=None, proposed_category="Advisory")

    with patch("gst_agent.classifier.settings", fake_settings), \
         patch("gst_agent.llm_client.classify_document", return_value=fake_result):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result.matched_category is None
    assert result.proposed_category == "Advisory"


def test_llm_fallback_swallows_errors_instead_of_raising():
    fake_settings = type("S", (), {"enable_llm_fallback": True})()

    with patch("gst_agent.classifier.settings", fake_settings), \
         patch("gst_agent.llm_client.classify_document", side_effect=RuntimeError("boom")):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result is None
