"""Abstract web search provider interface.

The chat feature toggles design calls for a pluggable web search backend.
V1 ships DuckDuckGo (no API key) as the default; V2 will add Tavily and
Bocha. This file defines the contract every provider must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class SearchResult:
    """A single search result returned by a provider."""

    title: str
    url: str
    snippet: str


class WebSearchProvider(ABC):
    """Abstract base for web search backends."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Return up to `max_results` results for the given query.

        Implementations should:
        - Never raise for "no results" — return [] instead.
        - For transient backend errors, may raise; callers are expected
          to log and degrade silently.
        """
        raise NotImplementedError
