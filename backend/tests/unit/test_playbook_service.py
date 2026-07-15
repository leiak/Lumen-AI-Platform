"""Tests for PlaybookService — YAML loading, validation, prompt injection.

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
import pytest

from lumen_services.playbook_service import (
    load_yaml,
    inject_into_prompt,
    validate_scope,
    PlaybookValidationError,
)


# ---- load_yaml --------------------------------------------------------------

def test_load_yaml_minimal():
    """YAML with just keywords parses cleanly."""
    parsed = load_yaml("keywords:\n  - cinematic\n  - moody\n")
    assert "keywords" in parsed
    assert parsed["keywords"] == ["cinematic", "moody"]


def test_load_yaml_empty_raises():
    with pytest.raises(PlaybookValidationError) as exc_info:
        load_yaml("")
    assert exc_info.value.field == "yaml_content"


def test_load_yaml_invalid_yaml_raises():
    with pytest.raises(PlaybookValidationError):
        load_yaml("keywords: [unclosed")


def test_load_yaml_root_must_be_mapping():
    with pytest.raises(PlaybookValidationError) as exc_info:
        load_yaml("- just\n- a\n- list\n")
    assert exc_info.value.field == "yaml_content"


def test_load_yaml_no_useful_keys_raises():
    """Empty / non-style playbook rejected."""
    with pytest.raises(PlaybookValidationError):
        load_yaml("description: just text\n")


def test_load_yaml_keywords_must_be_list():
    with pytest.raises(PlaybookValidationError):
        load_yaml("keywords: not_a_list\n")


def test_load_yaml_keywords_items_must_be_strings():
    with pytest.raises(PlaybookValidationError):
        load_yaml("keywords:\n  - 123\n  - ok\n")


# ---- inject_into_prompt ----------------------------------------------------

def test_inject_keywords_for_image():
    pb = {"keywords": ["cinematic", "blue"]}
    out = inject_into_prompt(pb, "a cat", target="image_prompt")
    assert "a cat" in out
    assert "cinematic" in out
    assert "blue" in out


def test_inject_palette_for_image():
    pb = {"keywords": ["warm"], "palette": {"primary": ["#FF6B35", "#004E89"]}}
    out = inject_into_prompt(pb, "a cat", target="image_prompt")
    assert "#FF6B35" in out


def test_inject_avoid_for_image():
    pb = {"avoid": ["watermarks", "blurry"]}
    out = inject_into_prompt(pb, "a cat", target="image_prompt")
    assert "watermarks" in out
    assert "Avoid:" in out


def test_inject_voice_direction_for_tts():
    pb = {"voice_direction": "warm, slow", "voice_tone": "gentle"}
    out = inject_into_prompt(pb, "Hello", target="tts_prompt")
    assert "warm, slow" in out
    assert "gentle" in out


def test_inject_voice_speed_for_tts():
    pb = {"voice_speed": 0.85}
    out = inject_into_prompt(pb, "Hello", target="tts_prompt")
    assert "0.85x" in out


def test_inject_no_tokens_returns_base():
    pb = {}
    assert inject_into_prompt(pb, "Hello", target="image_prompt") == "Hello"


def test_inject_unknown_target_raises():
    pb = {"keywords": ["x"]}
    with pytest.raises(ValueError):
        inject_into_prompt(pb, "x", target="video_prompt")  # type: ignore[arg-type]


# ---- validate_scope --------------------------------------------------------

def test_validate_scope_default_true():
    """No scope set → applies to both image and tts."""
    pb = {"keywords": ["x"]}
    assert validate_scope(pb, "image") is True
    assert validate_scope(pb, "tts") is True


def test_validate_scope_explicit_match():
    pb = {"scope": ["image"]}
    assert validate_scope(pb, "image") is True
    assert validate_scope(pb, "tts") is False


def test_validate_scope_explicit_multi():
    pb = {"scope": ["image", "tts", "video"]}
    assert validate_scope(pb, "image") is True
    assert validate_scope(pb, "tts") is True
    assert validate_scope(pb, "video") is True