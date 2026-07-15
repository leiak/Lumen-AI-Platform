from pathlib import Path

from lumen_core.storage import save_bytes, delete_relative
from lumen_core.config import settings, Settings


def _patch_storage_dir(monkeypatch, new_path: Path) -> None:
    """Replace settings.STORAGE_DIR for the duration of one test.

    STORAGE_DIR is a @property on Settings (Pydantic v2 BaseSettings
    forbids setting instance attributes on properties), so we have to
    swap the descriptor on the class. monkeypatch undoes this on
    teardown, restoring the original property.
    """
    monkeypatch.setattr(Settings, "STORAGE_DIR", new_path)


def test_save_bytes_creates_file(tmp_path, monkeypatch):
    _patch_storage_dir(monkeypatch, tmp_path / "storage")
    abs_path, size, rel = save_bytes(tenant_id=1, data=b"hello", mime_type="image/png")
    assert abs_path.exists()
    assert size == 5
    assert rel.startswith("generated_images/1/")
    assert abs_path.suffix == ".png"


def test_delete_relative_missing_ok(tmp_path, monkeypatch):
    _patch_storage_dir(monkeypatch, tmp_path / "storage")
    delete_relative("nonexistent.png")  # must not raise
