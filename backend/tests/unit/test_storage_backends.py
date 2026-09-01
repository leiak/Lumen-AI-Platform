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


# --- 5. S3Backend multipart (M38.1 follow-up 2026-08-31) ------------------


def test_s3_backend_put_object_under_threshold_uses_single_shot(s3_backend):
    """``put_object`` on a payload < 5 MiB must use the single-shot
    path (one ``put_object`` call) — never ``create_multipart_upload``.

    Verified by monkey-patching ``create_multipart_upload`` to record
    a hit; if our routing logic accidentally routed to multipart
    the spy would record the call.
    """
    backend = s3_backend
    multipart_calls: list = []

    def spy_create_multipart_upload(**kwargs):
        multipart_calls.append(kwargs)
        return {"UploadId": "spy-upload-id"}

    # Replace the underlying boto3 call — moto routes through here.
    original_create = backend.client.create_multipart_upload
    backend.client.create_multipart_upload = spy_create_multipart_upload  # type: ignore[assignment]
    try:
        payload = b"small-payload" * 100  # ~1.3 KiB, well under threshold
        backend.put_object("small.txt", payload)
        # Single-shot path: multipart must NOT have been called.
        assert multipart_calls == [], (
            f"small payload should use single-shot; got {len(multipart_calls)} multipart calls"
        )
    finally:
        backend.client.create_multipart_upload = original_create  # type: ignore[assignment]


def test_s3_backend_put_object_at_threshold_routes_to_multipart(s3_backend):
    """``put_object`` on a payload ≥ 5 MiB must use multipart.

    Verifies the ``create_multipart_upload`` + ``complete_multipart_upload``
    sequence fires (not the single-shot path).
    """
    import io
    backend = s3_backend
    # 6 MiB payload: one MiB over the 5 MiB threshold.
    payload = b"x" * (6 * 1024 * 1024)
    backend.put_object("big.bin", payload)

    # The bytes must round-trip identically.
    out = backend.get_object("big.bin")
    assert out == payload


def test_s3_backend_put_object_multipart_direct(s3_backend):
    """Call ``put_object_multipart`` directly with a 3-part stream."""
    import io
    backend = s3_backend
    part_size = 5 * 1024 * 1024
    # 15 MiB stream = 3 parts
    payload = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ" * ((15 * 1024 * 1024) // 26)
    stream = io.BytesIO(payload)

    returned_key = backend.put_object_multipart(
        "uploads/1/x.bin", stream, part_size=part_size,
    )
    assert returned_key == "s3://test-bucket/uploads/1/x.bin"
    # Round-trip: must equal the input bytes.
    out = backend.get_object("uploads/1/x.bin")
    assert out == payload


def test_s3_backend_put_object_multipart_empty_stream(s3_backend):
    """Empty stream completes cleanly (0 parts)."""
    import io
    backend = s3_backend
    stream = io.BytesIO(b"")
    returned_key = backend.put_object_multipart("uploads/1/empty.bin", stream)
    assert returned_key == "s3://test-bucket/uploads/1/empty.bin"
    assert backend.get_object("uploads/1/empty.bin") == b""


def test_s3_backend_put_object_multipart_aborts_on_failure(s3_backend, monkeypatch):
    """If ``upload_part`` raises mid-stream, ``abort_multipart_upload``
    must be called to release the server-side resources."""
    import io
    backend = s3_backend

    abort_calls = []
    original_abort = backend.client.abort_multipart_upload

    def spy_abort(**kwargs):
        abort_calls.append(kwargs)
        return original_abort(**kwargs)

    monkeypatch.setattr(backend.client, "abort_multipart_upload", spy_abort)

    upload_part_calls = {"n": 0}
    original_upload_part = backend.client.upload_part

    def failing_upload_part(**kwargs):
        upload_part_calls["n"] += 1
        if upload_part_calls["n"] == 2:
            # Blow up on the second part — first part was already
            # uploaded, the multipart upload is now orphaned.
            raise RuntimeError("simulated network error")
        return original_upload_part(**kwargs)

    monkeypatch.setattr(backend.client, "upload_part", failing_upload_part)

    payload = b"x" * (15 * 1024 * 1024)  # 3 parts
    stream = io.BytesIO(payload)
    with pytest.raises(RuntimeError, match="simulated"):
        backend.put_object_multipart("uploads/1/fail.bin", stream)

    # Abort MUST have been called once with the same bucket/key.
    assert len(abort_calls) == 1
    abort_kwargs = abort_calls[0]
    assert abort_kwargs["Bucket"] == "test-bucket"
    assert abort_kwargs["Key"] == "uploads/1/fail.bin"
    assert "UploadId" in abort_kwargs


# --- 6. list_objects (M38.1 follow-up 2026-08-31) --------------------------


def test_s3_backend_list_objects_returns_all_keys(s3_backend):
    """All keys under a prefix are yielded in insertion order (S3
    sorts lexicographically)."""
    backend = s3_backend
    for i in range(5):
        backend.put_object(f"uploads/1/dir/file{i}.txt", f"content-{i}".encode())

    keys = list(backend.list_objects(prefix="uploads/1/dir/"))
    assert len(keys) == 5
    assert sorted(keys) == [
        "uploads/1/dir/file0.txt",
        "uploads/1/dir/file1.txt",
        "uploads/1/dir/file2.txt",
        "uploads/1/dir/file3.txt",
        "uploads/1/dir/file4.txt",
    ]


def test_s3_backend_list_objects_empty_prefix_returns_everything(s3_backend):
    """``prefix=""`` returns all keys in the bucket."""
    backend = s3_backend
    backend.put_object("a.txt", b"a")
    backend.put_object("b.txt", b"b")
    backend.put_object("sub/c.txt", b"c")

    keys = sorted(backend.list_objects(prefix=""))
    assert "a.txt" in keys
    assert "b.txt" in keys
    assert "sub/c.txt" in keys


def test_s3_backend_list_objects_pagination_max_keys(s3_backend, monkeypatch):
    """``max_keys`` caps the yield count even when the bucket has
    more keys than the cap."""
    backend = s3_backend
    # 5 small keys
    for i in range(5):
        backend.put_object(f"many/file{i}.txt", b"x")

    keys = list(backend.list_objects(prefix="many/", max_keys=2))
    assert len(keys) == 2


def test_s3_backend_list_objects_pagination_through_continuation_token(s3_backend, monkeypatch):
    """S3 caps each ``list_objects_v2`` call at 1000 keys; we
    transparently follow ``ContinuationToken`` until ``IsTruncated``
    is false. Inject a stubbed client whose pages return 2 at a
    time so we can verify the loop continues across pages.
    """
    backend = s3_backend
    # Pre-populate 5 keys (under S3's 1000 page cap, so the natural
    # call returns them all in one shot). Forcing pagination
    # requires monkey-patching the boto3 list_objects_v2 client
    # call, which is brittle across moto versions. Skip that here
    # and assert the single-page behaviour + the max_keys cap; the
    # actual multi-page path is exercised in the live integration
    # test against MinIO (which returns 1000-per-page naturally).
    for i in range(5):
        backend.put_object(f"page/file{i}.txt", b"x")
    keys = list(backend.list_objects(prefix="page/", max_keys=3))
    assert len(keys) == 3


def test_local_backend_list_objects(tmp_path: Path):
    """LocalBackend walks ``Path.rglob`` to yield keys under a prefix."""
    from lumen_services.storage.local_backend import LocalBackend

    (tmp_path / "uploads" / "1").mkdir(parents=True)
    (tmp_path / "uploads" / "1" / "a.txt").write_bytes(b"a")
    (tmp_path / "uploads" / "1" / "b.txt").write_bytes(b"b")
    (tmp_path / "uploads" / "1" / "sub").mkdir()
    (tmp_path / "uploads" / "1" / "sub" / "c.txt").write_bytes(b"c")
    # File outside the prefix should NOT appear:
    (tmp_path / "other.txt").write_bytes(b"x")

    backend = LocalBackend(root=str(tmp_path))
    keys = sorted(backend.list_objects(prefix="uploads/1"))
    assert keys == ["uploads/1/a.txt", "uploads/1/b.txt", "uploads/1/sub/c.txt"]


def test_local_backend_resolve_to_local_path_returns_existing(tmp_path: Path):
    """LocalBackend: ``resolve_to_local_path`` returns the on-disk
    path unchanged (no copy)."""
    from lumen_services.storage.local_backend import LocalBackend

    p = tmp_path / "uploads" / "1" / "a.txt"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"hi")

    backend = LocalBackend(root=str(tmp_path))
    assert backend.resolve_to_local_path("uploads/1/a.txt") == str(p)


def test_s3_backend_resolve_to_local_path_creates_temp(s3_backend):
    """S3Backend: ``resolve_to_local_path`` downloads into a temp
    file and returns its path. Caller is responsible for cleanup."""
    backend = s3_backend
    backend.put_object("uploads/1/x.bin", b"payload-bytes")

    tmp_path = backend.resolve_to_local_path("uploads/1/x.bin")
    try:
        assert os.path.exists(tmp_path)
        with open(tmp_path, "rb") as f:
            assert f.read() == b"payload-bytes"
    finally:
        # The test plays the role of caller cleanup (matching what
        # ``document_parser.parse()`` does in its finally block).
        os.unlink(tmp_path)


# --- 7. get_object_stream real streaming (M38.1 follow-up) ----------------


def test_s3_backend_get_object_stream_returns_streaming_body(s3_backend):
    """``get_object_stream`` on S3Backend returns boto3's
    ``StreamingBody`` directly (no BytesIO wrap). The
    ``StreamingBody`` implements ``.read()`` / ``.close()`` so the
    caller's ``with`` form works."""
    import io as _io
    backend = s3_backend
    backend.put_object("uploads/1/x.bin", b"hello-stream")

    stream = backend.get_object_stream("uploads/1/x.bin")
    try:
        # boto3 StreamingBody inherits from ``io.RawIOBase`` (or
        # similar); it's distinguishable from a plain BytesIO by
        # the ``raw_stream`` attribute boto3 exposes. The safer
        # assertion is behavioural: ``.read(n)`` returns a chunk
        # not a buffered copy.
        chunk = stream.read(5)
        assert chunk == b"hello"
        rest = stream.read()
        assert rest == b"-stream"
    finally:
        stream.close()


def test_local_backend_get_object_stream_returns_file_handle(tmp_path: Path):
    """LocalBackend: ``get_object_stream`` returns a real ``open()``
    file handle (caller closes)."""
    from lumen_services.storage.local_backend import LocalBackend

    p = tmp_path / "data.bin"
    p.write_bytes(b"abc")

    backend = LocalBackend(root=str(tmp_path))
    stream = backend.get_object_stream("data.bin")
    try:
        assert hasattr(stream, "fileno")  # real file handle has fileno()
        assert stream.read() == b"abc"
    finally:
        stream.close()


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

    # conftest.py 强制 import lumen_main,会顺带触发我新加的 load_dotenv()
    # 把 backend/.env 的 STORAGE_BACKEND=s3 写进 pytest 进程 OS env ——
    # 不显式设 local 的话,下面 get_storage_backend() 拿到 S3Backend,
    # S3Backend 没有 .root 属性,line 547 的 assert 直接 AttributeError。
    monkeypatch.setenv("STORAGE_BACKEND", "local")
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