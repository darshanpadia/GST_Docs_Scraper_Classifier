"""Common interface every LLM provider implements."""
from __future__ import annotations

from abc import ABC, abstractmethod

from gst_agent.models import LLMClassification


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider has the API key it needs to be called."""

    @abstractmethod
    def classify(
        self, *, title: str, text: str, active_categories: list[str]
    ) -> LLMClassification:
        """Raise on any failure (missing key, network error, refusal, bad
        response) -- callers are responsible for catching, logging, and
        falling through to the next provider."""
