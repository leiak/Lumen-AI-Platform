"""Web search provider package.

Public API:
    get_web_search_provider() -> WebSearchProvider
    SearchResult
    WebSearchProvider
"""
from .provider import SearchResult, WebSearchProvider

__all__ = ["SearchResult", "WebSearchProvider", "get_web_search_provider"]


def __getattr__(name):
    """Lazy attribute access for forward references (PEP 562).

    `get_web_search_provider` lives in `factory.py`, which is added in a
    later task. Resolving it lazily keeps the package importable even
    when the factory module is not yet present.
    """
    if name == "get_web_search_provider":
        from .factory import get_web_search_provider
        return get_web_search_provider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
