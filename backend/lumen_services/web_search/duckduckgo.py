"""DuckDuckGo web search provider (V1 default, no API key required).

Backed by the `ddgs` package (the actively maintained successor to the
deprecated `duckduckgo_search` package; the old package silently fell
back to Bing and got blocked by anti-bot defenses in many regions).
"""
from __future__ import annotations

import logging
from typing import List

from ddgs import DDGS

from .provider import SearchResult, WebSearchProvider

logger = logging.getLogger(__name__)

# Generous timeout: ddgs 9.x's default 10s is too short for backup
# backends (mojeek / startpage) that we may fall back to in regions
# where duckduckgo.com is blocked.
_DDGS_TIMEOUT = 30


class DuckDuckGoProvider(WebSearchProvider):
    """Web search backed by ddgs's text endpoint.

    ddgs 9.x tries multiple backends (DuckDuckGo, Mojeek, Startpage,
    Bing) via `backend='auto'`. Failures degrade silently — caller is
    responsible for distinguishing empty vs error via the contract on
    `_run_web_search` (see chat_features.ChatFeatureService).
    """

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        try:
            with DDGS(timeout=_DDGS_TIMEOUT) as ddgs:
                raw = ddgs.text(query, max_results=max_results)
        except Exception as e:  # noqa: BLE001 - propagate to caller
            logger.warning("DuckDuckGo search failed: %s", e)
            raise

        return [
            SearchResult(
                title=r.get("title", "") or "",
                url=r.get("href", "") or "",
                snippet=r.get("body", "") or "",
            )
            for r in raw
        ]
