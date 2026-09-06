"""Phase 1 Group B 4.4 Day 6 (2026-09-06): OTel Span-derived metrics。

**为什么**:Day 1-5 ship 了 OTel trace pipeline,但只有 trace 维度可观测
(span name + attributes 散落在 Jaeger trace tree),没有**聚合**的 RPS /
error rate / P95 —— 排查"哪个 span 在某段时间内变慢 / 报错率上升"得手动翻
上千个 trace。Span-derived metrics 把每条 span 落到 Prometheus,PromQL
一秒出答案。

**为什么不新加 prometheus_client metric**:prometheus_client 是业务代码
主动埋点(``counter.inc()``),跨业务路径容易漂移(漏埋 / 多埋 / 改名)。
span-derived 走 OTel 单一数据源,跟现有 trace / log 关联天然成立
(``service.name`` / ``trace_id`` 自动 join)。``http_requests_total``
仍由 ``lumen_api/middleware/prometheus.py`` 维护;``lumen_llm_calls_total``
等业务 metric 仍走 prometheus_client。**互补**,不替代。

**怎么做**(集成方式 Option B):
1. ``SpanObserverMetricExporter`` 是 ``SpanProcessor`` 子类,挂在
   ``TracerProvider.add_span_processor()`` 上 —— 复用 Day 5 ``force_flush``
   / atexit / ``reset_for_test`` 生命周期。
2. ``on_end(span)`` 时读 span attributes(走 ``_ALLOWED_LABEL_KEYS``
   frozenset 过滤防 cardinality 爆炸)+ 算 duration(秒),推到 ``Counter``
   ``lumen.span.events`` 和 ``Histogram`` ``lumen.span.duration``。
3. Exporter 走 OTLP gRPC ``:4317``(同 span 共用 collector);PeriodicExportingMetricReader
   间隔 15000ms 对齐 Prometheus scrape_interval。
4. ``_status_class(http_status)`` 把 int 状态码 5 段分类(1xx / 2xx / 3xx /
   4xx / 5xx),让 4xx / 5xx series 数量可控。
5. ``_KNOWN_SPAN_NAMES`` 之外 ``span_name`` collapse 到 ``"other"``,未知
   业务 span 名不污染 metric 维度。

**幂等性**(同 ``otel.py`` 套路):
- 多次 ``setup_metrics()`` 只有第一次生效(``_initialized`` 守门)
- ``reset_for_test()`` 清 MeterProvider + SpanProcessor,测试间隔离

**Cardinality 估算**(< 670 series):
- workflow.node 最重:1 span_name × 5 status × 3 type × 22 node-type = 330
- 其他大多 < 50,OTel SDK 100k / Prometheus 10k 建议都达标

**踩坑**:
- 重复 ``metrics.set_meter_provider()`` OTel SDK 会 warn + 拒,直接走
  module-level ``_METER_PROVIDER`` / ``_METER_PROVIDER_SET_ONCE._done``
  reset
- ``PeriodicExportingMetricReader`` 内部起后台线程,pytest teardown 必须
  ``reader.shutdown()`` + ``meter_provider.shutdown()`` 防 daemon thread
  在 pytest 关闭 stdout 后写 "I/O on closed file"
- ``http.response.status_code`` 是 int,送 Counter/Histogram attributes
  OTel 接受但 Prometheus 端建议转字符串(``_status_class`` 已经做了)
- ``_KNOWN_SPAN_NAMES`` 必须包含所有当前 ``traced_span`` 已 ship 的 span
  名,新增 span 类型时记得同步扩
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from opentelemetry.sdk.trace import SpanProcessor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模块级 state:setup_metrics 幂等守门。
# ---------------------------------------------------------------------------
_initialized: bool = False
_init_lock = threading.Lock()

# span processor 实例(module 内唯一,挂在 TracerProvider 上)。
# 暴露给 otel.py 改写注入路径使用,保持单一来源。
_processor: "Optional[SpanObserverMetricExporter]" = None
_meter_provider: Any = None  # MeterProvider 或 None
_reader: Any = None  # PeriodicExportingMetricReader / InMemoryMetricReader


# ---------------------------------------------------------------------------
# Label / span_name allowlist —— 防止 cardinality 爆炸。
# ---------------------------------------------------------------------------

# Cardinality allowlist:span attribute 里只有这 12 个 key 进 Prometheus label。
# 其他属性静默丢弃(仍 inc counter,但不增加 series 维度)。
# 排序无关,frozenset 查 O(1)。
#
# 设计原则:每个 key 的 cardinality 各自有限(status_class 5 段 / method ~10 /
# kind 4 / 业务 status 5-10 / backend 2-3 / type 22),组合后
# < 670 series,远低于 OTel SDK 100k / Prometheus 10k 建议上限。
_ALLOWED_LABEL_KEYS: frozenset = frozenset({
    "span.kind",  # INTERNAL / SERVER / CLIENT / PRODUCER
    "http.request.method",  # GET / POST / PUT / DELETE ...
    "http.response.status_code",  # 已转 status_class
    "llm.call_kind",  # astream / invoke / batch
    "embedding.call_kind",  # sync_query / async_documents ...
    "chat.status",  # success / error / timeout
    "llm.status",  # success / error / timeout
    "retrieval.backend",  # faiss / es
    "retrieval.rerank_enabled",  # true / false
    "retrieval.has_filter",  # true / false
    "workflow.status",  # completed / failed / cancelled
    "workflow.node.status",  # success / error / skipped
    "workflow.node.type",  # llm / code / http / knowledge_retrieval ...
    "db.system",  # mysql / postgresql / redis ...
    "messaging.system",  # celery / kafka ...
})


# 已知的 span name 白名单。业务新加 span 类型时,必须同步扩展这里。
# 不在白名单的 span_name 静默 collapse 到 "other",防止业务方拼 typo
# 产生 cardinality 爆增。
#
# 维护约定:任何 @traced_span(name="...") 新增的 name 都加到这里。
_KNOWN_SPAN_NAMES: frozenset = frozenset({
    "chat.stream",
    "chat.endpoint",
    "embedding.generate",
    "retrieval.search",
    "workflow.run",
    "workflow.node",
    "llm.chat",
    "http.client",  # HTTPXClientInstrumentor 出站 span
    "http.server",  # FastAPIInstrumentor 入站 span
    "celery.task",  # CeleryInstrumentor task span
    "sqlalchemy.orm",  # SQLAlchemyInstrumentor ORM span
    "pymysql.connect",  # PyMySQLInstrumentor raw connect
})


# ---------------------------------------------------------------------------
# HTTP status code 5 段映射。
# ---------------------------------------------------------------------------

def _status_class(http_status: Any) -> str:
    """把 HTTP 状态码转 5 段字符串标签("1xx" / "2xx" / "3xx" / "4xx" /
    "5xx"),让 Prometheus series 数量固定。

    边界:199/200/299/399/499/599/600 全部测过,确保不丢 P99 计算精度。
    非数字 / None / 负数(< 100) / 大于 599 一律 fallback "UNSET"(单
    series,对所有异常值统一归并)。
    """
    if http_status is None:
        return "UNSET"
    try:
        n = int(http_status)
    except (TypeError, ValueError):
        return "UNSET"
    # 负数 / 0~99 是无效 HTTP 状态码,直接归 UNSET(避免 1xx 误命中)
    if n < 100:
        return "UNSET"
    if n < 200:
        return "1xx"
    if n < 300:
        return "2xx"
    if n < 400:
        return "3xx"
    if n < 500:
        return "4xx"
    if n < 600:
        return "5xx"
    return "UNSET"


# ---------------------------------------------------------------------------
# Span attribute → Prometheus label 提取。
# ---------------------------------------------------------------------------

def _extract_labels(span) -> Dict[str, str]:
    """从 OTel SpanReadOnlySpanInterface 抽 label dict(走 allowlist 过滤)。

    Args:
        span: OTel ReadableSpan 实例,提供 .attributes (Mapping | None) +
            .kind (SpanKind) + .name (str) + .status (Status) +
            .instrumentation_scope / .resource 等。

    Returns:
        Dict[str, str]:仅含 ``_ALLOWED_LABEL_KEYS`` 里 key 的 attribute,
        强制转为 str(Prometheus label 必须是字符串);``span_name`` 不在
        白名单,但作为单独 key 加进去(collapse 走 ``_KNOWN_SPAN_NAMES``)。
        总是返回非 None dict,空 dict 也行。

    Cardinality 守门:
    - attribute key 不在白名单 → 丢弃
    - ``span_name`` 不在 ``_KNOWN_SPAN_NAMES`` → collapse 到 ``"other"``
    - ``http.response.status_code`` 是 int → 走 ``_status_class`` 5 段映射
    - value 转 str;None / bool / int / float / str 全支持(bool → "True"/"False")
    """
    labels: Dict[str, str] = {}

    # span_name(不在 _ALLOWED_LABEL_KEYS,单独处理)
    # KNOWN 白名单外(包含 None / 空字符串)一律 collapse 到 "other",
    # 跟 _KNOWN_SPAN_NAMES 的语义一致:防 typo + 防 None 产生 "None" 字符串污染
    span_name = getattr(span, "name", None)
    if not span_name or span_name not in _KNOWN_SPAN_NAMES:
        labels["span_name"] = "other"
    else:
        labels["span_name"] = span_name

    # span.kind:SDK 是 SpanKind enum(0=INTERNAL/1=SERVER/2=CLIENT/3=PRODUCER),
    # 转 name 让 Prometheus label 友好。
    kind = getattr(span, "kind", None)
    if kind is not None:
        kind_name = getattr(kind, "name", None) or str(kind)
        labels["span.kind"] = str(kind_name)

    attrs = getattr(span, "attributes", None)
    if not attrs:
        return labels

    for key, value in attrs.items():
        if key not in _ALLOWED_LABEL_KEYS:
            continue

        if key == "http.response.status_code":
            # int 状态码 → 5 段分类(series 数量固定)
            labels["http.response.status_code"] = _status_class(value)
            continue

        # bool/int/float/str 全转 str;None 跳过(不写 label,避免 series
        # "None" 污染)
        if value is None:
            continue
        if isinstance(value, bool):
            labels[key] = "True" if value else "False"
        else:
            labels[key] = str(value)

    return labels


# ---------------------------------------------------------------------------
# SpanProcessor 子类:on_end 时把 span 转 Counter + Histogram。
# ---------------------------------------------------------------------------

class SpanObserverMetricExporter(SpanProcessor):
    """``SpanProcessor`` 子类 —— ``on_end`` 时把每条 span 转 Counter
    ``lumen.span.events`` + Histogram ``lumen.span.duration``。

    **生命周期**:
    - 挂在 ``TracerProvider.add_span_processor(self)`` 上
    - OTel SDK 每个 span end 时调 ``on_end(span)``
    - uvicorn shutdown / atexit 触发 ``force_flush()``
    - ``reset_for_test()`` 调 ``shutdown()``

    **设计要点**:
    - ``_counters`` / ``_histograms`` 按 ``(frozen_label_tuple)`` 分桶
      —— OTel Counter / Histogram 是 per-label 实例,需要 dict 索引
    - ``_get_meter()`` lazy init —— 避免 setup 顺序耦合(先 setup_tracing
      再 setup_metrics 时 MeterProvider 还在;反过来 MeterProvider 还没起)
    - ``on_end`` 整体 try/except 包,单 span 失败不污染后续
    - 跳过没有 end_time 的 span(异常路径 / SdkSpan 未正常关闭)
    """

    # 与 lumen_core.metrics.http_request_duration_seconds 同 bucket
    _DURATION_BUCKETS: Tuple[float, ...] = (
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    )

    def __init__(self, histogram_buckets: Optional[Iterable[float]] = None) -> None:
        self._counters: Dict[Tuple[Tuple[str, str], ...], Any] = {}
        self._histograms: Dict[Tuple[Tuple[str, str], ...], Any] = {}
        self._meter: Any = None  # lazy init
        self._buckets: Tuple[float, ...] = (
            tuple(histogram_buckets) if histogram_buckets else self._DURATION_BUCKETS
        )
        # 跨进程 / 跨进程 lifespan 复用时 on_end 可能撞 invalid state,
        # 失败计数方便 debug。
        self._fail_count = 0

    def _get_meter(self):
        """懒拿 meter —— 第一次 on_end 时取 global MeterProvider。"""
        if self._meter is None:
            from opentelemetry import metrics

            self._meter = metrics.get_meter("lumen.span.observer")
        return self._meter

    def on_start(self, span, parent_context=None) -> None:
        """SpanProcessor.on_start:no-op(只关心 end 时的 duration)。"""
        return None

    def on_end(self, span) -> None:
        """OTel SDK 每个 span end 时调一次,转 Counter + Histogram。"""
        try:
            self._record(span)
        except Exception as e:  # noqa: BLE001
            # 单 span 失败不污染后续 —— 计数 + logger.debug(不 warning,
            # 频繁失败时刷屏)
            self._fail_count += 1
            if self._fail_count <= 5 or self._fail_count % 100 == 0:
                logger.debug("SpanObserverMetricExporter.on_end failed: %s", e)

    def _record(self, span) -> None:
        """把一条 span 转 Counter + Histogram。"""
        start_ns = getattr(span, "start_time", None)
        end_ns = getattr(span, "end_time", None)
        # 异常路径(end_time 未设)或时间颠倒直接放弃
        if not start_ns or not end_ns or end_ns < start_ns:
            return

        labels = _extract_labels(span)
        label_key = tuple(sorted(labels.items()))

        # Counter:inc 1
        counter = self._counters.get(label_key)
        if counter is None:
            counter = self._get_meter().create_counter(
                name="lumen.span.events",
                unit="1",
                description="Span end events derived from OTel traces.",
            )
            self._counters[label_key] = counter
        counter.add(1, attributes=labels)

        # Histogram:record duration(秒)
        histogram = self._histograms.get(label_key)
        if histogram is None:
            histogram = self._get_meter().create_histogram(
                name="lumen.span.duration",
                unit="s",
                description="Span duration in seconds.",
            )
            self._histograms[label_key] = histogram
        duration_s = (end_ns - start_ns) / 1e9
        histogram.record(duration_s, attributes=labels)

    def shutdown(self) -> None:
        """测试 / 进程退出时清空 in-memory 状态(不影响 global MeterProvider)。"""
        self._counters.clear()
        self._histograms.clear()
        self._meter = None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """强制 flush buffered metric。

        SpanObserverMetricExporter 自身是 buffer-less(每次 on_end 同步
        add 进 Counter/Histogram,buffer 在 PeriodicExportingMetricReader
        里),所以这里只 trigger global MeterProvider 的 reader.flush,
        让 Prometheus exporter 把当前 cycle 推走。

        Returns:
            True on success, False on exception(已 swallow)。
        """
        try:
            global _reader, _meter_provider
            reader = _reader
            if reader is None and _meter_provider is not None:
                # fallback:取 MeterProvider 上第一个 reader
                readers = getattr(_meter_provider, "_metric_readers", None) or []
                reader = readers[0] if readers else None
            if reader is not None and hasattr(reader, "force_flush"):
                reader.force_flush(timeout_millis=timeout_millis)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("SpanObserverMetricExporter.force_flush failed: %s", e)
            return False


# ---------------------------------------------------------------------------
# 模块公开 API:setup_metrics / force_flush / reset_for_test。
# ---------------------------------------------------------------------------

# 与 otel.py:_build_metric_mode() 对齐:OTLP 三种 mode 才启 metric;
# console / none / 空值都不启(console 无 ConsoleMetricExporter)。
_OTLP_MODES = frozenset({"otlp", "otlp_grpc", "otlp_http"})


def setup_metrics(
    endpoint: Optional[str] = None,
    service_name: Optional[str] = None,
    deployment_environment: Optional[str] = None,
) -> bool:
    """Phase 1 Group B 4.4 Day 6 (2026-09-06): setup OTel metric SDK。

    决策:挂第二个 ``SpanProcessor`` 子类到现有 ``TracerProvider``,复用
    Day 5 ``force_flush`` / atexit 生命周期。新建 MeterProvider +
    PeriodicExportingMetricReader + OTLPMetricExporter(走 OTLP gRPC 默认
    :4317;HTTP 模式 lazy import,本项目依赖里只有 gRPC,装环境可选)。

    Returns:
        True if actually initialized (MeterProvider set + reader +
        SpanProcessor attached).False if disabled (OTEL_EXPORTER=none /
        console) or already initialized (idempotent),or exception
        swallowed。

    Raises:
        不抛异常:任何 import / setup 失败都降级到 logger.warning + return False,
        不阻塞 uvicorn 启动(OTel 是可观测性,挂了不应挂业务)。
    """
    global _initialized, _processor, _meter_provider, _reader

    with _init_lock:
        if _initialized:
            logger.debug("OTel metrics already initialized, skipping")
            return False

        exporter_mode = (os.getenv("OTEL_EXPORTER") or "console").strip().lower()
        if exporter_mode not in _OTLP_MODES:
            # none / off / noop / disabled / 空值 / console — 都不启
            logger.info(
                "OTEL_EXPORTER=%r, skipping OTel metrics setup "
                "(only otlp / otlp_grpc / otlp_http enable span-derived metrics)",
                exporter_mode,
            )
            return False

        try:
            from opentelemetry import metrics
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.sdk.resources import Resource

            from lumen_core.otel_config import build_resource

            # resource 复用 build_resource(跟 span 同 service.name /
            # deployment.environment),让 OTel metric 在 Prometheus /
            # collector 端跟 trace / log 自动 join。
            resource = build_resource(
                service_name=service_name,
                deployment_environment=deployment_environment,
            )

            # MetricExporter:默认 OTLP gRPC。HTTP 模式 lazy import(项目
            # 当前依赖只有 gRPC exporter,生产可按需 opentelemetry-exporter-otlp-proto-http)。
            metric_endpoint = (
                endpoint
                or os.getenv("OTEL_ENDPOINT")
                or os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
            )

            if exporter_mode == "otlp_http":
                try:
                    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # type: ignore[import-not-found]
                        OTLPMetricExporter,
                    )
                except ImportError:
                    logger.warning(
                        "otlp_http metric exporter not installed "
                        "(pip install opentelemetry-exporter-otlp-proto-http); "
                        "falling back to OTLP gRPC :4317",
                    )
                    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                        OTLPMetricExporter,
                    )
                    metric_endpoint = metric_endpoint or "http://localhost:4317"
                else:
                    metric_endpoint = metric_endpoint or "http://localhost:4318/v1/metrics"
            else:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )
                metric_endpoint = metric_endpoint or "http://localhost:4317"

            # HTTPS_PROXY 防御(同 otel.py:_build_exporter Day 5 注释):
            # OTLP gRPC metric exporter 内部走 grpc.insecure_channel,自动
            # 读 HTTPS_PROXY / GRPC_PROXY env 走代理,跟 span exporter 同
            # 根因 — 复用同套 warning 文案。
            if os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("GRPC_PROXY"):
                logger.warning(
                    "HTTPS_PROXY/GRPC_PROXY env detected (value=%s/%s/%s); "
                    "OTLP gRPC metric exporter will route through proxy. "
                    "To bypass, set GRPC_PROXY=\"\" / HTTPS_PROXY=\"\".",
                    os.getenv("HTTPS_PROXY"),
                    os.getenv("https_proxy"),
                    os.getenv("GRPC_PROXY"),
                )

            exporter = OTLPMetricExporter(endpoint=metric_endpoint, timeout=2)
            reader = PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=15000,  # 对齐 Prometheus scrape_interval: 15s
                export_timeout_millis=5000,
            )

            meter_provider = MeterProvider(
                metric_readers=[reader],
                resource=resource,
                # daemon thread 退出时不强杀(避免 atexit 阶段 metric 还在
                # tick 时硬杀 — 留给 PeriodicExportingMetricReader 走
                # shutdown 自己清,见 otel.py:_shutdown_cleanup 同模式)
                shutdown_on_exit=False,
            )
            metrics.set_meter_provider(meter_provider)

            _meter_provider = meter_provider
            _reader = reader

            # 挂 SpanProcessor 到当前 TracerProvider —— Otel SDK 的
            # add_span_processor 是 method on TracerProvider 实例,需要从
            # global 拿。如果当前没有 TracerProvider(direct setup_metrics
            # 没先调 setup_tracing),fallback 到 NoOpTracerProvider,SpanProcessor
            # 收不到任何 span → 静默 no-op(这是 defensive,正常流程
            # lumen_main.py 先 setup_tracing 再 setup_metrics)。
            processor = SpanObserverMetricExporter()
            try:
                from opentelemetry import trace as _otel_trace

                _provider = _otel_trace.get_tracer_provider()
                if hasattr(_provider, "add_span_processor"):
                    _provider.add_span_processor(processor)
                else:
                    logger.debug(
                        "Current TracerProvider doesn't support add_span_processor; "
                        "SpanObserverMetricExporter installed but inactive",
                    )
            except Exception as e:  # noqa: BLE001
                logger.debug("attach SpanObserverMetricExporter failed: %s", e)

            _processor = processor
            _initialized = True

            logger.info(
                "OpenTelemetry metrics initialized: exporter=%s endpoint=%s service=%s env=%s",
                exporter_mode,
                metric_endpoint,
                resource.attributes.get("service.name"),
                resource.attributes.get("deployment.environment"),
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenTelemetry metrics setup failed: %s", e)
            return False


def force_flush(timeout_millis: int = 5000) -> bool:
    """强制 flush 当前 MeterProvider 的 buffered metric。

    镜像 ``lumen_core.otel.force_flush`` 语义:
    - uvicorn lifespan shutdown 调一次(timeout_millis=5000)
    - atexit 兜底再调一次(timeout_millis=3000,Day 5 同模式)
    - 失败 swallow + 返 False,不抛

    Returns:
        True if force_flush was called; False if not initialized / no-op
        provider / exception raised。
    """
    try:
        reader = _reader
        if reader is None and _meter_provider is not None:
            readers = getattr(_meter_provider, "_metric_readers", None) or []
            reader = readers[0] if readers else None
        if reader is not None and hasattr(reader, "force_flush"):
            reader.force_flush(timeout_millis=timeout_millis)
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("OTel metrics force_flush failed: %s", e)
        return False


def reset_for_test() -> None:
    """测试间隔离:清掉 global MeterProvider + SpanProcessor + reader。

    pytest fixture 推荐(镜像 test_otel_business_spans.py):
        @pytest.fixture(autouse=True)
        def _otel_metrics_test_env():
            yield
            from lumen_core.otel_metrics import reset_for_test
            reset_for_test()

    OTel 一次锁(metrics module 跟 trace module 同模式):直接 reset
    module-level ``_METER_PROVIDER`` + ``_METER_PROVIDER_SET_ONCE._done``
    来达到完全 reset 效果,只用于 pytest fixture 隔离,生产代码不会调到
    这里。
    """
    global _initialized, _processor, _meter_provider, _reader

    # 关 reader + meter provider,避免 PeriodicExportingMetricReader 后台
    # 线程在 pytest 关闭 stdout 后写 "I/O on closed file"
    if _reader is not None:
        try:
            _reader.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug("MetricReader shutdown failed: %s", e)
    if _meter_provider is not None:
        try:
            _meter_provider.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug("MeterProvider shutdown failed: %s", e)

    # 关 processor in-memory state
    if _processor is not None:
        try:
            _processor.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug("SpanObserverMetricExporter shutdown failed: %s", e)

    _processor = None
    _meter_provider = None
    _reader = None

    # 清 OTel metrics module 一次锁 + module-level state。
    # OTel 1.36 把 module-level state 放在 ``opentelemetry.metrics._internal``
    # 子模块(public ``opentelemetry.metrics`` 命名空间没有这两个
    # attribute — 但 reset 路径必须改 internal state 才能让下次
    # ``set_meter_provider`` 生效)。
    try:
        from opentelemetry.metrics import _internal as _otel_metrics_internal

        mp = getattr(_otel_metrics_internal, "_METER_PROVIDER", None)
        if mp is not None:
            _otel_metrics_internal._METER_PROVIDER = None  # type: ignore[attr-defined]
        once = getattr(_otel_metrics_internal, "_METER_PROVIDER_SET_ONCE", None)
        if once is not None and hasattr(once, "_done"):
            once._done = False  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.debug("MeterProvider module-level reset failed: %s", e)

    _initialized = False


def is_initialized() -> bool:
    """测试 / 调试用:当前进程是否已 setup_metrics()。"""
    return _initialized


def get_processor() -> "Optional[SpanObserverMetricExporter]":
    """测试 / debug 用:拿当前 SpanObserverMetricExporter 实例。"""
    return _processor


__all__ = [
    "SpanObserverMetricExporter",
    "setup_metrics",
    "force_flush",
    "reset_for_test",
    "is_initialized",
    "get_processor",
    "_ALLOWED_LABEL_KEYS",
    "_KNOWN_SPAN_NAMES",
    "_status_class",
    "_extract_labels",
]