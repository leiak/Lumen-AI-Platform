"""Phase 1 Group B 4.4 Day 7 (2026-09-06): OTel log signal pipeline。

**为什么**:Day 1-6 ship 了 OTel trace + span-derived metric 两条 pipeline,
但 log ↔ trace 关联还缺:
- stdout JSON 主通道只 inject ``trace_id``,**没** ``span_id`` / ``trace_flags``
- 日志没走 OTel log signal,collector 看不到 log record

**做什么**:挂第三个 OTel signal (logs) 到同一套 setup 框架 —— 镜像
``otel_metrics.py`` 的 Option B 模式:
1. ``setup_logs()`` 按 ``OTEL_LOG_EXPORTER`` env 选 exporter(默认 disabled,
   运维按需开),装到 global ``LoggerProvider``
2. Exporter 走 OTLP gRPC ``:4317``(同 trace / metric 共用 collector)
3. ``BatchLogRecordProcessor`` 间隔 5000ms / timeout 3000ms — 比 metric 短
   (metric 15s),日志要近实时,运维 grep trace 时 log 已经落库
4. ``lumen_core.logging_config.OTelLogBridgeHandler`` 把 stdlib ``LogRecord``
   转 OTel ``LogRecord`` emit 到 Logger —— **同一 record 双写**(stdout JSON
   + OTel log signal),向后兼容 Phase 0 不破坏

**集成方式**(同 otel_metrics.py Option B):
- ``otel._do_setup()`` 末尾 OTLP 模式下级联调 ``setup_logs()``
- ``otel.force_flush()`` 串联 trace → metric → log flush
- ``otel.reset_for_test()`` 串联 metric → log reset
- atexit 双保险(SIGKILL 时 lifespan shutdown 不跑,atexit 兜底)
- ``reset_for_test()`` 同时清 ``opentelemetry._logs._internal._LOGGER_PROVIDER``
  + ``_LOGGER_PROVIDER_SET_ONCE._done``(镜像 metric 模式)

**为什么 env gating 用独立 ``OTEL_LOG_EXPORTER`` 而非沿用 ``OTEL_EXPORTER``**:
- ``OTEL_EXPORTER`` 是 Day 1 立的统一开关,trace + metric 共用
- log signal **默认 disabled**(开 log signal 会让 Phase 0 stdout JSON + OTel
  logs 双通道产生 2x 噪音),需要独立 env 让运维按需开
- 共用同套 OTLP 值 (``otlp`` / ``otlp_grpc`` / ``otlp_http``)

**为什么不直接接 Loki 容器**:
- Loki + Promtail + Grafana 数据源 + dashboard 工作量估 1-2d
- Day 7 收口在"otel-collector logs pipeline 验证能收 log record",Day 8 再接
  Loki / file exporter 替换 debug exporter

**踩坑**:
- OTel SDK 1.36 的 ``opentelemetry._logs`` 在 ``_internal`` 子模块藏
  ``_LOGGER_PROVIDER`` + ``_LOGGER_PROVIDER_SET_ONCE``,直接 reset 这两个
  attribute 才能让下次 ``set_logger_provider()`` 生效 —— 跟 metric 同坑
- ``opentelemetry.exporter.otlp.proto.http._log_exporter`` 项目依赖里没装,
  lazy import fallback 到 gRPC :4317 + warning
- ``BatchLogRecordProcessor.schedule_delay_millis`` / ``export_timeout_millis``
  直接传 int(SDK 接受 ms),不是 timedelta
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 模块级 state:setup_logs 幂等守门。
# ---------------------------------------------------------------------------
_initialized: bool = False
_init_lock = threading.Lock()

_logger_provider: Any = None  # LoggerProvider 或 None
_processor: Any = None  # BatchLogRecordProcessor 或 None


# ---------------------------------------------------------------------------
# Env gating 守门 —— 跟 otel_metrics._OTLP_MODES 同模式但独立 env。
# ---------------------------------------------------------------------------

# OTLP 三种 mode 才启 log signal;console / none / 空值 / 未知 → disabled。
_OTLP_MODES = frozenset({"otlp", "otlp_grpc", "otlp_http"})

# 显式 disable 的几个等价写法(运维写哪个都行)。
_DISABLED_MODES = frozenset({"none", "off", "noop", "disabled", ""})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logs(
    endpoint: Optional[str] = None,
    resource: Any = None,
) -> bool:
    """Phase 1 Group B 4.4 Day 7 (2026-09-06): setup OTel log SDK。

    决策:镜像 ``otel.setup_tracing`` 模式 + Day 6 ``otel_metrics.setup_metrics``
    模式(env gating + 幂等 + HTTPS_PROXY 守门 + HTTP mode lazy import)。

    Returns:
        True if actually initialized (LoggerProvider set + processor +
        exporter attached)。False if disabled (``OTEL_LOG_EXPORTER`` unset /
        ``none`` / ``off`` / ``noop`` / ``disabled`` / 空值 / 未知 mode) or
        already initialized (idempotent),or exception swallowed。

    Raises:
        不抛异常:任何 import / setup 失败都降级到 ``logger.warning`` + return
        False,不阻塞 uvicorn 启动(OTel 是可观测性,挂了不应挂业务)。

    Why disabled by default:
        Phase 0 stdout JSON 仍是主通道(向后兼容 Promtail / docker logs 抓取)。
        默认开 OTel log signal 会产生 2x 噪音(同一条 record 双写)。运维开
        log signal 通常是为了接 Loki 场景(Day 8),按需开即可。
    """
    global _initialized, _logger_provider, _processor

    with _init_lock:
        if _initialized:
            logger.debug("OTel logs already initialized, skipping")
            return False

        mode = (os.getenv("OTEL_LOG_EXPORTER") or "").strip().lower()
        if mode in _DISABLED_MODES:
            logger.info(
                "OpenTelemetry logs disabled (OTEL_LOG_EXPORTER=%r)",
                mode or "(unset)",
            )
            return False

        if mode not in _OTLP_MODES:
            logger.warning(
                "Unknown OTEL_LOG_EXPORTER=%r, treating as disabled "
                "(supported: otlp / otlp_grpc / otlp_http)",
                mode,
            )
            return False

        try:
            # resource 复用 otel_config.build_resource(跟 span / metric 同
            # service.name / deployment.environment),让 OTel log 在
            # collector / Loki / Grafana 端跟 trace / metric 自动 join。
            if resource is None:
                from lumen_core.otel_config import build_resource

                resource = build_resource()

            # Exporter:默认 OTLP gRPC。HTTP 模式 lazy import(项目当前依赖
            # 只装了 gRPC exporter,生产可按需
            # ``opentelemetry-exporter-otlp-proto-http``)。
            if mode == "otlp_http":
                try:
                    from opentelemetry.exporter.otlp.proto.http._log_exporter import (  # type: ignore[import-not-found]
                        OTLPLogExporter,
                    )
                except ImportError:
                    logger.warning(
                        "otlp_http log exporter not installed "
                        "(pip install opentelemetry-exporter-otlp-proto-http); "
                        "falling back to OTLP gRPC :4317",
                    )
                    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                        OTLPLogExporter,
                    )
                    log_endpoint = endpoint or "http://localhost:4317"
                else:
                    log_endpoint = endpoint or "http://localhost:4318/v1/logs"
            else:
                from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                    OTLPLogExporter,
                )
                log_endpoint = endpoint or "http://localhost:4317"

            # HTTPS_PROXY 防御(同 otel.py / otel_metrics.py 套路):
            # OTLP gRPC log exporter 内部走 grpc.insecure_channel,自动读
            # HTTPS_PROXY / GRPC_PROXY env 走代理,跟 span / metric exporter
            # 同根因 —— 复用同套 warning 文案。
            if os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("GRPC_PROXY"):
                logger.warning(
                    "HTTPS_PROXY/GRPC_PROXY env detected (value=%s/%s/%s); "
                    "OTLP gRPC log exporter will route through proxy. "
                    "To bypass, set GRPC_PROXY=\"\" / HTTPS_PROXY=\"\".",
                    os.getenv("HTTPS_PROXY"),
                    os.getenv("https_proxy"),
                    os.getenv("GRPC_PROXY"),
                )

            from opentelemetry.sdk._logs import LoggerProvider
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry._logs import set_logger_provider

            exporter = OTLPLogExporter(endpoint=log_endpoint, timeout=2)
            # 日志要近实时(运维 grep trace 时希望 log 已经在 Loki),间隔 5s
            # 比 metric 15s 短。timeout 3s 留 buffer 余量。
            processor = BatchLogRecordProcessor(
                exporter,
                schedule_delay_millis=5000,
                export_timeout_millis=3000,
            )

            provider = LoggerProvider(resource=resource)
            provider.add_log_record_processor(processor)
            set_logger_provider(provider)

            _logger_provider = provider
            _processor = processor
            _initialized = True

            logger.info(
                "OpenTelemetry logs initialized: exporter=%s endpoint=%s service=%s env=%s",
                mode,
                log_endpoint,
                resource.attributes.get("service.name"),
                resource.attributes.get("deployment.environment"),
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenTelemetry logs setup failed: %s", e)
            return False


def force_flush(timeout_millis: int = 5000) -> bool:
    """强制 flush 当前 LoggerProvider 的 buffered log。

    镜像 ``lumen_core.otel.force_flush`` + ``otel_metrics.force_flush`` 语义:
    - uvicorn lifespan shutdown 调一次(timeout_millis=5000)
    - atexit 兜底再调一次(timeout_millis=3000,Day 5 同模式)
    - 失败 swallow + 返 False,不抛

    Returns:
        True if force_flush was called; False if not initialized / no-op
        provider / exception raised。
    """
    try:
        provider = _logger_provider
        if provider is not None and hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout_millis)
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("OTel logs force_flush failed: %s", e)
        return False


def reset_for_test() -> None:
    """测试间隔离:清掉 global LoggerProvider + processor。

    pytest fixture 推荐(镜像 ``test_otel_metrics.py``):
        @pytest.fixture(autouse=True)
        def _otel_logs_test_env():
            yield
            from lumen_core.otel_logs import reset_for_test
            reset_for_test()

    OTel 一次锁(metrics module 跟 trace module 同模式):直接 reset
    module-level ``_LOGGER_PROVIDER`` + ``_LOGGER_PROVIDER_SET_ONCE._done``
    来达到完全 reset 效果,只用于 pytest fixture 隔离,生产代码不会调到这里。
    """
    global _initialized, _logger_provider, _processor

    # 关 processor(让 BatchLogRecordProcessor 后台线程正常退出,避免 pytest
    # 关闭 stdout 后写 "I/O on closed file" —— 与 metric reader shutdown 同坑)。
    if _processor is not None:
        try:
            _processor.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug("BatchLogRecordProcessor shutdown failed: %s", e)

    if _logger_provider is not None:
        try:
            _logger_provider.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.debug("LoggerProvider shutdown failed: %s", e)

    _processor = None
    _logger_provider = None

    # 清 OTel logs module 一次锁 + module-level state。
    # OTel 1.36 把 module-level state 放在 ``opentelemetry._logs._internal``
    # 子模块(public ``opentelemetry._logs`` 命名空间没有这两个
    # attribute —— 但 reset 路径必须改 internal state 才能让下次
    # ``set_logger_provider`` 生效)。
    try:
        from opentelemetry._logs import _internal as _otel_logs_internal

        lp = getattr(_otel_logs_internal, "_LOGGER_PROVIDER", None)
        if lp is not None:
            _otel_logs_internal._LOGGER_PROVIDER = None  # type: ignore[attr-defined]
        once = getattr(_otel_logs_internal, "_LOGGER_PROVIDER_SET_ONCE", None)
        if once is not None and hasattr(once, "_done"):
            once._done = False  # type: ignore[attr-defined]
    except Exception as e:  # noqa: BLE001
        logger.debug("LoggerProvider module-level reset failed: %s", e)

    _initialized = False


def is_initialized() -> bool:
    """测试 / 调试用:当前进程是否已 setup_logs()。"""
    return _initialized


def get_logger_provider() -> Any:
    """测试 / debug 用:拿当前 LoggerProvider 实例(可能 None)。"""
    return _logger_provider


__all__ = [
    "setup_logs",
    "force_flush",
    "reset_for_test",
    "is_initialized",
    "get_logger_provider",
    "_OTLP_MODES",
    "_DISABLED_MODES",
]
