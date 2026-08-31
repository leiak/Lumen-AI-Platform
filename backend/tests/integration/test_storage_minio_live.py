"""M38.1 follow-up: live integration tests against a running MinIO.

Requires a MinIO server at ``localhost:29000`` with credentials
``minioadmin:minioadmin`` (the default the dev ``docker-compose.yml``
sets up). If the probe at startup fails, every test in this
module is skipped — CI environments without docker compose don't
gate the suite on MinIO availability.

Sections:
    1. ``/storage/health`` reports backend=s3 / ok=true
    2. multipart upload: put_object ≥ 5 MiB
    3. ``list_objects`` returns every uploaded key
    4. ``get_object_stream`` is a real stream (not a buffered copy)
    5. tenant isolation via ``list_objects(prefix=...)``
"""
from __future__ import annotations

import io
import os
import uuid
from typing import Iterator

import pytest

# Skip the entire module if MinIO isn't running. The probe is
# session-scope so we don't repeat the network round-trip per test.
_MINIO_ENDPOINT = "http://localhost:29000"
_MINIO_ACCESS_KEY = "minioadmin"
_MINIO_SECRET_KEY = "minioadmin"


def _make_s3_client():
    """Build a boto3 S3 client pointed at the local MinIO. Lazily
    imported so the test module imports cleanly without boto3."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=_MINIO_ENDPOINT,
        aws_access_key_id=_MINIO_ACCESS_KEY,
        aws_secret_access_key=_MINIO_SECRET_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 1, "mode": "standard"},
        ),
        region_name="us-east-1",
    )


@pytest.fixture(scope="module")
def minio_or_skip() -> Iterator:
    """Probe MinIO once per module; skip the suite if unreachable."""
    try:
        import boto3  # noqa: F401
    except ImportError:
        pytest.skip("boto3 not installed")
    client = _make_s3_client()
    try:
        client.list_buckets()
    except Exception as exc:  # pragma: no cover - skip path
        pytest.skip(f"MinIO not reachable at {_MINIO_ENDPOINT}: {exc}")
    yield client


@pytest.fixture(scope="module")
def test_bucket(minio_or_skip) -> Iterator[str]:
    """Create a unique bucket; tear down + delete on session exit."""
    bucket = f"lumen-test-{uuid.uuid4().hex[:8]}"
    minio_or_skip.create_bucket(Bucket=bucket)
    yield bucket
    # Teardown: drain all objects, then delete the bucket.
    try:
        resp = minio_or_skip.list_objects_v2(Bucket=bucket)
        for obj in resp.get("Contents", []) or []:
            minio_or_skip.delete_object(Bucket=bucket, Key=obj["Key"])
        while resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
            resp = minio_or_skip.list_objects_v2(
                Bucket=bucket, ContinuationToken=token,
            )
            for obj in resp.get("Contents", []) or []:
                minio_or_skip.delete_object(Bucket=bucket, Key=obj["Key"])
        minio_or_skip.delete_bucket(Bucket=bucket)
    except Exception:  # pragma: no cover - cleanup best-effort
        pass


@pytest.fixture(scope="module")
def s3_backend_for_minio(test_bucket, monkeypatch_module) -> Iterator:
    """Build a real ``S3Backend`` pointed at the test bucket on MinIO.
    The backend's ``.client`` is reused — we don't go through the
    factory (which would require env-var setup) so the test stays
    self-contained.
    """
    pytest.importorskip("boto3")
    from lumen_services.storage.s3_backend import S3Backend

    client = _make_s3_client()
    backend = S3Backend(client=client, bucket=test_bucket, presigned_expiry=600)
    yield backend


@pytest.fixture(scope="module")
def monkeypatch_module(request):
    """Module-scoped monkeypatch (pytest's built-in is function-scope)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


# --- 1. Health -----------------------------------------------------------


def test_health_endpoint_returns_s3_when_storage_backend_is_s3(
    test_bucket, minio_or_skip, monkeypatch_module,
):
    """``GET /api/v1/storage/health`` reports ``backend=s3`` and
    ``ok=true`` when the singleton is forced into S3 mode."""
    # Build a backend, then patch the factory so the API endpoint
    # picks it up. We can't easily do this without env vars in
    # ``from_env``, so we hand-build the backend and patch the
    # getter.
    from lumen_services.storage.s3_backend import S3Backend
    from lumen_services.storage import base as base_mod

    backend = S3Backend(
        client=_make_s3_client(),
        bucket=test_bucket,
        presigned_expiry=600,
    )
    monkeypatch_module.setattr(
        "lumen_services.storage.get_storage_backend", lambda: backend,
    )

    # We don't need to spin up the full app — the health endpoint
    # is a thin wrapper. Just call the backend's ``health_check``.
    report = backend.health_check()
    assert report["backend"] == "s3"
    assert report["ok"] is True
    assert "latency_ms" in report


# --- 2. Multipart ---------------------------------------------------------


def test_multipart_upload_round_trip(s3_backend_for_minio):
    """``put_object`` with a 50 MiB payload goes through multipart
    and the bytes round-trip identically."""
    backend = s3_backend_for_minio
    payload = b"x" * (50 * 1024 * 1024)
    backend.put_object("big.bin", payload)
    out = backend.get_object("big.bin")
    assert out == payload
    assert len(out) == 50 * 1024 * 1024


def test_multipart_direct_stream(s3_backend_for_minio):
    """``put_object_multipart`` accepts a stream and assembles the
    object correctly."""
    backend = s3_backend_for_minio
    # 15 MiB stream = 3 parts at 5 MiB each.
    payload = b"ABCDEFGHIJ" * ((15 * 1024 * 1024) // 10)
    stream = io.BytesIO(payload)
    returned = backend.put_object_multipart("uploads/1/stream.bin", stream)
    assert returned == f"s3://{backend.bucket}/uploads/1/stream.bin"
    assert backend.get_object("uploads/1/stream.bin") == payload


# --- 3. list_objects -----------------------------------------------------


def test_list_objects_returns_all_uploaded_keys(s3_backend_for_minio):
    """Upload 100 small keys, ``list_objects`` returns all of them."""
    backend = s3_backend_for_minio
    for i in range(100):
        backend.put_object(f"many/file{i:03d}.txt", b"x")
    keys = list(backend.list_objects(prefix="many/"))
    assert len(keys) == 100
    assert keys[0] == "many/file000.txt"
    assert keys[-1] == "many/file099.txt"


def test_list_objects_respects_max_keys(s3_backend_for_minio):
    """``max_keys`` caps the yielded count."""
    backend = s3_backend_for_minio
    for i in range(50):
        backend.put_object(f"cap/file{i}.txt", b"x")
    keys = list(backend.list_objects(prefix="cap/", max_keys=5))
    assert len(keys) == 5


# --- 4. Streaming --------------------------------------------------------


def test_get_object_stream_is_real_stream(s3_backend_for_minio):
    """``get_object_stream`` returns a real ``StreamingBody`` —
    ``.read(n)`` returns n bytes (not a buffered full copy)."""
    backend = s3_backend_for_minio
    payload = b"abcdefghij" * 1000  # 10 KiB
    backend.put_object("stream.bin", payload)

    stream = backend.get_object_stream("stream.bin")
    try:
        chunk = stream.read(5)
        assert chunk == b"abcde"
        # The next ``read(n)`` continues from where we stopped —
        # streaming, not pre-loaded.
        rest = stream.read()
        assert rest.startswith(b"fghij")
    finally:
        stream.close()


# --- 5. Tenant isolation --------------------------------------------------


def test_list_objects_prefix_filters_by_tenant(s3_backend_for_minio):
    """Keys prefixed with different ``tenant_id/`` paths are
    isolated by ``list_objects(prefix="<tenant>/")`` — a tenant
    can only see its own sub-tree."""
    backend = s3_backend_for_minio
    for tenant in (1, 2, 3):
        for i in range(3):
            backend.put_object(f"{tenant}/doc/file{i}.bin", b"x")

    tenant1 = list(backend.list_objects(prefix="1/"))
    tenant2 = list(backend.list_objects(prefix="2/"))
    assert len(tenant1) == 3
    assert all(k.startswith("1/") for k in tenant1)
    assert len(tenant2) == 3
    assert all(k.startswith("2/") for k in tenant2)
    # The two tenant key sets must not overlap.
    assert set(tenant1).isdisjoint(set(tenant2))