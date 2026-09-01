"""M38.4 Step 4 — ImageParser unit tests.

Real PNG / JPG / WebP / GIF / BMP / TIFF fixtures via Pillow (the
parser's own dep). Tests cover:

- PNG → 1 chunk, modality='image', image_caption derived from filename
- JPG / WebP / GIF / BMP / TIFF — all dispatched through the same
  extension → mime mapping
- the ``image_caption`` text comes from the filename with underscores
  and dashes replaced by spaces (so ``product_logo_v2.png`` →
  ``"product logo v2"``); this is the MVP caption strategy per spec
  §"开放问题 2" (v2 will swap in LLM-generated captions)
- unsupported extensions fall back to the legacy raw-text path with a
  parse_error in metadata
- ``preserves_chunks=True`` so the secondary text-split doesn't shred
  the single-chunk shape
- missing file / corrupt image gracefully handled

Pillow is the parser's own dep — fixture cost is negligible.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image as PILImage

from lumen_services.parsers import ImageParser
from lumen_services.parsers.image_parser import IMAGE_EXTENSIONS


# ----------------------------------------------------------------------
# Fixture builders
# ----------------------------------------------------------------------


def _write_png(path: str, color: str = "red", size: tuple = (100, 50)) -> None:
    PILImage.new("RGB", size, color).save(path, format="PNG")


def _write_jpg(path: str, color: str = "blue", size: tuple = (80, 60)) -> None:
    PILImage.new("RGB", size, color).save(path, format="JPEG")


def _write_webp(path: str, color: str = "green", size: tuple = (40, 40)) -> None:
    PILImage.new("RGB", size, color).save(path, format="WEBP")


def _write_gif(path: str, color: str = "yellow", size: tuple = (32, 32)) -> None:
    PILImage.new("RGB", size, color).save(path, format="GIF")


def _write_bmp(path: str, color: str = "purple", size: tuple = (24, 24)) -> None:
    PILImage.new("RGB", size, color).save(path, format="BMP")


def _write_tiff(path: str, color: str = "cyan", size: tuple = (16, 16)) -> None:
    PILImage.new("RGB", size, color).save(path, format="TIFF")


# ----------------------------------------------------------------------
# Tests — core behavior
# ----------------------------------------------------------------------


def test_image_parser_returns_single_chunk(tmp_path):
    out = tmp_path / "logo.png"
    _write_png(str(out), color="red", size=(64, 32))

    result = ImageParser().parse(str(out))

    assert result["metadata"]["type"] == "image"
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["modality"] == "image"


def test_image_parser_caption_from_filename_underscores(tmp_path):
    """``product_logo_v2.png`` → ``"product logo v2"``."""
    out = tmp_path / "product_logo_v2.png"
    _write_png(str(out))

    result = ImageParser().parse(str(out))
    assert result["chunks"][0]["image_caption"] == "product logo v2"
    # The chunk's content is the caption — the multimodal embedder's
    # text branch embeds this for cross-modal retrieval.
    assert result["chunks"][0]["content"] == "product logo v2"


def test_image_parser_caption_from_filename_dashes(tmp_path):
    out = tmp_path / "company-logo-2024.png"
    _write_png(str(out))

    result = ImageParser().parse(str(out))
    assert result["chunks"][0]["image_caption"] == "company logo 2024"


def test_image_parser_caption_handles_no_separator(tmp_path):
    out = tmp_path / "logo.png"
    _write_png(str(out))

    result = ImageParser().parse(str(out))
    assert result["chunks"][0]["image_caption"] == "logo"


def test_image_parser_caption_handles_chinese(tmp_path):
    """CJK filenames should preserve the unicode stem verbatim (no
    lower-casing or whitespace stripping beyond the documented
    underscore/dash replacement)."""
    out = tmp_path / "产品_主图.png"
    _write_png(str(out))

    result = ImageParser().parse(str(out))
    assert result["chunks"][0]["image_caption"] == "产品 主图"


def test_image_parser_records_width_height(tmp_path):
    out = tmp_path / "sized.png"
    _write_png(str(out), size=(200, 100))

    result = ImageParser().parse(str(out))
    assert result["metadata"]["width"] == 200
    assert result["metadata"]["height"] == 100
    assert result["chunks"][0]["chunk_metadata"]["width"] == 200
    assert result["chunks"][0]["chunk_metadata"]["height"] == 100


def test_image_parser_records_mime_type(tmp_path):
    out = tmp_path / "photo.jpg"
    _write_jpg(str(out))

    result = ImageParser().parse(str(out))
    assert result["metadata"]["mime"] == "image/jpeg"
    assert result["metadata"]["format"] == "jpeg"


# ----------------------------------------------------------------------
# Tests — extension coverage
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "ext,writer,mime",
    [
        (".png", _write_png, "image/png"),
        (".jpg", _write_jpg, "image/jpeg"),
        (".jpeg", _write_jpg, "image/jpeg"),
        (".webp", _write_webp, "image/webp"),
        (".gif", _write_gif, "image/gif"),
        (".bmp", _write_bmp, "image/bmp"),
        (".tiff", _write_tiff, "image/tiff"),
        (".tif", _write_tiff, "image/tiff"),
    ],
)
def test_image_parser_supports_documented_extensions(tmp_path, ext, writer, mime):
    out = tmp_path / f"sample{ext}"
    writer(str(out))
    result = ImageParser().parse(str(out))
    assert result["metadata"]["mime"] == mime
    assert result["chunks"][0]["modality"] == "image"


def test_image_extensions_table_includes_documented_types():
    """The image_extensions set must include all 8 formats spec §"开放
    问题 7" lists."""
    expected = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
    assert expected.issubset(IMAGE_EXTENSIONS.keys())


# ----------------------------------------------------------------------
# Tests — edge cases
# ----------------------------------------------------------------------


def test_image_parser_unsupported_extension_falls_back(tmp_path):
    out = tmp_path / "doc.xyz"
    out.write_bytes(b"random")

    result = ImageParser().parse(str(out))
    assert result["metadata"]["fallback"] is True
    assert "unsupported image extension" in result["metadata"]["parse_error"]


def test_image_parser_missing_file_falls_back(tmp_path):
    """Missing file → fall back to raw text read (which also fails,
    yielding empty text + parse_error). The Document row ends up in
    the failed state via the document_tasks error path."""
    result = ImageParser().parse(str(tmp_path / "missing.png"))
    assert result["metadata"]["fallback"] is True
    assert "parse_error" in result["metadata"]


def test_image_parser_corrupt_image_falls_back(tmp_path):
    """A file with .png extension but invalid PNG bytes must not crash
    — emit a chunk with the filename-derived caption + a parse_error
    note so the caller can mark the Document as failed."""
    out = tmp_path / "fake.png"
    out.write_bytes(b"not actually a PNG")

    result = ImageParser().parse(str(out))
    # Still gets one chunk (caption fallback) + parse_error in metadata
    assert len(result["chunks"]) == 1
    assert "pillow_error" in result["metadata"]


def test_image_parser_preserves_chunks_flag_is_true():
    assert ImageParser.preserves_chunks is True


def test_image_parser_get_type():
    assert ImageParser().get_type() == "image"


def test_image_parser_chunk_metadata_carries_dimensions_for_image_assets(tmp_path):
    """The downstream code uses ``chunk_metadata.width`` /
    ``chunk_metadata.height`` when constructing an ``ImageAsset`` row
    (Step 5). Make sure both fields round-trip."""
    out = tmp_path / "dim.png"
    _write_png(str(out), size=(256, 128))

    result = ImageParser().parse(str(out))
    chunk_meta = result["chunks"][0]["chunk_metadata"]
    assert chunk_meta["width"] == 256
    assert chunk_meta["height"] == 128
    assert chunk_meta["mime"] == "image/png"
