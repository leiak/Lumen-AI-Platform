from datetime import datetime
from lumen_schemas.model_config import ModelConfigResponse, ModelConfigCreate, ModelConfigUpdate
from lumen_models.model_config import ModelConfig


def test_schema_includes_image_generation():
    s = ModelConfigResponse(
        id=1, name="x", model_type="openai", model_name="gpt-4o",
        is_chat=True, is_embedding=False, is_image_generation=True,
        is_active=True, tenant_id=None,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
    )
    assert s.is_image_generation is True


def test_schema_default_is_false():
    s = ModelConfigResponse(
        id=2, name="y", model_type="openai", model_name="gpt-4",
        is_active=True, tenant_id=None,
        created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
    )
    assert s.is_image_generation is False


def test_create_schema_includes_image_generation():
    s = ModelConfigCreate(
        name="dall-e", model_type="openai", model_name="dall-e-3",
        is_image_generation=True,
    )
    assert s.is_image_generation is True


def test_update_schema_accepts_image_generation():
    s = ModelConfigUpdate(is_image_generation=True)
    assert s.is_image_generation is True


def test_model_has_image_generation_column():
    # The ORM model must expose the column so the read schema can read it.
    assert hasattr(ModelConfig, "is_image_generation")
    col = ModelConfig.is_image_generation
    # Column default should be False at the DB level.
    assert col.default.arg is False
