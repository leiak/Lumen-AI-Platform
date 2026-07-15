"""Unit tests for ModelConfig schema with the new is_chat/is_embedding flags."""
import pytest
from pydantic import ValidationError

from lumen_schemas.model_config import (
    ModelConfigCreate, ModelConfigUpdate, ModelConfigResponse,
)


def test_create_defaults_is_chat_true_is_embedding_false():
    """Defaults match legacy ModelConfig rows that pre-date the flags."""
    cfg = ModelConfigCreate(
        name="x", model_type="ollama", model_name="qwen2.5:7b",
    )
    assert cfg.is_chat is True
    assert cfg.is_embedding is False


def test_create_accepts_explicit_both_true():
    """Multimodal-style model that's both chat and embedding."""
    cfg = ModelConfigCreate(
        name="x", model_type="ollama", model_name="some-multi",
        is_chat=True, is_embedding=True,
    )
    assert cfg.is_chat is True
    assert cfg.is_embedding is True


def test_update_partial_keeps_none_for_omitted_fields():
    """ModelConfigUpdate allows partial updates; omitted fields are None."""
    upd = ModelConfigUpdate(temperature=0.3)
    assert upd.temperature == 0.3
    assert upd.is_chat is None
    assert upd.is_embedding is None


def test_response_includes_flags():
    """ModelConfigResponse must serialize is_chat/is_embedding for the UI."""
    resp = ModelConfigResponse(
        id=1, name="x", model_type="ollama", model_name="q",
        is_chat=True, is_embedding=True, is_active=True, is_default=False,
        temperature=0.7, max_tokens=4096, timeout=120, tenant_id=1,
        created_at="2026-06-06T00:00:00", updated_at="2026-06-06T00:00:00",
    )
    assert resp.is_chat is True
    assert resp.is_embedding is True


def test_response_coerces_is_default_none_to_false():
    """Regression: legacy / script-inserted rows can have is_default=NULL
    in MySQL. The schema validator must coerce None → False so the list
    endpoint stays 200 instead of raising ValidationError → 500 (which
    left the admin page blank until the dev restarted uvicorn).
    """
    resp = ModelConfigResponse(
        id=571, name="legacy-img-model", model_type="minimax",
        model_name="stub-image-1",
        is_chat=False, is_embedding=False, is_image_generation=True,
        is_active=True, is_default=None,  # ← the legacy NULL
        temperature=0.7, max_tokens=4096, timeout=120, tenant_id=1,
        created_at="2026-06-06T00:00:00", updated_at="2026-06-06T00:00:00",
    )
    # Coerced to bool False; the frontend `is_default` Tag stays the
    # same (renders `-` for both False and None).
    assert resp.is_default is False
    assert isinstance(resp.is_default, bool)
