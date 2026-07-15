"""Tests for Subtitle Pydantic schemas.

Spec: docs-internal/superpowers/specs/M35-overview.md §5
"""
import pytest
from pydantic import ValidationError

from lumen_schemas.subtitle import SubtitleCreate, SubtitleRead


def test_create_minimal():
    s = SubtitleCreate(script="hello world", total_duration_ms=5000)
    assert s.language == "zh-CN"
    assert s.tts_job_id is None


def test_create_duration_too_small():
    with pytest.raises(ValidationError):
        SubtitleCreate(script="x", total_duration_ms=500)


def test_create_duration_too_large():
    with pytest.raises(ValidationError):
        SubtitleCreate(script="x", total_duration_ms=24 * 60 * 60 * 1000 + 1)


def test_create_script_required():
    with pytest.raises(ValidationError):
        SubtitleCreate(script="", total_duration_ms=5000)


def test_create_with_tts_job_id():
    s = SubtitleCreate(script="x", total_duration_ms=5000, tts_job_id=99)
    assert s.tts_job_id == 99