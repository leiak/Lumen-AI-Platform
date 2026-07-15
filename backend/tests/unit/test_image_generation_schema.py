import pytest
from pydantic import ValidationError
from lumen_schemas.image_generation import (
    ImageGenerationCreate, ImageGenerationListItem, ImageGenerationDetail,
)


def test_create_minimal():
    s = ImageGenerationCreate(model_config_id=1, prompt="cat")
    assert s.n == 1
    assert s.size == "1024x1024"


def test_create_n_out_of_range():
    with pytest.raises(ValidationError):
        ImageGenerationCreate(model_config_id=1, prompt="x", n=5)
    with pytest.raises(ValidationError):
        ImageGenerationCreate(model_config_id=1, prompt="x", n=0)


def test_create_prompt_too_long():
    with pytest.raises(ValidationError):
        ImageGenerationCreate(model_config_id=1, prompt="x" * 4001)


def test_create_with_extra_params():
    s = ImageGenerationCreate(
        model_config_id=1, prompt="x",
        extra_params={"seed": 42, "guidance_scale": 7.5},
    )
    assert s.extra_params == {"seed": 42, "guidance_scale": 7.5}
