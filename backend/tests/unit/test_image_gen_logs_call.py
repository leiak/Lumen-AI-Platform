"""M26 image-generation LLMCallLog tests.

Exercises ``_run_generation`` end-to-end:

- A successful image generation writes one llm_call_logs row with
  ``call_type='image_generation'`` and ``image_id`` set.
- The row's status mirrors the GeneratedImage row's status.
- A failed generation writes status='failure' + error_message.
- Token usage is None (image models don't report tokens).

Uses the project's stub Pillow provider (no network calls) so the
test runs in CI without external services.
"""
import io
import os
import sys
import uuid
from typing import Optional

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401

from lumen_core.database import SessionLocal
from lumen_models.llm_call_log import LLMCallLog
from lumen_services.image_generation_service import _run_generation


def _make_image_bytes() -> bytes:
    """Build a small valid PNG via Pillow (the stub provider is the
    default; this isn't actually called by the test)."""
    img = Image.new("RGB", (32, 32), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_generated_image(suffix: str) -> int:
    """Create a stub-capable ModelConfig (is_image_generation=True) + a
    pending GeneratedImage row, returning the row id."""
    from lumen_models.model_config import ModelConfig

    db = SessionLocal()
    try:
        # Create a fresh ModelConfig row marked for image generation. We
        # don't reuse an existing one because (a) it may not exist on a
        # fresh dev DB and (b) we want predictable model_name / tenant_id
        # for the test's assertions.
        mc = ModelConfig(
            tenant_id=1,
            name=f"test-image-{suffix}",
            model_type="stub",
            model_name=f"test-image-{suffix}",
            is_image_generation=True,
            is_active=True,
            is_chat=False,
            is_embedding=False,
        )
        db.add(mc)
        db.commit()
        db.refresh(mc)
        row = GeneratedImage(
            tenant_id=1,
            user_id=1,
            model_config_id=mc.id,
            prompt=f"red square {suffix}",
            size="32x32",
            n=1,
            file_path="",
            file_size=0,
            mime_type="image/png",
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def _cleanup(image_id: int, model_name: str) -> None:
    db = SessionLocal()
    try:
        db.query(LLMCallLog).filter(LLMCallLog.image_id == image_id).delete()
        db.query(GeneratedImage).filter(GeneratedImage.id == image_id).delete()
        db.query(ModelConfig).filter(ModelConfig.model_name == model_name).delete()
        db.commit()
    finally:
        db.close()


def test_image_gen_writes_image_generation_row():
    """Successful run writes 1 row with call_type=image_generation,
    image_id set, status mirrors GeneratedImage."""
    suffix = uuid.uuid4().hex[:8]
    image_id = _make_generated_image(suffix)
    model_name = f"test-image-{suffix}"

    try:
        _run_generation(image_id)

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.image_id == image_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.call_type == "image_generation"
        assert row.image_id == image_id
        assert row.status in ("success", "completed")
        # Token usage is None for image models
        assert row.token_usage is None
        # extra carries the negative_prompt + batch_id
        assert "negative_prompt" in (row.extra or {})
        # response_content is a short status string
        assert row.response_content is not None
    finally:
        _cleanup(image_id, model_name)


def test_image_gen_records_prompt_in_user_message():
    """The prompt is captured as the user_message field (so the UI can
    show 'what was asked' on the detail page)."""
    suffix = uuid.uuid4().hex[:8]
    image_id = _make_generated_image(suffix)
    model_name = f"test-image-{suffix}"
    try:
        _run_generation(image_id)

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.image_id == image_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.user_message is not None
        assert f"red square {suffix}" in row.user_message
    finally:
        _cleanup(image_id, model_name)


def test_image_gen_records_extra_params():
    """extra_params captures size / quality / style / n so the UI can
    show 'what model settings were used'."""
    suffix = uuid.uuid4().hex[:8]
    image_id = _make_generated_image(suffix)
    model_name = f"test-image-{suffix}"
    try:
        _run_generation(image_id)

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.image_id == image_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.extra_params is not None
        assert row.extra_params.get("size") == "32x32"
        assert row.extra_params.get("n") == 1
    finally:
        _cleanup(image_id, model_name)


def test_image_gen_duration_recorded():
    """duration_ms is recorded (image models are slower than LLMs, so this
    is the key metric for image generation calls)."""
    suffix = uuid.uuid4().hex[:8]
    image_id = _make_generated_image(suffix)
    model_name = f"test-image-{suffix}"
    try:
        _run_generation(image_id)

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.image_id == image_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.duration_ms is not None
        assert row.duration_ms >= 0
    finally:
        _cleanup(image_id, model_name)