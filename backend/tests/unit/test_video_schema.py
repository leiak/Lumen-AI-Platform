"""M36: Pydantic schema validation tests for VideoComposeCreate / Read / List."""
import pytest
from pydantic import ValidationError

from lumen_schemas.video import (
    VideoComposeCreate, VideoComposeRead, VideoComposeListItem,
)


def test_create_minimal_defaults():
    s = VideoComposeCreate(source_images=["/tmp/a.png"])
    assert s.resolution == "1280x720"
    assert s.fps == 24
    assert s.audio_path is None
    assert s.subtitle_path is None


def test_create_validates_resolution_regex():
    # Valid: WxH where W and H are digits
    assert VideoComposeCreate(source_images=["/tmp/a.png"], resolution="640x480").resolution == "640x480"
    assert VideoComposeCreate(source_images=["/tmp/a.png"], resolution="1920X1080").resolution == "1920X1080"
    # Invalid forms
    with pytest.raises(ValidationError):
        VideoComposeCreate(source_images=["/tmp/a.png"], resolution="not-a-resolution")
    with pytest.raises(ValidationError):
        VideoComposeCreate(source_images=["/tmp/a.png"], resolution="1280")


def test_create_rejects_fps_out_of_range():
    with pytest.raises(ValidationError):
        VideoComposeCreate(source_images=["/tmp/a.png"], fps=0)
    with pytest.raises(ValidationError):
        VideoComposeCreate(source_images=["/tmp/a.png"], fps=999)


def test_create_accepts_optional_audio_and_subtitle_path():
    """audio_path / subtitle_path are Optional[str] — accept None or strings."""
    s = VideoComposeCreate(
        source_images=["/tmp/a.png"],
        audio_path="/tmp/foo.mp3",
        subtitle_path=None,
    )
    assert s.audio_path == "/tmp/foo.mp3"
    assert s.subtitle_path is None


def test_read_passes_through_status_literal():
    """VideoStatus is a Literal; VideoComposeRead accepts the 5 valid values."""
    # Use model_validate with a dict so we don't need an ORM row.
    s = VideoComposeRead.model_validate({
        "id": 1, "tenant_id": 1, "user_id": 1,
        "conversation_id": None, "model_config_id": None,
        "playbook_id": None, "source_audio_id": None,
        "source_subtitle_id": None, "source_images": ["/tmp/a.png"],
        "resolution": "1280x720", "fps": 24,
        "file_path": "x.mp4", "file_size": 100, "mime_type": "video/mp4",
        "duration_ms": 4000, "status": "completed",
        "error_message": None, "started_at": None, "finished_at": None,
        "created_at": "2026-07-15T00:00:00", "updated_at": "2026-07-15T00:00:00",
    })
    assert s.status == "completed"


def test_read_rejects_invalid_status():
    with pytest.raises(ValidationError):
        VideoComposeRead.model_validate({
            "id": 1, "tenant_id": 1, "user_id": 1,
            "conversation_id": None, "model_config_id": None,
            "playbook_id": None, "source_audio_id": None,
            "source_subtitle_id": None, "source_images": [],
            "resolution": "1280x720", "fps": 24,
            "file_path": "x.mp4", "file_size": 100, "mime_type": "video/mp4",
            "duration_ms": 4000, "status": "weird-state",  # not in Literal
            "error_message": None, "started_at": None, "finished_at": None,
            "created_at": "2026-07-15T00:00:00", "updated_at": "2026-07-15T00:00:00",
        })
