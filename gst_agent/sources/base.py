"""Common interface every source module implements.

Adding a new official source later (a 5th GST-law site) means writing one
new class here and registering it in sources/__init__.py -- nothing in the
pipeline, database, or classifier needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from gst_agent.models import DiscoveredDoc


class DocumentSource(ABC):
    name: str

    @abstractmethod
    def discover(self) -> list[DiscoveredDoc]:
        """Return every document this source currently knows about.

        Implementations should not raise on partial failure (e.g. one seed
        page being down) -- log a warning and return what was successfully
        discovered from the other pages instead.
        """
