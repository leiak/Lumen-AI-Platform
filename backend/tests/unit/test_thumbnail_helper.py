from lumen_services.image_generation_service import _make_thumbnail
from PIL import Image
import io


def _make_png_bytes(w=1024, h=1024, color=(255, 0, 0)):
    img = Image.new("RGB", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_thumbnail_returns_jpeg_bytes():
    out = _make_thumbnail(_make_png_bytes())
    assert out is not None
    assert out[:2] == b"\xff\xd8"  # JPEG magic


def test_thumbnail_is_256x256():
    out = _make_thumbnail(_make_png_bytes(2000, 1000))
    img = Image.open(io.BytesIO(out))
    assert img.size == (256, 256)


def test_thumbnail_size_under_50kb():
    out = _make_thumbnail(_make_png_bytes(4000, 4000))
    assert len(out) < 50_000


def test_thumbnail_returns_none_on_garbage():
    assert _make_thumbnail(b"not an image") is None
