"""M38.1: unit tests for ``lumen_services.storage``.

Covers:

- ``StorageBackend._validate_key`` (rejects absolute paths,
  traversal, empty strings)
- ``LocalBackend`` end-to-end (put / get / stream / delete / exists
  / presigned URL / health check)
- ``S3Backend`` end-to-end via ``moto`` (mock S3 endpoint, no live
  MinIO required)
- ``get_storage_backend`` factory dispatch (env var → backend type)

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-storage-abstraction.md``
§ 9.1.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest


# --- 1. base / key validation ------------------------------------------


def test_validate_key_rejects_absolute():
    from lumen_services.storage.base import StorageBackend

    with pytest.raises(ValueError, match="relative"):
        StorageBackend._validate_key("/etc/passwd")


def test_validate_key_rejects_parent_traversal():
    from lumen_services.storage.base import StorageBackend

    with pytest.raises(ValueError, match=r"\.\."):
        StorageBackend._validate_key("foo/../../etc/passwd")


def test_validate_key_rejects_empty():
    from lumen_services.storage.base import StorageBackend

    with pytest.raises(ValueError, match="non-empty"):
        StorageBackend._validate_key("   ")


def test_validate_key_normalises_backslashes():
    from lumen_services.storage.base import StorageBackend

    # Backslashes are rewritten to forward slashes; the ``..``
    # rejection still fires on the normalised form.
    out = StorageBackend._validate_key("foo\\bar")
    assert "/" in out
    assert "\\" not in out


# --- 2. LocalBackend ----------------------------------------------------


def test_local_backend_put_get_delete(tmp_path: Path):
    from lumen_services.storage.local_backend import LocalBackend

    backend = LocalBackend(root=str(tmp_path))
    assert backend.backend_name == "local"

    key = "uploads/1/2/hello.txt"
    backend.put_object(key, b"hello world", content_type="text/plain")
    assert backend.object_exists(key)
    assert backend.get_object(key) == b"hello world"
    assert backend.get_presigned_url(key) == f"/api/v1/storage/local/{key}"

    backend.delete_object(key)
    assert not backend.object_exists(key)
    # Idempotent: deleting twice is a silent no-op.
    backend.delete_object(key)


def test_local_backend_get_missing_raises_file_not_found(tmp_path: Path):
    from lumen_services.storage.local_backend import LocalBackend

    backend = LocalBackend(root=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        backend.get_object("uploads/missing.pdf")


def test_local_backend_stream_returns_filelike(tmp_path: Path):
    from lumen_services.storage.local_backend import LocalBackend

    backend = LocalBackend(root=str(tmp_path))
    backend.put_object("data.bin", b"binary-content")
    stream = backend.get_object_stream("data.bin")
    try:
        assert stream.read() == b"binary-content"
    finally:
        stream.close()


def test_local_backend_put_overwrites(tmp_path: Path):
    from lumen_services.storage.local_backend import LocalBackend

    backend = LocalBackend(root=str(tmp_path))
    backend.put_object("k", b"first")
    backend.put_object("k", b"second")
    assert backend.get_object("k") == b"second"


def test_local_backend_health_ok(tmp_path: Path):
    from lumen_services.storage.local_backend import LocalBackend

    backend = LocalBackend(root=str(tmp_path))
    report = backend.health_check()
    assert report["backend"] == "local"
    assert report["ok"] is True
    assert "latency_ms" in report


def test_local_backend_from_env_honours_override(tmp_path: Path, monkeypatch):
    from lumen_services.storage import reset_storage_backend
    from lumen_services.storage.local_backend import LocalBackend

    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))
    reset_storage_backend()
    backend = LocalBackend.from_env()
    assert backend.root == tmp_path.resolve()


def test_local_backend_validates_key_against_escape(tmp_path: Path):
    """Negative: a key with ``..`` must not resolve outside the root."""
    from lumen_services.storage.local_backend import LocalBackend

    backend = LocalBackend(root=str(tmp_path))
    with pytest.raises(ValueError):
        backend.put_object("../escape.txt", b"x")


# --- 3. S3Backend (moto) -----------------------------------------------


@pytest.fixture
def s3_backend():
    """A S3Backend pointed at a moto-mocked S3 endpoint.

    moto is imported lazily inside the fixture so the test module
    imports cleanly when boto3 / moto aren't installed (LocalBackend
    dev environment).
    """
    import importlib

    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")

    with moto.mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        client.create_bucket(Bucket="test-bucket")
        # Importing here lets moto mock the AWS calls that
        # ``S3Backend.__init__`` makes via the boto3 session.
        from lumen_services.storage.s3_backend import S3Backend

        yield S3Backend(client=client, bucket="test-bucket", presigned_expiry=600)


def test_s3_backend_put_get_delete(s3_backend):
    backend = s3_backend
    backend.put_object("uploads/1/2/x.pdf", b"pdf-bytes")
    assert backend.object_exists("uploads/1/2/x.pdf")
    assert backend.get_object("uploads/1/2/x.pdf") == b"pdf-bytes"

    backend.delete_object("uploads/1/2/x.pdf")
    assert not backend.object_exists("uploads/1/2/x.pdf")
    # Idempotent
    backend.delete_object("uploads/1/2/x.pdf")


def test_s3_backend_get_missing_normalises_to_file_not_found(s3_backend):
    with pytest.raises(FileNotFoundError):
        s3_backend.get_object("missing.txt")


def test_s3_backend_presigned_url_has_signature(s3_backend):
    url = s3_backend.get_presigned_url("uploads/1/2/x.pdf")
    assert "X-Amz-Signature" in url or "Signature=" in url
    # moto still produces AWS-style virtual-hosted URLs even when
    # we configured path-style — the important property for the
    # test is that the signature is present.


def test_s3_backend_health_check_ok(s3_backend):
    report = s3_backend.health_check()
    assert report["backend"] == "s3"
    assert report["ok"] is True


# --- 4. factory dispatch ------------------------------------------------


def test_factory_returns_local_by_default(monkeypatch, tmp_path: Path):
    """No ``STORAGE_BACKEND`` set → LocalBackend rooted at ``./data``
    or whatever ``STORAGE_LOCAL_ROOT`` points at."""
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))

    from lumen_services.storage import get_storage_backend, reset_storage_backend

    reset_storage_backend()
    backend = get_storage_backend()
    assert backend.backend_name == "local"
    assert backend.root == tmp_path.resolve()
    reset_storage_backend()


def test_factory_returns_s3_when_configured(monkeypatch):
    """``STORAGE_BACKEND=s3`` with required env vars → S3Backend."""
    pytest.importorskip("boto3")
    pytest.importorskip("moto")

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "x")
    monkeypatch.setenv("S3_ACCESS_KEY", "k")
    monkeypatch.setenv("S3_SECRET_KEY", "s")

    import moto

    from lumen_services.storage import get_storage_backend, reset_storage_backend

    with moto.mock_aws():
        reset_storage_backend()
        backend = get_storage_backend()
        assert backend.backend_name == "s3"
    reset_storage_backend()


def test_factory_missing_s3_credentials_raises_actionable_error(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)

    from lumen_services.storage import get_storage_backend, reset_storage_backend
    from lumen_services.storage.s3_backend import S3BackendError

    reset_storage_backend()
    with pytest.raises(S3BackendError, match="S3_BUCKET"):
        get_storage_backend()
    reset_storage_backend()


def test_factory_returns_singleton(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))
    from lumen_services.storage import get_storage_backend, reset_storage_backend

    reset_storage_backend()
    a = get_storage_backend()
    b = get_storage_backend()
    assert a is b
    reset_storage_backend()


def test_reset_storage_backend_re_reads_env(monkeypatch, tmp_path: Path):
    from lumen_services.storage import get_storage_backend, reset_storage_backend
    from lumen_services.storage.local_backend import LocalBackend

    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "first"))
    reset_storage_backend()
    a = get_storage_backend()
    assert a.root == (tmp_path / "first").resolve()

    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path / "second"))
    reset_storage_backend()
    b = get_storage_backend()
    assert b is not a
    assert b.root == (tmp_path / "second").resolve()
    reset_storage_backend()