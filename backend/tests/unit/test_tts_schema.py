"""Tests for TTS Pydantic schemas.

Spec: docs-internal/superpowers/specs/M35-overview.md §6
"""
import pytest
from pydantic import ValidationError

from lumen_schemas.tts import TTSJobCreate, TTSJobRead, TTSJobListItem, TTSVoiceItem


def test_create_minimal():
    s = TTSJobCreate(model_config_id=1, text="hello")
    assert s.voice == "default"
    assert s.speed == 1.0
    assert s.format == "mp3"
    assert s.playbook_id is None


def test_create_text_required():
    with pytest.raises(ValidationError):
        TTSJobCreate(model_config_id=1, text="")


def test_create_text_too_long():
    with pytest.raises(ValidationError):
        TTSJobCreate(model_config_id=1, text="x" * 10001)


def test_create_speed_out_of_range():
    with pytest.raises(ValidationError):
        TTSJobCreate(model_config_id=1, text="x", speed=0.1)
    with pytest.raises(ValidationError):
        TTSJobCreate(model_config_id=1, text="x", speed=5.0)


def test_create_format_literal():
    """`format` is a Literal; invalid values raise."""
    with pytest.raises(ValidationError):
        TTSJobCreate(model_config_id=1, text="x", format="wma")  # type: ignore[arg-type]


def test_create_with_playbook_id():
    s = TTSJobCreate(
        model_config_id=1, text="x", voice="zh-CN-XiaoxiaoNeural",
        playbook_id=42,
    )
    assert s.playbook_id == 42
    assert s.voice == "zh-CN-XiaoxiaoNeural"


def test_voice_item_shape():
    v = TTSVoiceItem(id="zh-CN-XiaoxiaoNeural", name="晓晓", language="zh-CN", gender="female")
    assert v.id == "zh-CN-XiaoxiaoNeural"
    assert v.gender == "female"