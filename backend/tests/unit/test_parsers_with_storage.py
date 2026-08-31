"""M38.1 follow-up: parser works with the storage abstraction.

The ``DocumentParser.parse()`` entry point accepts a
``storage_key`` parameter that takes priority over ``file_path``.
On the local backend this resolves to the existing on-disk
location (no copy); on the S3 backend it downloads to a temp
file that ``parse()`` cleans up in a ``finally`` block.

These tests mock the storage layer to verify the resolver logic
without needing a live MinIO.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest


class _FakeLocalStorage:
    """Backend stub that returns the original key path unchanged."""

    backend_name = "local"

    def __init__(self, files: dict) -> None:
        # ``files`` maps ``storage_key`` -> ``file_path`` on disk.
        self._files = dict(files)

    def resolve_to_local_path(self, key: str) -> str:
        path = self._files.get(key)
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(key)
        return path


class _FakeS3Storage:
    """Backend stub that copies the bytes into a temp file."""

    backend_name = "s3"

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def resolve_to_local_path(self, key: str) -> str:
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
        tmp.write(self._payload)
        tmp.flush()
        tmp.close()
        return tmp.name


@pytest.fixture
def text_file(tmp_path: Path):
    """Plain-text file used by the parser."""
    p = tmp_path / "hello.txt"
    p.write_text("hello world", encoding="utf-8")
    return p


def test_parse_with_storage_key_local_backend(text_file, monkeypatch):
    """Local backend: ``storage_key`` resolves to the existing path,
    no copy, the parser runs against the original file."""
    from lumen_services.document_parser import DocumentParser

    key = "uploads/1/2/hello.txt"
    fake = _FakeLocalStorage({key: str(text_file)})
    # ``get_storage_backend`` is imported lazily inside
    # ``_resolve_parse_path``; patch the canonical path on
    # ``lumen_services.storage`` so the lookup hits our fake.
    monkeypatch.setattr(
        "lumen_services.storage.get_storage_backend", lambda: fake,
    )

    parser = DocumentParser()
    result = parser.parse(file_path=None, storage_key=key)
    # The text was actually parsed:
    assert "hello" in result["text"]
    # Metadata surfaces both the resolved path AND the original key:
    assert result["metadata"]["file_path"] == str(text_file)
    assert result["metadata"]["storage_key"] == key


def test_parse_with_storage_key_s3_backend_cleans_temp(monkeypatch):
    """S3 backend: storage_key downloads to a temp file; parse()
    must delete the temp in its ``finally`` block."""
    from lumen_services.document_parser import DocumentParser

    payload = b"s3-payload-text"
    fake = _FakeS3Storage(payload)
    monkeypatch.setattr(
        "lumen_services.storage.get_storage_backend", lambda: fake,
    )

    parser = DocumentParser()
    result = parser.parse(file_path=None, storage_key="uploads/1/x.bin")
    assert result["text"].startswith("s3-payload-text")

    # The temp file referenced by metadata must NOT still exist —
    # the parser's ``finally`` block cleans it up.
    tmp_path = result["metadata"]["file_path"]
    assert not os.path.exists(tmp_path), (
        f"parse() should delete the temp file at {tmp_path} in finally block"
    )


def test_parse_storage_key_missing_falls_back_to_file_path(text_file, monkeypatch):
    """Storage layer raised ``FileNotFoundError`` for the key;
    ``parse()`` falls back to ``file_path`` so the caller still
    sees the original parse error, not a confusing "storage
    backend not configured" message."""
    from lumen_services.document_parser import DocumentParser

    fake = _FakeLocalStorage({})  # nothing mapped
    monkeypatch.setattr(
        "lumen_services.storage.get_storage_backend", lambda: fake,
    )

    parser = DocumentParser()
    result = parser.parse(file_path=str(text_file), storage_key="uploads/missing.txt")
    assert "hello" in result["text"]
    # Storage key was not surfaced because it failed; the fallback
    # path was taken.
    assert "storage_key" not in result["metadata"]


def test_parse_legacy_file_path_still_works(text_file):
    """Pre-M38.1 callers that pass only ``file_path`` keep working
    unchanged — the resolver only activates when ``storage_key`` is
    set."""
    from lumen_services.document_parser import DocumentParser

    parser = DocumentParser()
    result = parser.parse(file_path=str(text_file))
    assert "hello" in result["text"]
    assert result["metadata"]["file_path"] == str(text_file)