"""Unit tests for the embedding_model_config_id field on KB schemas."""
import pytest
from pydantic import ValidationError

from lumen_schemas.knowledge import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
)


def test_create_requires_embedding_model_config_id():
    """Create must require the new FK field."""
    with pytest.raises(ValidationError) as ei:
        KnowledgeBaseCreate(name="kb1")
    assert "embedding_model_config_id" in str(ei.value)


def test_create_accepts_embedding_model_config_id():
    """Create with the new FK is valid."""
    kb = KnowledgeBaseCreate(name="kb1", embedding_model_config_id=7)
    assert kb.embedding_model_config_id == 7


def test_update_cannot_change_embedding_model_config_id():
    """Update schema must NOT expose embedding_model_config_id — it's locked."""
    fields = set(KnowledgeBaseUpdate.model_fields.keys())
    assert "embedding_model_config_id" not in fields


def test_response_serializes_both_fields():
    """Response must surface the FK and the legacy string for the UI."""
    resp = KnowledgeBaseResponse(
        id=1, name="kb1", tenant_id=1, embedding_model_config_id=7,
        embedding_model="nomic-embed-text",
        status="active",
        created_at="2026-06-06T00:00:00",
    )
    assert resp.embedding_model_config_id == 7
    assert resp.embedding_model == "nomic-embed-text"
