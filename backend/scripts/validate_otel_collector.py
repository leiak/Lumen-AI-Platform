"""Phase 1 Group B 4.4 Day 4 (2026-09-05): OTel Collector + Jaeger 链路验证脚本。

3 段验证(每个返 0 = pass / 1 = fail):

1. **Jaeger services API**: ``GET localhost:16686/api/services`` 找
   ``lumen-backend`` —— 后端有 span 上报才会出现 service 名。
2. **OTel Collector /metrics**: ``GET localhost:8889/metrics`` 找
   ``otelcol_receiver_accepted_spans`` —— collector 收到 span 后自监控
   metric 会暴露。
3. **Prometheus scrape**: ``GET localhost:19090/api/v1/targets`` 找
   ``otel-collector`` job state=up —— Prometheus 拉 collector 成功。

镜像 ``bench_minio.py`` / ``audit_*.py`` 模式:argparse + JSON 报告输出
+ 失败 exit code。CI / 本机都好用。

Usage (from backend/):
    python -m scripts.validate_otel_collector
    python -m scripts.validate_otel_collector --jaeger-url http://other-host:16686 \\
        --collector-url http://other-host:8889 \\
        --prometheus-url http://other-host:19090
    python -m scripts.validate_otel_collector --send-test-span  # 主动发 1 个测试 span

Style reference: ``scripts/bench_minio.py`` (sys.path bootstrap + argparse
+ explicit ``sys.exit``).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ``scripts/`` lives next to ``lumen_*`` packages — insert the
# parent (the backend root) onto ``sys.path`` so ``from lumen_core.X
# import Y`` works. Mirrors ``bench_minio.py:36-38``。
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Windows cmd 默认 GBK codepage,中文 / emoji 让 print() 抛
# UnicodeEncodeError 直接打断 CLI。跟 ``bench_minio.py`` 同款修法。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

logger = logging.getLogger("validate_otel_collector")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def parse_args() -> argparse.Namespace:
    """CLI flags."""
    p = argparse.ArgumentParser(
        description=(
            "Phase 1 4.4 Day 4 — 验证 OTel Collector + Jaeger + Prometheus 链路"
        ),
    )
    p.add_argument("--jaeger-url", default="http://localhost:16686",
                   help="Jaeger UI / API 根 URL (默认 localhost:16686)")
    p.add_argument("--collector-url", default="http://localhost:8889",
                   help="OTel Collector prometheus exporter URL (默认 :8889)")
    p.add_argument("--prometheus-url", default="http://localhost:19090",
                   help="Prometheus server URL (默认 localhost:19090)")
    p.add_argument("--service-name", default="lumen-backend",
                   help="期望在 Jaeger 出现的 service 名 (默认 lumen-backend)")
    p.add_argument("--timeout", type=float, default=5.0,
                   help="HTTP 请求超时秒数 (默认 5)")
    p.add_argument("--send-test-span", action="store_true",
                   help="先发 1 个测试 span (走 OTLP gRPC) 再验证,适合冷启动 collector")
    p.add_argument("--output-json", default=None,
                   help="Path to write JSON report (also printed to stdout)")
    return p.parse_args()


# ===== HTTP helper =====


def _http_get_json(url: str, timeout: float) -> Dict[str, Any]:
    """GET URL 期望返 JSON。失败抛 RuntimeError。

    用 urllib 不用 httpx —— 脚本要尽量少依赖(可能 telemetry 链路
    有问题时 httpx 也未必可用),urllib 是 stdlib 兜底。
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
        return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"connection failed: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"non-JSON response from {url}: {e}") from e


def _http_get_text(url: str, timeout: float) -> str:
    """GET URL 返 raw text (Prometheus metrics 格式)。失败抛 RuntimeError。"""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"connection failed: {e.reason}") from e


# ===== 验证 1: Jaeger services =====


def validate_jaeger(
    jaeger_url: str, expected_service: str, timeout: float,
) -> Dict[str, Any]:
    """GET ``{jaeger_url}/api/services`` 找 expected_service。

    Jaeger 返回 ``{"data": ["svc1", "svc2", ...]}`` 格式。
    """
    url = f"{jaeger_url.rstrip('/')}/api/services"
    logger.info("[1/3] Jaeger: GET %s", url)

    payload = _http_get_json(url, timeout)
    services: List[str] = payload.get("data", [])

    found = expected_service in services
    return {
        "check": "jaeger_services",
        "url": url,
        "passed": found,
        "expected_service": expected_service,
        "found_services": services,
        "detail": (
            f"service {expected_service!r} found"
            if found
            else f"service {expected_service!r} NOT in {services}"
        ),
    }


# ===== 验证 2: OTel Collector /metrics =====


def validate_collector(collector_url: str, timeout: float) -> Dict[str, Any]:
    """GET ``{collector_url}/metrics`` 找 ``otelcol_receiver_accepted_spans``。

    collector 自监控 metric 暴露在 prometheus exporter 端点。命名规范:
    - ``otelcol_receiver_accepted_spans{receiver="otlp",transport="grpc"}``
      = OTLP gRPC receiver 接收的 span 数
    - ``otelcol_exporter_sent_spans{exporter="jaeger"}``
      = jaeger exporter 发送的 span 数

    即使没业务 span 走过(冷启动),``otelcol_receiver_accepted_spans{...}``
    metric 本身**会暴露**,值 = 0。所以"指标存在"是 OK 的,不需要真发 span。
    """
    url = f"{collector_url.rstrip('/')}/metrics"
    logger.info("[2/3] Collector: GET %s", url)

    text = _http_get_text(url, timeout)
    lines = text.splitlines()

    # 找 receiver / exporter metric,允许 # HELP / # TYPE 前缀
    metric_patterns = [
        "otelcol_receiver_accepted_spans",
        "otelcol_exporter_sent_spans",
        "otelcol_processor_batch_batch_send_size",
    ]

    matched_metrics: Dict[str, List[str]] = {pat: [] for pat in metric_patterns}
    for line in lines:
        for pat in metric_patterns:
            if line.startswith(pat) and not line.startswith("#"):
                matched_metrics[pat].append(line.strip())

    any_found = any(matched_metrics.values())
    return {
        "check": "otelcol_metrics",
        "url": url,
        "passed": any_found,
        "matched_metrics": {
            k: v[:3] for k, v in matched_metrics.items() if v  # 只 sample 前 3 行
        },
        "total_lines": len(lines),
        "detail": (
            f"found {sum(1 for v in matched_metrics.values() if v)}/{len(metric_patterns)}"
            " expected metric families"
            if any_found
            else f"none of {metric_patterns} found in /metrics"
        ),
    }


# ===== 验证 3: Prometheus scrape =====


def validate_prometheus(
    prometheus_url: str, timeout: float,
) -> Dict[str, Any]:
    """GET ``{prometheus_url}/api/v1/targets`` 找 ``otel-collector`` job state=up。

    Prometheus targets API 返回 ``{"data": {"activeTargets": [...]}}``。
    """
    url = f"{prometheus_url.rstrip('/')}/api/v1/targets"
    logger.info("[3/3] Prometheus: GET %s", url)

    payload = _http_get_json(url, timeout)
    active_targets: List[Dict[str, Any]] = (
        payload.get("data", {}).get("activeTargets", [])
    )

    # 找 labels.job == "otel-collector" 且 health == "up"
    otel_targets = [
        t for t in active_targets
        if t.get("labels", {}).get("job") == "otel-collector"
    ]
    up_targets = [t for t in otel_targets if t.get("health") == "up"]

    return {
        "check": "prometheus_scrape",
        "url": url,
        "passed": len(up_targets) > 0,
        "otel_targets_count": len(otel_targets),
        "up_count": len(up_targets),
        "otel_targets": [
            {
                "labels": t.get("labels"),
                "health": t.get("health"),
                "lastScrape": t.get("lastScrape"),
                "lastError": t.get("lastError"),
            }
            for t in otel_targets
        ],
        "detail": (
            f"otel-collector job: {len(up_targets)}/{len(otel_targets)} target(s) up"
        ),
    }


# ===== 可选: 发 1 个测试 span =====


def send_test_span(
    endpoint: str = "http://localhost:4317", service_name: str = "lumen-backend",
) -> bool:
    """发 1 个 OTLP gRPC 测试 span 到 collector,适合冷启动场景验证。

    走 lumen_core.otel 的 SDK 而不是直接写 proto,避免额外依赖。
    """
    try:
        # 先 reset 再 setup,避免污染已有 TracerProvider
        from lumen_core.otel import reset_for_test, setup_tracing
        from opentelemetry import trace

        reset_for_test()
        ok = setup_tracing(service_name=service_name)
        if not ok:
            logger.warning("setup_tracing failed, cannot send test span")
            return False

        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("validate-otel-collector-test") as span:
            span.set_attribute("validation.source", "validate_otel_collector.py")
            time.sleep(0.1)  # 给 batch processor 时间 flush

        # 强制 flush,BatchSpanProcessor 默认 5s 间隔
        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=2000)  # type: ignore[attr-defined]

        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("send_test_span failed: %s", e)
        return False


# ===== main =====


def main() -> int:
    args = parse_args()
    results: List[Dict[str, Any]] = []

    if args.send_test_span:
        logger.info("Sending test span first...")
        if send_test_span(service_name=args.service_name):
            logger.info("test span sent; waiting 2s for collector + jaeger ingest")
            time.sleep(2)

    # 1. Jaeger
    try:
        r1 = validate_jaeger(args.jaeger_url, args.service_name, args.timeout)
    except Exception as e:  # noqa: BLE001
        r1 = {
            "check": "jaeger_services",
            "url": f"{args.jaeger_url}/api/services",
            "passed": False,
            "error": str(e),
            "detail": f"Jaeger check failed: {e}",
        }
    results.append(r1)

    # 2. Collector
    try:
        r2 = validate_collector(args.collector_url, args.timeout)
    except Exception as e:  # noqa: BLE001
        r2 = {
            "check": "otelcol_metrics",
            "url": f"{args.collector_url}/metrics",
            "passed": False,
            "error": str(e),
            "detail": f"Collector check failed: {e}",
        }
    results.append(r2)

    # 3. Prometheus
    try:
        r3 = validate_prometheus(args.prometheus_url, args.timeout)
    except Exception as e:  # noqa: BLE001
        r3 = {
            "check": "prometheus_scrape",
            "url": f"{args.prometheus_url}/api/v1/targets",
            "passed": False,
            "error": str(e),
            "detail": f"Prometheus check failed: {e}",
        }
    results.append(r3)

    # 输出报告
    passed_count = sum(1 for r in results if r.get("passed"))
    total = len(results)

    print("\n" + "=" * 60)
    print("Phase 1 4.4 Day 4 — OTel Collector 链路验证报告")
    print("=" * 60)
    for r in results:
        status = "✓ PASS" if r.get("passed") else "✗ FAIL"
        print(f"\n[{status}] {r['check']}")
        print(f"  URL:    {r.get('url')}")
        print(f"  Detail: {r.get('detail')}")
        if r.get("error"):
            print(f"  Error:  {r['error']}")
    print("\n" + "=" * 60)
    print(f"Summary: {passed_count}/{total} passed")
    print("=" * 60)

    report = {
        "summary": {"passed": passed_count, "total": total, "all_passed": passed_count == total},
        "results": results,
    }
    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nReport written to {args.output_json}")

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "validate_jaeger",
    "validate_collector",
    "validate_prometheus",
    "send_test_span",
    "main",
]
