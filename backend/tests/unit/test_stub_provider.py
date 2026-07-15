import pytest
from lumen_services.image_providers.stub_provider import StubImageProvider


@pytest.mark.asyncio
async def test_stub_returns_png_bytes():
    p = StubImageProvider()
    out = await p.generate(prompt="hello world", size="512x512")
    assert len(out) == 1
    assert out[0][:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


@pytest.mark.asyncio
async def test_stub_default_size():
    p = StubImageProvider()
    out = await p.generate(prompt="x")
    assert len(out) == 1
    # Verify image opens as 1024x1024
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(out[0]))
    assert img.size == (1024, 1024)


@pytest.mark.asyncio
async def test_stub_handles_invalid_size():
    p = StubImageProvider()
    out = await p.generate(prompt="x", size="garbage")
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(out[0]))
    assert img.size == (1024, 1024)  # falls back to default
