from pathlib import Path

from lumen_core.config import settings


def test_storage_dir_is_path():
    assert isinstance(settings.STORAGE_DIR, Path)
    assert settings.STORAGE_DIR.exists()


def test_generated_images_dir_default():
    d = settings.GENERATED_IMAGES_DIR
    assert d.name == "generated_images"
    assert d.exists()
