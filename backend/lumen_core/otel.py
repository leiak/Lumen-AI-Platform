"""Phase 1 Group B 2.4.4 (2026-09-04): OpenTelemetry SDK setup 工厂。

**为什么**:Phase 0 Unit 5 ship 的自研 ``trace_id`` 解决"同请求日志能 join",
但**不是真正的分布式追踪** — 没 span tree / 没 span attributes / 没可视化。
OTel SDK + instrumentation 直接补这 3 块。

**做什么**:
1. ``setup_tracing()`` 按 ``OTEL_EXPORTER`` env 选 exporter(console / OTLP
   gRPC / OTLP HTTP / noop),装到 global ``TracerProvider``
2. 自动 instrument httpx(下游 Ollama / OpenAI / 自家 API 自动写 span,
   parent 走 W3C ``traceparent`` 透传)
3. SQLAlchemy / Celery 自动 instrumentation 留 Day 2(跟 engine 创建顺序耦合)

**幂等性**:
- 同一进程多次调 ``setup_tracing()`` 只有第一次生效,后续直接返 False
- ``reset_for_test()`` 清掉 TracerProvider + httpx instrument,测试可以
  重新 setup 不同 exporter

**Exhaustive env vars**:
  - ``OTEL_EXPORTER``: ``console`` (dev 默认) / ``otlp`` / ``otlp_grpc`` /
    ``otlp_http`` / ``none``。空值走 console。
  - ``OTEL_ENDPOINT``: exporter URL(默认 ``http://localhost:4317`` for
    gRPC,``http://localhost:4318/v1/traces`` for HTTP)
  - ``OTEL_SERVICE_NAME``: 覆盖默认 ``lumen-backend``
  - ``OTEL_SERVICE_VERSION``: 覆盖默认 git SHA / ``0.1.0``
  - ``DEPLOYMENT_ENV``: ``dev`` / ``staging`` / ``prod``(默认 ``dev``)

**踩坑**:
- 重复 ``trace.set_tracer_provider()`` OTel SDK 会 warning;我们用
  ``_initialized`` 守门避免
- ``BatchSpanProcessor`` 在 uvicorn shutdown 时未 flush 可能丢最后几个
  span;Phase 1 Day 5 末尾加 atexit / lifespan shutdown flush
- 旧 ``lumen_services.httpx_trace`` 模块 + ``HTTPXClientInstrumentor`` 双
  写 ``X-Trace-Id`` / ``traceparent`` header;两者不冲突(不同 header 名),
  但 Day 5 计划把 ``httpx_trace`` 标 deprecated(已 ship 代码保留兼容)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)


# 模块级 state:setup_tracing 幂等守门。
_initialized: bool = False
_init_lock = threading.Lock()

DEFAULT_SERVICE_NAME = "lumen-backend"


def setup_tracing(
    service_name: Optional[str] = None,
    service_version: Optional[str] = None,
    deployment_environment: Optional[str] = None,
) -> bool:
    """Setup OpenTelemetry SDK + httpx 自动 instrumentation。

    Returns:
        True if actually initialized (TracerProvider set + instrumentor attached).
        False if disabled (OTEL_EXPORTER=none) or already initialized (idempotent)。

    Raises:
        不抛异常:任何 import / setup 失败都降级到 logger.warning + return False,
        不阻塞 uvicorn 启动(OTel 是可观测性,挂了不应挂业务)。

    Note:
        FastAPI 单独 instrument:用 ``FastAPIInstrumentor.instrument_app(app)``
        在 ``lumen_main._lifespan`` 里 app 已创建后调。本函数只 setup global
        TracerProvider + httpx(httpx 是模块级,无需 app 引用)。
    """
    global _initialized

    with _init_lock:
        if _initialized:
            logger.debug("OTel already initialized, skipping")
            return False

        exporter_mode = (os.getenv("OTEL_EXPORTER") or "console").strip().lower()
        if exporter_mode in ("none", "off", "", "noop", "disabled"):
            logger.info("OTEL_EXPORTER=%r,skipping OTel setup", exporter_mode)
            return False

        try:
            _do_setup(
                exporter_mode=exporter_mode,
                service_name=service_name,
                service_version=service_version,
                deployment_environment=deployment_environment,
            )
            _initialized = True
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenTelemetry setup failed: %s", e)
            return False


def _do_setup(
    exporter_mode: str,
    service_name: Optional[str],
    service_version: Optional[str],
    deployment_environment: Optional[str],
) -> None:
    """实际 setup 逻辑(失败抛异常,setup_tracing 包成 logger.warning)。

    拆出来是为了让 setup_tracing 主干 try/except 包一切。
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    from lumen_core.otel_config import build_resource

    resource = build_resource(
        service_name=service_name,
        service_version=service_version,
        deployment_environment=deployment_environment,
    )

    provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)

    # 选 exporter
    exporter = _build_exporter(exporter_mode)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    # 自动 instrument:httpx(出站 HTTP)+ SQLAlchemy(engine execute / ORM query)
    # + Pymysql(raw connect,覆盖 ensure_* 迁移脚本)+ Celery(task 自动起 parent
    # span + 跨进程 W3C traceparent header 注入)。
    #
    # 顺序:SQLAlchemy 必须先(pymysql 是底层 driver,先 instrument pymysql 再
    # instrument SQLAlchemy 时 SQLAlchemy 会用上 instrumented pymysql);
    # Celery 不依赖其他两个,放最后。
    #
    # idempotency:每个 Instrumentor 内部 _instrumented 守门,二次调用会
    # 抛 AlreadyInstrumentedError。我们包在 try 里吞掉,跟 logger.warning
    # 走 — 真重复 setup 是 bug,生产里不应该发生,但测试 reset 后重 setup
    # 会撞。
    _instrument_httpx()
    _instrument_pymysql()
    _instrument_sqlalchemy()
    _instrument_celery()

    logger.info(
        "OpenTelemetry initialized: exporter=%s service=%s version=%s env=%s",
        exporter_mode,
        resource.attributes.get("service.name"),
        resource.attributes.get("service.version"),
        resource.attributes.get("deployment.environment"),
    )


def _instrument_httpx() -> None:
    """httpx 出站 HTTP 自动 instrumentation(Day 1 ship)。"""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        logger.warning("HTTPXClientInstrumentor not installed; httpx spans disabled")
    except Exception as e:  # noqa: BLE001
        # AlreadyInstrumentedError 等 — 真重复 setup 是 bug,日志警告不阻塞
        logger.warning("httpx instrumentation failed: %s", e)


def _instrument_pymysql() -> None:
    """pymysql raw connect 自动 instrumentation(Day 2)。

    主要覆盖路径:lumen_core.database 里 ``ensure_*`` 迁移脚本 + 任何
    直连 MySQL 的管理脚本(pymysql.connect())。SQLAlchemy ORM 路径走
    SQLAlchemyInstrumentor,不重复。

    pymysql 是 SQLAlchemy 默认 driver 之一,pymysql.instrument 必须在
    SQLAlchemy 之前调,否则 SQLAlchemy 拿到的 connection 是 uninstrumented
    DBAPI,SQL span 关联不到 raw query span。
    """
    try:
        from opentelemetry.instrumentation.pymysql import PyMySQLInstrumentor

        PyMySQLInstrumentor().instrument()
    except ImportError:
        logger.warning("PyMySQLInstrumentor not installed; raw pymysql spans disabled")
    except Exception as e:  # noqa: BLE001
        logger.warning("pymysql instrumentation failed: %s", e)


def _instrument_sqlalchemy() -> None:
    """SQLAlchemy engine 自动 instrumentation(Day 2)。

    关键决策:用 ``instrument(engine=engine)`` 而非全局 ``instrument()``。
    全局会试图 patch 所有 engine,但项目只有 1 个 engine(create_engine
    在 lumen_core.database.py:6 模块级);用 ``engine=`` 显式传避免误伤
    任何未来 import 进来的其他 engine(比如测试 fixture)。

    engine import 在这里(lazy),setup_tracing() 主干 try/except 包一切,
    MySQL down 时 create_engine 仍然能成功(create_engine 是 lazy,
    真正连接是第一次 query 时),所以 SQLAlchemy instrumentation 不会阻塞
    uvicorn 启动。
    """
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from lumen_core.database import engine

        SQLAlchemyInstrumentor().instrument(engine=engine)
    except ImportError:
        logger.warning(
            "SQLAlchemyInstrumentor not installed; SQLAlchemy spans disabled",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("sqlalchemy instrumentation failed: %s", e)


def _instrument_celery() -> None:
    """Celery task 自动 instrumentation(Day 2)。

    自动为每个 task 创建 parent span + 跨进程 W3C traceparent header 注入。
    自研 ``lumen_tasks.trace_signals`` 保留 X-Trace-Id header 路径作为
    fallback(老客户端不识别 traceparent 时还能 join)。

    CeleryInstrumentor.instrument() 是 module-level patch(改 Celery class),
    无需先 import celery_app — uvicorn 进程调 setup_tracing() 时如果
    celery_app 没 import,CeleryInstrumentor 仍能 instrument 后续任何
    Celery() 实例化。这是 Day 2 的关键设计:Celery instrument 不依赖
    celery_app 加载顺序。
    """
    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
    except ImportError:
        logger.warning("CeleryInstrumentor not installed; celery task spans disabled")
    except Exception as e:  # noqa: BLE001
        logger.warning("celery instrumentation failed: %s", e)


def _build_exporter(exporter_mode: str):
    """按 exporter_mode 返对应 SpanExporter 实例。

    失败抛异常(_do_setup catch 后转 logger.warning)。
    """
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    if exporter_mode == "console":
        return ConsoleSpanExporter()

    if exporter_mode in ("otlp", "otlp_grpc"):
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        endpoint = (
            os.getenv("OTEL_ENDPOINT")
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            or "http://localhost:4317"
        )
        return OTLPSpanExporter(endpoint=endpoint, timeout=2)

    if exporter_mode == "otlp_http":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found,no-redef]
            OTLPSpanExporter as HTTPOTLPSpanExporter,
        )

        endpoint = (
            os.getenv("OTEL_ENDPOINT")
            or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
            or "http://localhost:4318/v1/traces"
        )
        return HTTPOTLPSpanExporter(endpoint=endpoint, timeout=2)

    # 未知值兜底走 console + warning
    logger.warning("Unknown OTEL_EXPORTER=%r,falling back to console", exporter_mode)
    return ConsoleSpanExporter()


def is_initialized() -> bool:
    """当前进程是否已 setup_tracing()(测试 / 重启场景用)。"""
    return _initialized


def reset_for_test() -> None:
    """测试间隔离:清掉 global TracerProvider + httpx instrument。

    pytest fixture 推荐写法:
        @pytest.fixture(autouse=True)
        def _reset_otel():
            yield
            from lumen_core.otel import reset_for_test
            reset_for_test()

    Note: 不能 reset FastAPIInstrumentor(单例绑 app,跨测试同一 app —
    让 test 自己用 lifespan="off" TestClient 即可)。

    OTel 一次锁:`trace.set_tracer_provider()` 内部用 ``_once.Once`` 守门,
    第二次调用会被 warn + 忽略。我们直接 reset 模块级 ``_TRACER_PROVIDER``
    + ``_TRACER_PROVIDER_SET_ONCE._done`` 来达到完全 reset 效果,只用于
    pytest fixture 隔离,生产代码不会调到这里。
    """
    global _initialized
    with _init_lock:
        if not _initialized:
            # 即使 _initialized=False(可能 conftest 触发的 lumen_main import
            # 把它设过 True 后又被外部 reset 过),也要清掉 trace module 的
            # module-level 状态,避免下一次 setup_tracing 被 _once 拒。
            try:
                from opentelemetry import trace

                if getattr(trace, "_TRACER_PROVIDER", None) is not None:
                    trace._TRACER_PROVIDER = None
                once = getattr(trace, "_TRACER_PROVIDER_SET_ONCE", None)
                if once is not None and hasattr(once, "_done"):
                    once._done = False
            except Exception as e:  # noqa: BLE001
                logger.debug("TracerProvider module-level reset failed: %s", e)
            return

        try:
            from opentelemetry import trace

            # 直接清 module-level state(比 set_tracer_provider() 更彻底 —
            # OTel 一次锁会拒后续 set,所以走私有 attribute reset)。
            trace._TRACER_PROVIDER = None
            once = getattr(trace, "_TRACER_PROVIDER_SET_ONCE", None)
            if once is not None and hasattr(once, "_done"):
                once._done = False
        except Exception as e:  # noqa: BLE001
            logger.debug("TracerProvider reset failed: %s", e)

        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

            HTTPXClientInstrumentor().uninstrument()
        except Exception as e:  # noqa: BLE001
            logger.debug("HTTPXClientInstrumentor uninstrument failed: %s", e)

        _initialized = False


__all__ = [
    "setup_tracing",
    "is_initialized",
    "reset_for_test",
    "DEFAULT_SERVICE_NAME",
]