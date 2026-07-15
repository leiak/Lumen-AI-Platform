"""Tests for TTS provider factory + stub.

Spec: docs-internal/superpowers/specs/M35-overview.md §3
"""
import asyncio

import pytest

from lumen_services.tts_providers.factory import get_tts_provider
from lumen_services.tts_providers.stub_provider import StubTTSProvider
from lumen_services.tts_providers.edge_provider import EdgeTTSProvider
from lumen_services.tts_providers.piper_provider import PiperTTSProvider
from lumen_services.tts_providers.openai_provider import OpenAITTSProvider


class _MC:
    """Tiny ModelConfig stand-in — only model_type matters for routing."""

    def __init__(self, t):
        self.model_type = t


# ---- factory routing --------------------------------------------------------

def test_factory_edge():
    assert isinstance(get_tts_provider(_MC("edge")), EdgeTTSProvider)


def test_factory_piper():
    assert isinstance(get_tts_provider(_MC("piper")), PiperTTSProvider)


def test_factory_openai():
    assert isinstance(get_tts_provider(_MC("openai")), OpenAITTSProvider)


def test_factory_default_is_stub():
    assert isinstance(get_tts_provider(_MC("unknown")), StubTTSProvider)
    assert isinstance(get_tts_provider(_MC("")), StubTTSProvider)


def test_factory_case_insensitive():
    assert isinstance(get_tts_provider(_MC("EDGE")), EdgeTTSProvider)
    assert isinstance(get_tts_provider(_MC("Piper")), PiperTTSProvider)


# ---- stub provider ----------------------------------------------------------

def test_stub_provider_synthesize_returns_valid_wav():
    """Stub returns a non-empty WAV byte string."""
    async def _go():
        provider = StubTTSProvider(_MC("stub"))
        data = await provider.synthesize(text="hello")
        return data

    data = asyncio.run(_go())
    assert isinstance(data, bytes)
    assert len(data) > 0
    # WAV magic: "RIFF" at offset 0, "WAVE" at offset 8
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


def test_stub_provider_estimate_cost_zero():
    """Stub is free."""
    provider = StubTTSProvider(_MC("stub"))
    assert provider.estimate_cost(100) == 0.0
    assert provider.estimate_cost(100000) == 0.0


def test_stub_provider_list_voices():
    """Stub exposes at least one default voice."""
    provider = StubTTSProvider(_MC("stub"))
    voices = provider.list_voices()
    assert len(voices) >= 1
    assert "id" in voices[0]
    assert "language" in voices[0]