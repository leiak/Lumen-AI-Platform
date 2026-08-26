"""M38.1: S3-compatible storage backend.

Works with any service that speaks the AWS S3 v4 protocol:
- Amazon S3
- MinIO (self-hosted)
- Aliyun OSS
- Tencent COS
- Cloudflare R2

Uses ``boto3`` under the hood. ``boto3`` is intentionally an
optional dependency — code paths that never instantiate
``S3Backend`` (LocalBackend dev, unit tests) do not require it.

Configuration is read from environment variables (see spec §4).
"""
from __future__ import annotations

import os
import time
from io import BytesIO
from typing import BinaryIO, Dict, Optional

from .base import StorageBackend


class S3BackendError(RuntimeError):
    """Raised when the S3 backend cannot be configured or used."""


class S3Backend(StorageBackend):
    """S3-compatible object storage. Builds a boto3 client from the
    standard ``S3_*`` env vars."""

    backend_name = "s3"

    def __init__(
        self,
        client,
        bucket: str,
        presigned_expiry: int = 3600,
    ) -> None:
        # ``client`` is a boto3 S3 client; we keep the type as
        # ``Any``-equivalent to avoid importing boto3 types at
        # module load time.
        self.client = client
        self.bucket = bucket
        self.presigned_expiry = int(presigned_expiry)

    # -- factory --------------------------------------------------------

    @classmethod
    def from_env(cls) -> "S3Backend":
        """Build from ``S3_*`` env vars. Raises
        :class:`S3BackendError` with an actionable message when
        boto3 isn't installed or required vars are missing."""
        try:
            import boto3  # type: ignore
            from botocore.config import Config as BotoConfig  # type: ignore
        except ImportError as exc:
            raise S3BackendError(
                "S3 backend requires boto3 — install with "
                "`pip install boto3` or set STORAGE_BACKEND=local"
            ) from exc

        endpoint = os.getenv("S3_ENDPOINT") or None  # empty -> AWS default
        region = os.getenv("S3_REGION", "us-east-1")
        bucket = os.getenv("S3_BUCKET")
        access_key = os.getenv("S3_ACCESS_KEY")
        secret_key = os.getenv("S3_SECRET_KEY")
        use_ssl = (os.getenv("S3_USE_SSL", "true").strip().lower()
                   not in {"0", "false", "no", "off"})
        path_style = (os.getenv("S3_PATH_STYLE", "false").strip().lower()
                      in {"1", "true", "yes", "on"})

        if not bucket:
            raise S3BackendError("S3_BUCKET env var is required")
        if not access_key or not secret_key:
            raise S3BackendError(
                "S3_ACCESS_KEY and S3_SECRET_KEY env vars are required"
            )

        config = BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path" if path_style else "virtual"},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            use_ssl=use_ssl,
            config=config,
        )
        expiry = int(os.getenv("S3_PRESIGNED_URL_EXPIRY", "3600"))
        return cls(client=client, bucket=bucket, presigned_expiry=expiry)

    # -- interface ------------------------------------------------------

    def put_object(
        self,
        key: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        safe = self._validate_key(key)
        kwargs: Dict[str, object] = {"Bucket": self.bucket, "Key": safe, "Body": data}
        if content_type:
            kwargs["ContentType"] = content_type
        self.client.put_object(**kwargs)
        return f"s3://{self.bucket}/{safe}"

    def get_object(self, key: str) -> bytes:
        stream = self.get_object_stream(key)
        try:
            return stream.read()
        finally:
            stream.close()

    def get_object_stream(self, key: str) -> BinaryIO:
        safe = self._validate_key(key)
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=safe)
        except Exception as exc:
            # boto3 raises ``ClientError`` with ``Error["Code"] == "NoSuchKey"``
            # for missing keys; normalise to FileNotFoundError so the
            # upper layers can rely on the same exception type as the
            # LocalBackend.
            code = _extract_error_code(exc)
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(safe) from exc
            raise
        body = resp["Body"]
        # Wrap boto3's StreamingBody in a thin BytesIO so callers can
        # treat it like a regular file (boto3's StreamingBody already
        # supports .read() / .close() but lacks a few stdlib methods
        # some parsers use). For files <5MB we read straight into
        # memory; above that the caller is expected to use
        # get_object_stream which yields the StreamingBody as-is.
        data = body.read()
        body.close()
        return BytesIO(data)

    def delete_object(self, key: str) -> None:
        safe = self._validate_key(key)
        # boto3's delete_object is idempotent (no error on missing key).
        self.client.delete_object(Bucket=self.bucket, Key=safe)

    def object_exists(self, key: str) -> bool:
        safe = self._validate_key(key)
        try:
            self.client.head_object(Bucket=self.bucket, Key=safe)
            return True
        except Exception as exc:
            if _extract_error_code(exc) in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def get_presigned_url(self, key: str, expiry: Optional[int] = None) -> str:
        safe = self._validate_key(key)
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": safe},
            ExpiresIn=expiry or self.presigned_expiry,
        )

    def health_check(self) -> Dict[str, object]:
        start = time.monotonic()
        detail = "ok"
        ok = True
        try:
            # Cheap probe: head_bucket is a HEAD on the bucket
            # itself, returns 200/403 without listing objects.
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            ok = False
            code = _extract_error_code(exc)
            detail = f"error: {code or type(exc).__name__}: {exc}"
        return {
            "backend": self.backend_name,
            "ok": ok,
            "detail": detail,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }


def _extract_error_code(exc: Exception) -> Optional[str]:
    """Best-effort extraction of the S3 error code from a boto3
    ClientError so we can map it to ``FileNotFoundError``. Returns
    ``None`` for any non-boto3 exception."""
    try:
        return exc.response["Error"]["Code"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError):
        return None