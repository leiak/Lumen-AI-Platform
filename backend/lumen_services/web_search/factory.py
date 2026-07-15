"""Factory that returns the configured web search provider singleton.

Selection is env-driven (`WEB_SEARCH_PROVIDER`); unknown values fall back
to DuckDuckGo with a warning. Add new branches here when introducing
Tavily/Bocha providers.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from .provider import WebSearchProvider

logger = logging.getLogger(__name__)

_instance: Optional[WebSearchProvider] = None


def get_web_search_provider() -> WebSearchProvider:
    """Return the singleton web search provider chosen by env."""
    global _instance
    if _instance is not None:
        return _instance

    name = (os.getenv("WEB_SEARCH_PROVIDER") or "duckduckgo").strip().lower()
    if name == "duckduckgo":
        from .duckduckgo import DuckDuckGoProvider
        _instance = DuckDuckGoProvider()
    else:
        logger.warning(
            "Unknown WEB_SEARCH_PROVIDER=%r; falling back to duckduckgo", name
        )
        from .duckduckgo import DuckDuckGoProvider
        _instance = DuckDuckGoProvider()

    return _instance
