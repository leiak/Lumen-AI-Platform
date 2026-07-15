"""Tests for image_providers package — T7 covers factory routing.

Spec: §7.1
"""
import pytest

from lumen_services.image_providers.factory import get_image_provider
from lumen_services.image_providers.stub_provider import StubImageProvider
from lumen_services.image_providers.openai_provider import OpenAIImageProvider
from lumen_services.image_providers.stability_provider import StabilityImageProvider
from lumen_services.image_providers.ollama_provider import OllamaImageProvider
from lumen_services.image_providers.minimax_provider import MiniMaxImageProvider


class _MC:
    """Tiny ModelConfig stand-in — only model_type matters for routing."""

    def __init__(self, t):
        self.model_type = t


def test_factory_openai():
    assert isinstance(get_image_provider(_MC("openai")), OpenAIImageProvider)


def test_factory_stability():
    assert isinstance(get_image_provider(_MC("stability")), StabilityImageProvider)


def test_factory_ollama():
    assert isinstance(get_image_provider(_MC("ollama")), OllamaImageProvider)


def test_factory_minimax():
    assert isinstance(get_image_provider(_MC("minimax")), MiniMaxImageProvider)


def test_factory_default_is_stub():
    assert isinstance(get_image_provider(_MC("unknown")), StubImageProvider)
    assert isinstance(get_image_provider(_MC("")), StubImageProvider)


def test_openai_stub_raises_not_implemented():
    """Stubs should not silently succeed — caller must catch NotImplementedError."""

    async def _go():
        return await OpenAIImageProvider(_MC("openai")).generate(prompt="x")

    with pytest.raises(NotImplementedError):
        # pytest-asyncio if configured, else just run the coroutine
        try:
            import asyncio

            asyncio.run(_go())
        except NotImplementedError:
            raise
        else:
            raise AssertionError("Expected NotImplementedError")


def test_stability_stub_raises_not_implemented():
    async def _go():
        return await StabilityImageProvider(_MC("stability")).generate(prompt="x")

    with pytest.raises(NotImplementedError):
        import asyncio

        asyncio.run(_go())


def test_ollama_stub_raises_not_implemented():
    async def _go():
        return await OllamaImageProvider(_MC("ollama")).generate(prompt="x")

    with pytest.raises(NotImplementedError):
        import asyncio

        asyncio.run(_go())
