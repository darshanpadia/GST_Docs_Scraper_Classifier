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


class _FakeProvider:
    def __init__(self, name, *, configured=True, result=None, error=None):
        self.name = name
        self._configured = configured
        self._result = result
        self._error = error

    def is_configured(self):
        return self._configured

    def classify(self, *, title, text, active_categories):
        if self._error is not None:
            raise self._error
        return self._result


_ENABLED = type("S", (), {"enable_llm_fallback": True})()


def test_llm_fallback_disabled_returns_none_without_calling_any_provider():
    # Explicitly mocked to enable_llm_fallback=False -- must NOT rely on
    # that being the ambient default. A developer's own .env can (and, in
    # this project's real one, does) set ENABLE_LLM_FALLBACK=true with real
    # API keys; a test that assumes otherwise silently starts making real
    # network calls to a real LLM provider instead of testing anything.
    disabled = type("S", (), {"enable_llm_fallback": False})()
    with patch("gst_agent.classifier.settings", disabled), \
         patch("gst_agent.llm_providers.get_ordered_providers") as mock_get_providers:
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result is None
    mock_get_providers.assert_not_called()


def test_llm_fallback_matches_an_existing_category():
    provider = _FakeProvider("p", result=LLMClassification(matched_category="Order", proposed_category=None))

    with patch("gst_agent.classifier.settings", _ENABLED), \
         patch("gst_agent.llm_providers.get_ordered_providers", return_value=[provider]):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result.matched_category == "Order"
    assert result.proposed_category is None


def test_llm_fallback_proposes_a_new_category():
    provider = _FakeProvider("p", result=LLMClassification(matched_category=None, proposed_category="Advisory"))

    with patch("gst_agent.classifier.settings", _ENABLED), \
         patch("gst_agent.llm_providers.get_ordered_providers", return_value=[provider]):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result.matched_category is None
    assert result.proposed_category == "Advisory"


def test_llm_fallback_swallows_errors_instead_of_raising():
    provider = _FakeProvider("p", error=RuntimeError("boom"))

    with patch("gst_agent.classifier.settings", _ENABLED), \
         patch("gst_agent.llm_providers.get_ordered_providers", return_value=[provider]):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result is None


def test_llm_fallback_falls_through_to_the_next_configured_provider():
    # The whole point of a provider chain: one free API's outage/rate limit
    # doesn't take the fallback down as long as another configured provider
    # can still answer.
    failing = _FakeProvider("gemini", error=RuntimeError("rate limited"))
    working = _FakeProvider("groq", result=LLMClassification(matched_category="Order", proposed_category=None))

    with patch("gst_agent.classifier.settings", _ENABLED), \
         patch("gst_agent.llm_providers.get_ordered_providers", return_value=[failing, working]):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Order"])

    assert result.matched_category == "Order"


def test_llm_fallback_skips_unconfigured_providers_without_calling_them():
    unconfigured = _FakeProvider("gemini", configured=False, error=AssertionError("should not be called"))
    working = _FakeProvider("groq", result=LLMClassification(matched_category="Circular", proposed_category=None))

    with patch("gst_agent.classifier.settings", _ENABLED), \
         patch("gst_agent.llm_providers.get_ordered_providers", return_value=[unconfigured, working]):
        result = classifier.classify_with_llm(text="x", title="y", active_categories=["Circular"])

    assert result.matched_category == "Circular"
