"""Tests for StockMusic Pydantic schemas.

M36.2.2: validates ``StockMusicListItem`` / ``StockMusicDetail`` against a
real ORM row, ensuring the gallery / detail endpoints serialize
correctly.
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from lumen_schemas.stock_music import StockMusicDetail, StockMusicListItem


def _fake_row(**overrides):
    """Build a SimpleNamespace that mimics a StockMusic ORM row."""
    base = dict(
        id=1,
        name="舒缓钢琴",
        category="舒缓",
        description="Soft piano-like chord progression",
        mime_type="audio/mpeg",
        file_size=235000,
        duration_seconds=30.0,
        source="builtin",
        created_at=datetime(2026, 8, 7, 9, 0, 0),
        file_path="stock/music/mellow.mp3",
        tenant_id=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_list_item_minimum_required_fields():
    """StockMusicListItem only requires the columns surfaced in the list."""
    row = _fake_row()
    item = StockMusicListItem.model_validate(row)
    assert item.id == 1
    assert item.name == "舒缓钢琴"
    assert item.category == "舒缓"
    assert item.duration_seconds == 30.0
    assert item.source == "builtin"
    # file_path is NOT exposed on the list item (only on detail).
    assert not hasattr(item, "file_path")


def test_detail_includes_file_path_and_tenant_id():
    """StockMusicDetail adds file_path + tenant_id on top of the list shape."""
    row = _fake_row()
    detail = StockMusicDetail.model_validate(row)
    assert detail.id == 1
    assert detail.file_path == "stock/music/mellow.mp3"
    assert detail.tenant_id is None


def test_list_item_rejects_invalid_source():
    """``source`` is a Literal — unknown values must fail validation."""
    row = _fake_row(source="unknown_provider")
    with pytest.raises(ValidationError):
        StockMusicListItem.model_validate(row)


def test_optional_description_defaults_to_none():
    """description may be None for rows seeded without a long blurb."""
    row = _fake_row(description=None)
    item = StockMusicListItem.model_validate(row)
    assert item.description is None
