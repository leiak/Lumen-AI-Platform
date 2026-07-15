from lumen_services.image_providers import ImageProvider


def test_protocol_importable():
    assert ImageProvider is not None
