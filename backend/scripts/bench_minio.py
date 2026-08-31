"""M38.1 follow-up: MinIO load benchmark.

Generates a workload matrix covering single-tenant sequential,
multi-tenant concurrent, multipart paths, and list latency. The
output is a JSON report with P50/P95/P99 latencies + ops/s per
scenario — the values become a regression anchor for future
storage-layer changes (e.g. switching from MinIO to Aliyun OSS).

Usage (from backend/):
    python -m scripts.bench_minio \\
        --doc-size 100KB \\
        --tenant-count 5 \\
        --docs-per-tenant 50 \\
        --concurrency 10 \\
        --output-json /tmp/minio_bench.json

Style reference: ``scripts/run_rag_eval.py`` (sys.path bootstrap +
argparse + explicit ``sys.exit``). The benchmark uses
``asyncio.to_thread`` to wrap the synchronous boto3 client so the
event loop stays responsive while N uploads are in flight.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

# ``scripts/`` lives next to ``lumen_*`` packages — insert the
# parent (the backend root) onto ``sys.path`` so ``from
# lumen_services.storage import ...`` works. Mirrors
# ``run_rag_eval.py:36-38``.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Windows cmd 默认 GBK codepage,中文 / emoji 让 print() 抛
# UnicodeEncodeError 直接打断 CLI。跟 ``run_rag_eval.py`` 同款修法。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

logger = logging.getLogger("bench_minio")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def parse_args() -> argparse.Namespace:
    """CLI flags. Defaults reproduce the 100 KiB multi-tenant
    baseline from spec §6."""
    p = argparse.ArgumentParser(
        description="M38.1 follow-up — MinIO S3 latency / throughput benchmark",
    )
    p.add_argument("--endpoint", default="http://localhost:29000",
                   help="S3 endpoint URL (default MinIO dev)")
    p.add_argument("--bucket", default="lumen-bench",
                   help="Bucket name (auto-created if missing)")
    p.add_argument("--access-key", default="minioadmin")
    p.add_argument("--secret-key", default="minioadmin")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--doc-size", type=int, default=100 * 1024,
                   help="Per-doc payload size in bytes (default 100 KiB)")
    p.add_argument("--tenant-count", type=int, default=5,
                   help="Number of simulated tenants (default 5)")
    p.add_argument("--docs-per-tenant", type=int, default=50,
                   help="Number of docs per tenant (default 50)")
    p.add_argument("--concurrency", type=int, default=10,
                   help="Max concurrent in-flight PUTs (default 10)")
    p.add_argument("--keep-bucket", action="store_true",
                   help="Skip teardown (leave bucket + objects for inspection)")
    p.add_argument("--output-json", default=None,
                   help="Path to write JSON report (also printed to stdout)")
    return p.parse_args()


def _make_client(args: argparse.Namespace):
    """Build a boto3 S3 client for the benchmark."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=args.endpoint,
        aws_access_key_id=args.access_key,
        aws_secret_access_key=args.secret_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 1, "mode": "standard"},
        ),
        region_name=args.region,
    )


def _percentile_summary(samples: List[float]) -> Dict[str, float]:
    """Compute P50 / P95 / P99 / mean / ops_per_s for a list of
    per-operation latencies. ``samples`` is in milliseconds.

    Returns dict with: p50_ms, p95_ms, p99_ms, mean_ms,
    samples_n, ops_per_s.
    """
    if not samples:
        return {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "mean_ms": 0,
                "samples_n": 0, "ops_per_s": 0}
    sorted_samples = sorted(samples)
    n = len(sorted_samples)

    def _pct(q: float) -> float:
        # Nearest-rank percentile — keeps the test cheap and
        # deterministic without pulling in scipy.
        idx = min(int(q * n), n - 1)
        return sorted_samples[idx]

    mean = statistics.mean(sorted_samples)
    # ops/s = 1000 / mean_ms (per single-op throughput).
    ops_per_s = (1000.0 / mean) if mean > 0 else 0.0
    return {
        "p50_ms": round(_pct(0.50), 3),
        "p95_ms": round(_pct(0.95), 3),
        "p99_ms": round(_pct(0.99), 3),
        "mean_ms": round(mean, 3),
        "samples_n": n,
        "ops_per_s": round(ops_per_s, 2),
    }


async def _bench_put_seq(
    client, bucket: str, key: str, payload: bytes,
) -> List[float]:
    """Single-tenant sequential PUT: latency per op in ms."""
    loop = asyncio.get_running_loop()
    samples: List[float] = []
    # ``put_object`` is sync — wrap it via ``run_in_executor`` so we
    # don't block the event loop. The benchmark only does one PUT
    # at a time here (sequential scenario).
    def _one_put() -> float:
        start = time.perf_counter()
        client.put_object(Bucket=bucket, Key=key, Body=payload)
        return (time.perf_counter() - start) * 1000.0
    # 10 iterations so the percentile summary has a stable signal.
    for _ in range(10):
        samples.append(await loop.run_in_executor(None, _one_put))
    return samples


async def _bench_put_concurrent(
    client, bucket: str, args: argparse.Namespace,
) -> List[float]:
    """Multi-tenant concurrent PUTs up to ``--concurrency`` in-flight.

    Distributes ``tenant_count × docs_per_tenant`` keys across N
    concurrent workers; collects per-op latency in ms.
    """
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(args.concurrency)
    samples: List[float] = []

    payload = os.urandom(args.doc_size)
    total = args.tenant_count * args.docs_per_tenant

    def _make_key(i: int) -> str:
        tenant = (i // args.docs_per_tenant) + 1
        doc = i % args.docs_per_tenant
        # UUID keeps keys unique so multiple runs of the bench don't
        # collide on the same object (which would skew the
        # ``put_object`` rewrite path).
        return f"bench/{tenant}/{doc}-{uuid.uuid4().hex[:6]}.bin"

    async def _one_put(i: int) -> float:
        key = _make_key(i)
        def _do_put() -> float:
            start = time.perf_counter()
            client.put_object(Bucket=bucket, Key=key, Body=payload)
            return (time.perf_counter() - start) * 1000.0
        async with sem:
            return await loop.run_in_executor(None, _do_put)

    tasks = [asyncio.create_task(_one_put(i)) for i in range(total)]
    samples = await asyncio.gather(*tasks)
    return list(samples)


async def _bench_get(
    client, bucket: str, key: str, iterations: int = 20,
) -> List[float]:
    """GET latency with warm cache (sequential)."""
    loop = asyncio.get_running_loop()

    def _one_get() -> float:
        start = time.perf_counter()
        resp = client.get_object(Bucket=bucket, Key=key)
        # Drain the body so the round-trip is honest.
        resp["Body"].read()
        return (time.perf_counter() - start) * 1000.0
    samples = []
    for _ in range(iterations):
        samples.append(await loop.run_in_executor(None, _one_get))
    return samples


async def _bench_list(
    client, bucket: str, iterations: int = 10,
) -> List[float]:
    """``list_objects_v2`` latency — full-bucket scan."""
    loop = asyncio.get_running_loop()

    def _one_list() -> float:
        start = time.perf_counter()
        # Walk pagination so we measure real cost, not just the
        # first page.
        token = None
        while True:
            kwargs: Dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            resp = client.list_objects_v2(**kwargs)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return (time.perf_counter() - start) * 1000.0
    samples = []
    for _ in range(iterations):
        samples.append(await loop.run_in_executor(None, _one_list))
    return samples


async def _bench_multipart(
    client, bucket: str, args: argparse.Namespace,
) -> List[float]:
    """Multipart PUTs at the configured ``--doc-size`` to exercise
    the ``create_multipart_upload`` + ``complete`` path."""
    loop = asyncio.get_running_loop()
    sem = asyncio.Semaphore(args.concurrency)
    payload = os.urandom(args.doc_size)
    part_size = 5 * 1024 * 1024
    iterations = max(3, args.docs_per_tenant // 5)  # cap to keep bench fast

    async def _one_put(i: int) -> float:
        key = f"bench/mp/{i}-{uuid.uuid4().hex[:6]}.bin"
        def _do() -> float:
            start = time.perf_counter()
            create = client.create_multipart_upload(Bucket=bucket, Key=key)
            upload_id = create["UploadId"]
            parts = []
            try:
                pn = 1
                while True:
                    offset = (pn - 1) * part_size
                    if offset >= len(payload):
                        break
                    end = min(offset + part_size, len(payload))
                    body = payload[offset:end]
                    part_resp = client.upload_part(
                        Bucket=bucket, Key=key, PartNumber=pn,
                        UploadId=upload_id, Body=body,
                    )
                    parts.append({"PartNumber": pn, "ETag": part_resp["ETag"]})
                    pn += 1
                client.complete_multipart_upload(
                    Bucket=bucket, Key=key, UploadId=upload_id,
                    MultipartUpload={"Parts": parts},
                )
            except Exception:
                client.abort_multipart_upload(
                    Bucket=bucket, Key=key, UploadId=upload_id,
                )
                raise
            return (time.perf_counter() - start) * 1000.0
        async with sem:
            return await loop.run_in_executor(None, _do)
    tasks = [asyncio.create_task(_one_put(i)) for i in range(iterations)]
    return list(await asyncio.gather(*tasks))


def _ensure_bucket(client, bucket: str) -> None:
    """Create the bench bucket if missing."""
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)


def _cleanup_bucket(client, bucket: str) -> None:
    """Drain the bench bucket + delete it."""
    try:
        token = None
        while True:
            kwargs: Dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            resp = client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []) or []:
                client.delete_object(Bucket=bucket, Key=obj["Key"])
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        client.delete_bucket(Bucket=bucket)
    except Exception as exc:  # pragma: no cover - cleanup best-effort
        logger.warning("cleanup bucket %s failed: %s", bucket, exc)


async def main() -> int:
    args = parse_args()
    client = _make_client(args)

    # Sanity check: bucket exists / endpoint reachable.
    try:
        client.list_buckets()
    except Exception as exc:
        print(f"ERROR: MinIO unreachable at {args.endpoint}: {exc}", file=sys.stderr)
        return 1
    _ensure_bucket(client, args.bucket)

    logger.info(
        "benchmarking endpoint=%s bucket=%s doc_size=%d tenant_count=%d "
        "docs_per_tenant=%d concurrency=%d",
        args.endpoint, args.bucket, args.doc_size,
        args.tenant_count, args.docs_per_tenant, args.concurrency,
    )

    # Pre-populate one key for the sequential + get scenarios.
    warm_key = "bench/_warmup/h.bin"
    warm_payload = os.urandom(args.doc_size)
    client.put_object(Bucket=args.bucket, Key=warm_key, Body=warm_payload)

    # Run each scenario.
    put_seq_samples = await _bench_put_seq(client, args.bucket, warm_key, warm_payload)
    put_conc_samples = await _bench_put_concurrent(client, args.bucket, args)
    get_samples = await _bench_get(client, args.bucket, warm_key)
    list_samples = await _bench_list(client, args.bucket)
    mp_samples = []
    if args.doc_size >= 5 * 1024 * 1024:
        mp_samples = await _bench_multipart(client, args.bucket, args)

    # Build the report.
    report = {
        "config": {
            "endpoint": args.endpoint,
            "bucket": args.bucket,
            "doc_size_bytes": args.doc_size,
            "tenant_count": args.tenant_count,
            "docs_per_tenant": args.docs_per_tenant,
            "concurrency": args.concurrency,
        },
        "put": {
            "single_sequential": _percentile_summary(put_seq_samples),
            "multi_concurrent": _percentile_summary(put_conc_samples),
        },
        "get": _percentile_summary(get_samples),
        "list": _percentile_summary(list_samples),
    }
    if mp_samples:
        report["put"]["multipart"] = _percentile_summary(mp_samples)

    # Emit.
    report_text = json.dumps(report, indent=2, ensure_ascii=False)
    print(report_text)
    if args.output_json:
        Path(args.output_json).write_text(report_text, encoding="utf-8")
        logger.info("wrote report → %s", args.output_json)

    if not args.keep_bucket:
        _cleanup_bucket(client, args.bucket)
    else:
        logger.info("kept bucket %s for inspection (--keep-bucket)", args.bucket)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))