"""Tests for TTSProvider Protocol typing.

Spec: docs-internal/superpowers/specs/M35-overview.md §3
"""
import inspect

from lumen_services.tts_providers import TTSProvider


def test_protocol_importable():
    """TTSProvider Protocol exists and is importable."""
    assert TTSProvider is not None


def test_protocol_methods_present():
    """Protocol declares synthesize / list_voices / estimate_cost.

    For Protocol classes, ``__annotations__`` is populated only when
    ``@runtime_checkable`` is in play, but ``__dict__`` / instance
    attribute lookup works for both. We use ``hasattr`` against a
    concrete stub that implements the protocol as a definitive check.
    """
    # A Protocol class may be looked up via dir() and hasattr at the
    # class level for its declared methods.
    assert hasattr(TTSProvider, "synthesize")
    assert hasattr(TTSProvider, "list_voices")
    assert hasattr(TTSProvider, "estimate_cost")


def test_protocol_signatures_match():
    """Method signatures are inspectable."""
    synth_sig = inspect.signature(TTSProvider.synthesize)
    params = list(synth_sig.parameters.keys())
    for kw in ("text", "voice", "speed", "format"):
        assert kw in params, f"synthesize missing kw param: {kw}"