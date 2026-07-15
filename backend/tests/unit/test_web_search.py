"""Unit tests for the web search provider package."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestDuckDuckGoProvider:
    def test_search_returns_results_normalized(self):
        """DDG raw results should be mapped to SearchResult fields."""
        from lumen_services.web_search.duckduckgo import DuckDuckGoProvider

        # ddgs 9.x text() returns list[dict]; duckduckgo_search 8.x returned
        # a generator. We test against the new contract.
        fake_raw = [
            {"title": "T1", "href": "https://a.example", "body": "S1"},
            {"title": "T2", "href": "https://b.example", "body": "S2"},
        ]
        fake_ddgs = MagicMock()
        fake_ddgs.text.return_value = fake_raw
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)

        with patch("lumen_services.web_search.duckduckgo.DDGS", return_value=fake_ddgs):
            provider = DuckDuckGoProvider()
            results = provider.search("hello", max_results=5)

        assert len(results) == 2
        assert results[0].title == "T1"
        assert results[0].url == "https://a.example"
        assert results[0].snippet == "S1"
        assert results[1].title == "T2"
        assert fake_ddgs.text.call_args.kwargs.get("max_results") == 5

    def test_search_empty_results_returns_empty_list(self):
        """Provider should return [] when DDG returns nothing — never raise."""
        from lumen_services.web_search.duckduckgo import DuckDuckGoProvider

        fake_ddgs = MagicMock()
        fake_ddgs.text.return_value = []
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)

        with patch("lumen_services.web_search.duckduckgo.DDGS", return_value=fake_ddgs):
            results = DuckDuckGoProvider().search("nothing")

        assert results == []

    def test_constructor_passes_timeout_to_ddgs(self):
        """ddgs requires a non-default timeout for slow / blocked networks.
        The provider must forward a reasonable timeout to DDGS().
        """
        from lumen_services.web_search.duckduckgo import DuckDuckGoProvider

        fake_ddgs = MagicMock()
        fake_ddgs.__enter__ = MagicMock(return_value=fake_ddgs)
        fake_ddgs.__exit__ = MagicMock(return_value=False)
        fake_ddgs.text.return_value = []

        with patch("lumen_services.web_search.duckduckgo.DDGS", return_value=fake_ddgs) as ddgs_cls:
            DuckDuckGoProvider().search("q")

        # timeout must be a positive int — confirms we set it (not relying
        # on ddgs's 10s default, which is too short for backup backends).
        kwargs = ddgs_cls.call_args.kwargs
        assert "timeout" in kwargs
        assert kwargs["timeout"] >= 10


class TestGetWebSearchProvider:
    def setup_method(self):
        # Reset module-level singleton between tests
        import lumen_services.web_search.factory as factory_mod
        factory_mod._instance = None

    def test_default_provider_is_duckduckgo(self, monkeypatch):
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        from lumen_services.web_search.factory import get_web_search_provider
        from lumen_services.web_search.duckduckgo import DuckDuckGoProvider

        p = get_web_search_provider()
        assert isinstance(p, DuckDuckGoProvider)

    def test_unknown_provider_falls_back_to_duckduckgo(self, monkeypatch):
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "does-not-exist")
        from lumen_services.web_search.factory import get_web_search_provider
        from lumen_services.web_search.duckduckgo import DuckDuckGoProvider

        p = get_web_search_provider()
        assert isinstance(p, DuckDuckGoProvider)

    def test_factory_returns_singleton(self, monkeypatch):
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        from lumen_services.web_search.factory import get_web_search_provider

        p1 = get_web_search_provider()
        p2 = get_web_search_provider()
        assert p1 is p2
