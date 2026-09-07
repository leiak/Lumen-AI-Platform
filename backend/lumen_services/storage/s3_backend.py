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

import mimetypes
import os
import time
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, Optional

from .base import StorageBackend
from lumen_core.boto3_bypass import boto3_bypass_proxy_kwargs

# M38.1 follow-up (2026-08-31): 单次 PUT / multipart 自动分流的阈值(5 MiB)。
# 与 S3 单次 PUT 上限 5 GB 的安全距离充足;5 MiB 也是 multipart part_size
# 的常用起点(下游 lazy-load、流式解析时刚好一个网络往返)。
_MULTIPART_THRESHOLD_BYTES = 5 * 1024 * 1024
_DEFAULT_PART_SIZE_BYTES = 5 * 1024 * 1024


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

    @staticmethod
    def _bypass_proxy_kwargs() -> dict[str, object] | str:
        """Phase 1 Group B 4.4 Day 5 (2026-09-06):boto3 proxy bypass 控制。
        2.1 C.2 (2026-09-07):统一走 ``lumen_core.boto3_bypass`` helper,跟
        httpx_bypass 决策表对齐 —— env-aware,生产 HTTPS_PROXY 设了就走代理。

        决策:
        - 默认 (dev / 无 proxy env):返 ``{"proxies": {}}``(botocore "无 proxy"
          — 不查 Windows registry / HTTPS_PROXY)。直连 MinIO / localhost:29000
          必须 bypass,代理对 internal IP 无路由返回 502。
        - 设了 ``HTTPS_PROXY`` / ``HTTP_PROXY`` env:返 ``{}`` sentinel,
          BotoConfig 不传 ``proxies``,botocore 自己查 env。
        - ``S3_BYPASS_PROXY=false``:显式 opt-out 走 auto(等同 env 有设)。
        - ``LUMEN_FORCE_PROXY_BYPASS=1``:强制 bypass(无视 env,本地调试用)。

        为什么支持 opt-out:生产 / K8s 集群如果 S3 endpoint 在代理后面,显式
        ``S3_BYPASS_PROXY=false`` 让 botocore 自己解析代理配置。
        """
        bypass = os.getenv("S3_BYPASS_PROXY", "true").strip().lower()
        if bypass in {"0", "false", "no", "off"}:
            return "auto"  # sentinel:不传 proxies 参数
        # 默认走 boto3_bypass 共享 helper(env-aware)
        return boto3_bypass_proxy_kwargs()

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

        config_kwargs: dict[str, object] = {
            "signature_version": "s3v4",
            "s3": {"addressing_style": "path" if path_style else "virtual"},
            "retries": {"max_attempts": 3, "mode": "standard"},
        }
        # Phase 1 Group B 4.4 Day 5 (2026-09-06):boto3 proxy bypass。
        # 默认 ``proxies={}`` 禁掉 Windows registry / ``HTTPS_PROXY``
        # env 走的代理。S3 backend 目标是 MinIO (localhost:29000) 或
        # AWS S3 直连,都不需要企业出口代理;走代理反而会让本地
        # MinIO 连不上(代理对 internal IP 无路由)。
        #
        # 对应 httpx 修法(``model_loader._bypass_proxy_client_kwargs``
        # → ``proxy=None, trust_env=False``),保持项目"内部 HTTP
        # client 默认 bypass 代理"的一致语义。生产 / K8s 集群如果
        # 真要走代理,设 ``S3_BYPASS_PROXY=false`` 走 botocore auto-detect。
        proxy_mode = cls._bypass_proxy_kwargs()
        if proxy_mode != "auto":
            # 2.1 C.2:proxy_mode 现在是 kwargs 格式(``{"proxies": {}}`` 或 ``{}``),
            # 用 update 合并进 config_kwargs,而不是当作 proxies 的 value 赋值
            # (赋值会导致 ``config_kwargs["proxies"] = {"proxies": {}}`` nested bug)。
            config_kwargs.update(proxy_mode)
        config = BotoConfig(**config_kwargs)
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

    @staticmethod
    def _effective_content_type(key: str, content_type: Optional[str]) -> Optional[str]:
        """Resolve the ``ContentType`` header for an upload.

        调用方显式传的 ``content_type`` 优先;没传时按对象 key 的扩展名
        推断。不推断的话 S3 / MinIO 一律存成 ``binary/octet-stream``,
        浏览器拿到 presigned URL 只会触发下载而不是 inline 预览 —— KB
        文档预览、公众号素材缩略图、视频 ``<video>`` 播放都会退化。
        推不出来时返回 ``None``,让 S3 用自己的默认值。
        """
        if content_type:
            return content_type
        guessed, _encoding = mimetypes.guess_type(key)
        return guessed

    def put_object(
        self,
        key: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        safe = self._validate_key(key)
        # Auto-route: large payloads (≥ 5 MiB) go through multipart so
        # we don't hit boto3's single-PUT 5 GB limit and we keep memory
        # bounded. Smaller payloads stay on the single-shot path (one
        # HTTP call, no multipart overhead).
        if isinstance(data, (bytes, bytearray)) and len(data) >= _MULTIPART_THRESHOLD_BYTES:
            return self.put_object_multipart(
                safe, BytesIO(bytes(data)), content_type=content_type,
            )
        kwargs: Dict[str, object] = {"Bucket": self.bucket, "Key": safe, "Body": data}
        effective_type = self._effective_content_type(safe, content_type)
        if effective_type:
            kwargs["ContentType"] = effective_type
        self.client.put_object(**kwargs)
        return f"s3://{self.bucket}/{safe}"

    def put_object_multipart(
        self,
        key: str,
        data_stream: BinaryIO,
        part_size: int = _DEFAULT_PART_SIZE_BYTES,
        content_type: Optional[str] = None,
    ) -> str:
        """Stream-upload ``data_stream`` via S3 multipart upload.

        Sequence:
        1. ``create_multipart_upload`` to obtain an ``UploadId``.
        2. Loop ``data_stream.read(part_size)`` until EOF, calling
           ``upload_part`` per chunk and recording each ``ETag``.
        3. ``complete_multipart_upload`` with all parts in order.
        4. On any failure inside the loop, ``abort_multipart_upload``
           releases server-side resources (incomplete multipart
           uploads accumulate storage cost on MinIO until expiry).

        Caller owns ``data_stream`` (we read, do not close).
        ``part_size`` defaults to 5 MiB, matching S3's recommended
        minimum and our auto-routing threshold.
        """
        safe = self._validate_key(key)
        # An empty stream collapses to a 0-byte object via the
        # single-shot ``put_object`` path. S3's
        # ``CompleteMultipartUpload`` requires at least one part and
        # raises ``MalformedXML`` otherwise — so we'd waste an
        # Init / Abort round-trip for nothing. Branching here keeps
        # the multipart path strictly "non-empty payload".
        if data_stream.peek(1) if hasattr(data_stream, "peek") else data_stream.read(1):
            # ``peek``/``read(1)`` consumed 1 byte — rewind so the
            # multipart loop sees the same bytes the caller streamed.
            if hasattr(data_stream, "seek"):
                data_stream.seek(-1, 1)
        else:
            return self.put_object(safe, b"", content_type=content_type)
        create_kwargs: Dict[str, object] = {"Bucket": self.bucket, "Key": safe}
        effective_type = self._effective_content_type(safe, content_type)
        if effective_type:
            create_kwargs["ContentType"] = effective_type
        create_resp = self.client.create_multipart_upload(**create_kwargs)
        upload_id = create_resp["UploadId"]
        parts: list = []
        try:
            part_number = 1
            while True:
                chunk = data_stream.read(part_size)
                if not chunk:
                    break
                part_resp = self.client.upload_part(
                    Bucket=self.bucket,
                    Key=safe,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=chunk,
                )
                parts.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})
                part_number += 1
            self.client.complete_multipart_upload(
                Bucket=self.bucket,
                Key=safe,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            # Best-effort cleanup; abort errors themselves don't
            # mask the original cause. The ``raise`` at the end
            # propagates the upload error to the caller.
            try:
                self.client.abort_multipart_upload(
                    Bucket=self.bucket, Key=safe, UploadId=upload_id,
                )
            except Exception as abort_exc:  # pragma: no cover - defensive
                # Don't lose the abort error completely — log so an
                # operator can manually clean up dangling uploads.
                import logging
                logging.getLogger(__name__).warning(
                    "abort_multipart_upload failed for %s (upload_id=%s): %s",
                    safe, upload_id, abort_exc,
                )
            raise
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
        # Real streaming: hand boto3's StreamingBody back to the caller
        # so large files don't buffer into RAM. ``StreamingBody``
        # already implements ``.read()`` / ``.close()`` so the parser
        # layer's ``with storage.get_object_stream(key) as f:`` pattern
        # works without wrapping. ``base.py`` docstring warns callers
        # to close.
        return resp["Body"]

    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> Iterator[str]:
        """Yield keys under ``prefix``, paginating with ``ContinuationToken``.

        S3 returns at most 1000 keys per ``list_objects_v2`` call; we
        loop until ``IsTruncated=False`` or ``max_keys`` is reached.
        ``MaxKeys`` is set to ``min(max_keys, 1000)`` to honour S3's
        hard page limit while letting callers iterate without
        thinking about pagination.
        """
        # ``MaxKeys`` is bounded by S3's hard limit (1000). We cap
        # ``max_keys`` at 1000 internally and let the caller slice
        # with ``itertools.islice`` if they want fewer.
        page_size = min(max_keys, 1000) if max_keys > 0 else 1000
        continuation_token: Optional[str] = None
        yielded = 0
        while True:
            kwargs: Dict[str, object] = {
                "Bucket": self.bucket,
                "MaxKeys": page_size,
            }
            if prefix:
                kwargs["Prefix"] = prefix
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            resp = self.client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []) or []:
                key = obj.get("Key")
                if key:
                    yield key
                    yielded += 1
                    if max_keys and yielded >= max_keys:
                        return
            if not resp.get("IsTruncated"):
                return
            continuation_token = resp.get("NextContinuationToken")

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

    def resolve_to_local_path(self, key: str) -> str:
        """Download the object into a NamedTemporaryFile and return
        its path.

        Used by the parser layer when the underlying library
        (pdfplumber / python-docx / docling) requires a real
        filesystem path. The temp file is created in the system
        default temp directory and persists until the caller deletes
        it (``finally: Path(p).unlink(missing_ok=True)``) — we do
        NOT auto-cleanup because some parsers cache the path and
        re-open after this method returns.
        """
        import tempfile
        safe = self._validate_key(key)
        # ``delete=False`` so the caller controls cleanup. Carry the
        # original suffix from the storage key (e.g. ``.docx``, ``.pdf``,
        # ``.pptx``) so parser libraries that dispatch on file extension
        # — docling, python-docx, openpyxl — route correctly. Without
        # this suffix the temp file has no extension, docling falls back
        # to the PDF backend (pypdfium2) on .docx inputs, and parsing
        # fails with ``PdfiumError: Failed to load document``.
        tmp = tempfile.NamedTemporaryFile(
            prefix="lumen-storage-",
            suffix=Path(safe).suffix,
            delete=False,
        )
        try:
            # Stream the download — get_object_stream yields a
            # StreamingBody which we close after the copy.
            stream = self.get_object_stream(safe)
            try:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
            finally:
                stream.close()
            tmp.flush()
            tmp.close()
        except Exception:
            # Clean up the half-written temp file on failure.
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return tmp.name

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