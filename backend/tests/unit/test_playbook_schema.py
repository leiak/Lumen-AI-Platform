"""Tests for Playbook Pydantic schemas.

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
import pytest
from pydantic import ValidationError

from lumen_schemas.playbook import PlaybookCreate, PlaybookUpdate


def test_create_minimal():
    s = PlaybookCreate(name="my-style", yaml_content="keywords:\n  - cool\n")
    assert s.description is None
    assert s.scope == ["image", "tts"]


def test_create_name_required():
    with pytest.raises(ValidationError):
        PlaybookCreate(name="", yaml_content="keywords:\n  - x\n")


def test_create_name_too_long():
    with pytest.raises(ValidationError):
        PlaybookCreate(name="x" * 101, yaml_content="keywords:\n  - x\n")


def test_create_yaml_required():
    with pytest.raises(ValidationError):
        PlaybookCreate(name="x", yaml_content="")


def test_create_with_custom_scope():
    s = PlaybookCreate(
        name="image-only", yaml_content="keywords:\n  - x\n",
        scope=["image"],
    )
    assert s.scope == ["image"]


def test_update_partial_fields():
    """Update model allows partial fields; none required."""
    u = PlaybookUpdate()
    assert u.description is None
    assert u.yaml_content is None
    assert u.scope is None