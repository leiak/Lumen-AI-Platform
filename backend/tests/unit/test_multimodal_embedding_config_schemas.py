"""M38.4 Step 5a: Pydantic schemas for MultimodalEmbeddingConfig.

Covers:
- MultimodalEmbeddingConfigCreate accepts the documented provider set
  and rejects unknown providers
- MultimodalEmbeddingConfigUpdate is PATCH-style (every field optional)
- MultimodalEmbeddingConfigResponse round-trips an ORM-like dict via
  ``from_attributes=True``
- MultimodalConfigTestResponse: ``ok=True`` + dim; ``ok=False`` + error

These tests don't touch the DB — they're pure Pydantic validation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from lumen_schemas.multimodal_embedding_config import (
    MultimodalConfigTestResponse,
    MultimodalEmbeddingConfigCreate,
    MultimodalEmbeddingConfigResponse,
    MultimodalEmbeddingConfigUpdate,
)


# --- Create / Update --------------------------------------------------------


def test_create_accepts_all_providers():
    """All 6 documented provider values round-trip."""
    for prov in [
        "jina_clip_v2",
        "clip_base_32",
        "openai_vision",
        "qwen_vl",
        "nomic_v15",
        "azure_vision",
    ]:
        cfg = MultimodalEmbeddingConfigCreate(
            name=f"test-{prov}",
            provider=prov,  # type: ignore[arg-type]
            model_name="some-model",
        )
        assert cfg.provider == prov


def test_create_rejects_unknown_provider():
    """Unknown provider string fails Pydantic literal validation."""
    with pytest.raises(ValidationError):
        MultimodalEmbeddingConfigCreate(
            name="x",
            provider="bogus_provider",  # type: ignore[arg-type]
            model_name="x",
        )


def test_create_requires_minimum_fields():
    """Missing ``provider`` / ``model_name`` / ``name`` → ValidationError."""
    with pytest.raises(ValidationError):
        MultimodalEmbeddingConfigCreate()  # type: ignore[call-arg]


def test_create_accepts_optional_fields():
    """description / config / base_url / api_key / enabled / is_default all optional."""
    cfg = MultimodalEmbeddingConfigCreate(
        name="full",
        provider="jina_clip_v2",
        model_name="jinaai/jina-clip-v2",
        description="a desc",
        config={"revision": "abc123", "device": "cpu"},
        base_url="http://localhost",
        api_key="secret",
        enabled=False,
        is_default=True,
    )
    assert cfg.description == "a desc"
    assert cfg.config == {"revision": "abc123", "device": "cpu"}
    assert cfg.base_url == "http://localhost"
    assert cfg.api_key == "secret"
    assert cfg.enabled is False
    assert cfg.is_default is True


def test_update_all_fields_optional():
    """``Update`` is PATCH-style — empty body is valid (no-op)."""
    upd = MultimodalEmbeddingConfigUpdate()
    assert upd.model_dump(exclude_unset=True) == {}


def test_update_subset_only_writes_present_fields():
    """``exclude_unset`` only includes fields the caller sent."""
    upd = MultimodalEmbeddingConfigUpdate(name="new-name", enabled=False)
    dumped = upd.model_dump(exclude_unset=True)
    assert dumped == {"name": "new-name", "enabled": False}


def test_update_rejects_unknown_provider():
    """Same literal validation as Create."""
    with pytest.raises(ValidationError):
        MultimodalEmbeddingConfigUpdate(provider="not_real")  # type: ignore[arg-type]


def test_create_rejects_name_too_long():
    """``max_length=100`` on name."""
    with pytest.raises(ValidationError):
        MultimodalEmbeddingConfigCreate(
            name="x" * 101,
            provider="jina_clip_v2",
            model_name="x",
        )


def test_create_rejects_empty_name():
    """``min_length=1`` on name."""
    with pytest.raises(ValidationError):
        MultimodalEmbeddingConfigCreate(
            name="",
            provider="jina_clip_v2",
            model_name="x",
        )


# --- Response ---------------------------------------------------------------


def _orm_like_row() -> Dict[str, Any]:
    """Mimic what ``ModelConfig.model_validate`` would receive.

    Uses ``from_attributes=True`` so the response model reads from
    attributes (not keys). Build a tiny object that exposes those
    attributes.
    """

    class _Row:
        pass

    row = _Row()
    row.id = 42
    row.name = "jina-clip-v2 default"
    row.description = "test desc"
    row.provider = "jina_clip_v2"
    row.model_name = "jinaai/jina-clip-v2"
    row.config = {"revision": "abc"}
    row.base_url = None
    row.api_key = "secret"
    row.enabled = True
    row.is_default = True
    row.dimension = 1024
    row.tenant_id = None  # global builtin
    row.created_at = datetime(2026, 9, 1, 0, 0, 0)
    row.updated_at = datetime(2026, 9, 1, 0, 0, 0)
    return row


def test_response_from_attributes_round_trip():
    """``from_attributes=True`` reads from a row-like object."""
    resp = MultimodalEmbeddingConfigResponse.model_validate(_orm_like_row())
    assert resp.id == 42
    assert resp.provider == "jina_clip_v2"
    assert resp.dimension == 1024
    assert resp.tenant_id is None
    assert resp.created_at == datetime(2026, 9, 1, 0, 0, 0)


def test_response_dimension_optional():
    """``dimension`` can be None (pre first /test)."""
    row = _orm_like_row()
    row.dimension = None
    resp = MultimodalEmbeddingConfigResponse.model_validate(row)
    assert resp.dimension is None


# --- TestResponse -----------------------------------------------------------


def test_test_response_ok_shape():
    """Success path: ok=True, dim set, error None."""
    r = MultimodalConfigTestResponse(ok=True, dim=1024, elapsed_ms=234)
    assert r.ok is True
    assert r.dim == 1024
    assert r.elapsed_ms == 234
    assert r.error is None


def test_test_response_fail_shape():
    """Failure path: ok=False, error set, dim None."""
    r = MultimodalConfigTestResponse(ok=False, error="connection refused")
    assert r.ok is False
    assert r.dim is None
    assert r.error == "connection refused"
