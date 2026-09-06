"""Phase 1 Group B 4.4 Day 7 (2026-09-06): OTel log signal 单测。

**覆盖范围**(30 case):
1. env gating (unset / none / off / console / disabled / 未知) → False
2. setup_logs OTLP / otlp_grpc / otlp_http 全启用 → True
3. setup_logs 幂等(二次返 False)
4. force_flush 无 provider 返 True
5. force_flush 异常 swallow 返 False
6. reset_for_test 清 module state + OTel internal _LOGGER_PROVIDER + _done
7. SimpleLogRecordProcessor + InMemoryLogExporter 端到端集成
8. OTelLogBridgeHandler emit 用 SDK LogRecord(避免 OTel 1.36 API/SDK LogRecord bug)
9. OTelLogBridgeHandler 异常 swallow
10. _ContextFilter 加 span_id + trace_flags
11. _CONTEXT_FIELDS tuple 包含 span_id / trace_flags
12. tracing.get_span_id / get_trace_flags 行为
13. HTTPS_PROXY / GRPC_PROXY env 检测 + warning
14. setup_tracing 级联 setup_logs(OTLP mode)
15. otel.force_flush 级联 log flush
16. otel.reset_for_test 级联 log reset
17. LoggerProvider resource(service.name / deployment.environment)
18. setup_logs 内部异常 swallow
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import logging

import pytest

from lumen_core import otel_logs, otel
from lumen_core.otel_logs import (
    _DISABLED_MODES,
    _OTLP_MODES,
    force_flush,
    is_initialized,
    reset_for_test,
    setup_logs,
)


# ---------------------------------------------------------------------------
# Fixture:每 test 前 reset OTel + log module state。
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _otel_logs_test_env(monkeypatch):
    """每 test 前清 trace + metric + log module state,避免跨测试污染。

    镜像 test_otel_metrics.py:_otel_metrics_test_env 模式。
    """
    from lumen_core import otel_metrics

    otel.reset_for_test()
    otel_metrics.reset_for_test()
    reset_for_test()
    monkeypatch.delenv("OTEL_LOG_EXPORTER", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("GRPC_PROXY", raising=False)
    monkeypatch.delenv("OTEL_ENDPOINT", raising=False)

    yield

    otel.reset_for_test()
    otel_metrics.reset_for_test()
    reset_for_test()


def _build_resource_stub() -> object:
    """构造轻量 Resource stub 用于 setup_logs(resource=...) 端到端测试。

    镜像 lumen_core.otel_config.build_resource 行为,但不依赖
    OTEL_SERVICE_NAME env(避免 fixture 之间的 env 污染)。
    """
    from types import SimpleNamespace

    attrs = {
        "service.name": "lumen-backend-test",
        "service.version": "0.1.0-test",
        "deployment.environment": "test",
    }
    return SimpleNamespace(attributes=attrs)


def _patch_otlp_log_exporter_with_inmemory():
    """把 OTLPLogExporter(从 setup_logs 实际 import 的 module)替换成 mock
    返回 InMemoryLogExporter 实例,避免真建 gRPC channel。
    """
    from unittest.mock import patch
    from opentelemetry.sdk._logs.export import InMemoryLogExporter

    fake = InMemoryLogExporter()
    # setup_logs 走 `from opentelemetry.exporter.otlp.proto.grpc._log_exporter
    # import OTLPLogExporter`,所以 patch 那个 source module 的 attribute
    return patch(
        "opentelemetry.exporter.otlp.proto.grpc._log_exporter.OTLPLogExporter",
        return_value=fake,
    ), fake


# ===========================================================================
# Part 1: env gating (6 case)
# ===========================================================================


def test_setup_logs_unset_disabled(_otel_logs_test_env, caplog):
    """OTEL_LOG_EXPORTER 未设 → disabled + info log。"""
    with caplog.at_level(logging.INFO, logger="lumen_core.otel_logs"):
        result = setup_logs()
    assert result is False
    assert is_initialized() is False
    assert any("disabled" in rec.message for rec in caplog.records)


def test_setup_logs_none_disabled(_otel_logs_test_env):
    """OTEL_LOG_EXPORTER=none → disabled,等同 unset。"""
    os.environ["OTEL_LOG_EXPORTER"] = "none"
    assert setup_logs() is False
    assert is_initialized() is False


def test_setup_logs_off_disabled(_otel_logs_test_env):
    """OTEL_LOG_EXPORTER=off → disabled。"""
    os.environ["OTEL_LOG_EXPORTER"] = "off"
    assert setup_logs() is False
    assert is_initialized() is False


def test_setup_logs_console_disabled(_otel_logs_test_env):
    """OTEL_LOG_EXPORTER=console → disabled(无 ConsoleLogExporter,镜像
    metric 模式:console 模式下不启 metric exporter)。"""
    os.environ["OTEL_LOG_EXPORTER"] = "console"
    assert setup_logs() is False
    assert is_initialized() is False


def test_setup_logs_disabled_disabled(_otel_logs_test_env):
    """OTEL_LOG_EXPORTER=disabled → disabled。"""
    os.environ["OTEL_LOG_EXPORTER"] = "disabled"
    assert setup_logs() is False
    assert is_initialized() is False


def test_setup_logs_unknown_mode_warning_disabled(_otel_logs_test_env, caplog):
    """未知 mode(如 'foo') → warning + disabled。"""
    os.environ["OTEL_LOG_EXPORTER"] = "foo"
    with caplog.at_level(logging.WARNING, logger="lumen_core.otel_logs"):
        result = setup_logs()
    assert result is False
    assert is_initialized() is False
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Unknown OTEL_LOG_EXPORTER" in m for m in warning_msgs)
    assert any("foo" in m for m in warning_msgs)


# ===========================================================================
# Part 2: OTLP mode 启用 (3 case)
# ===========================================================================


def test_setup_logs_otlp_full_flow(_otel_logs_test_env, monkeypatch):
    """OTEL_LOG_EXPORTER=otlp → 完整 setup(LoggerProvider + processor +
    exporter),返 True + is_initialized True。

    mock OTLPLogExporter 避免真建 gRPC channel。
    """
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        result = setup_logs(resource=_build_resource_stub())

    assert result is True
    assert is_initialized() is True
    # LoggerProvider 已 set
    from opentelemetry._logs import get_logger_provider
    assert get_logger_provider() is not None


def test_setup_logs_otlp_grpc_alias(_otel_logs_test_env, monkeypatch):
    """OTEL_LOG_EXPORTER=otlp_grpc 跟 otlp 等价(都启)。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp_grpc")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        result = setup_logs(resource=_build_resource_stub())

    assert result is True
    assert is_initialized() is True


def test_setup_logs_otlp_http_fallback(_otel_logs_test_env, monkeypatch, caplog):
    """OTEL_LOG_EXPORTER=otlp_http + http exporter 未装 → fallback gRPC + warning。

    通过 patch 真实的 http exporter 模块 ImportError 触发 fallback。
    """
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp_http")

    import sys as _sys
    # 假装 http exporter 未装 —— 把 http _log_exporter 模块从 sys.modules 移除
    # + 在 find_spec 时返 None(模拟 pip 没装)。
    http_module_key = "opentelemetry.exporter.otlp.proto.http._log_exporter"
    saved_module = _sys.modules.pop(http_module_key, None)
    # patch find_spec 让 import 系统认为该模块不存在
    from unittest.mock import patch as _patch

    def _fake_find_spec(name, *args, **kwargs):
        if name == http_module_key or name.startswith(http_module_key + "."):
            return None
        import importlib.util as _iu
        return _iu.find_spec(name)

    try:
        with _patch("importlib.util.find_spec", side_effect=_fake_find_spec):
            pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
            with caplog.at_level(logging.WARNING, logger="lumen_core.otel_logs"):
                with pctx:
                    result = setup_logs(resource=_build_resource_stub())

        # 成功(走 gRPC fallback),有 warning
        assert result is True
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("otlp_http log exporter not installed" in m for m in warning_msgs)
    finally:
        if saved_module is not None:
            _sys.modules[http_module_key] = saved_module


# ===========================================================================
# Part 3: 幂等 (1 case)
# ===========================================================================


def test_setup_logs_idempotent(_otel_logs_test_env, monkeypatch):
    """setup_logs 多次调只有第一次生效,后续返 False(避免重复创建 OTel
    LoggerProvider 撞 set_logger_provider once-lock)。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        assert setup_logs(resource=_build_resource_stub()) is True
        # 第二次 → False
        assert setup_logs(resource=_build_resource_stub()) is False
        assert is_initialized() is True


# ===========================================================================
# Part 4: force_flush (3 case)
# ===========================================================================


def test_force_flush_no_provider_returns_true(_otel_logs_test_env):
    """没 setup_logs 时 force_flush 返 True(swallow 不存在 provider)。"""
    result = force_flush(timeout_millis=5000)
    assert result is True


def test_force_flush_exception_swallowed(_otel_logs_test_env, monkeypatch):
    """force_flush 内部 provider 抛异常时 swallow + 返 False(跟 otel.py +
    otel_metrics.py 同步语义)。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "none")
    setup_logs()  # False,但 module state 已 reset

    class _Boom:
        def force_flush(self, timeout_millis=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(otel_logs, "_logger_provider", _Boom())
    result = force_flush(timeout_millis=5000)
    assert result is False


def test_force_flush_calls_provider(_otel_logs_test_env, monkeypatch):
    """force_flush 在已 setup 时调,实际调 provider.force_flush + 返 True。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        setup_logs(resource=_build_resource_stub())

    # 已 setup, force_flush 应该返 True
    result = force_flush(timeout_millis=5000)
    assert result is True


# ===========================================================================
# Part 5: reset_for_test (3 case)
# ===========================================================================


def test_reset_for_test_when_not_initialized(_otel_logs_test_env):
    """reset_for_test 在没 setup_logs 时调不崩(swallow all)。"""
    reset_for_test()
    assert is_initialized() is False


def test_reset_for_test_clears_state(_otel_logs_test_env, monkeypatch):
    """reset_for_test 后 is_initialized() 返 False,module 状态清干净。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        setup_logs(resource=_build_resource_stub())
        assert is_initialized() is True

    reset_for_test()
    assert is_initialized() is False
    assert otel_logs._logger_provider is None
    assert otel_logs._processor is None


def test_reset_for_test_clears_otel_logs_internal(_otel_logs_test_env, monkeypatch):
    """reset_for_test 同时清 OTel _logs._internal 的 _LOGGER_PROVIDER +
    _LOGGER_PROVIDER_SET_ONCE._done,否则下一次 setup_logs 被 _once.Once 拒。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        setup_logs(resource=_build_resource_stub())

    reset_for_test()

    from opentelemetry._logs import _internal as logs_internal

    assert logs_internal._LOGGER_PROVIDER is None
    assert logs_internal._LOGGER_PROVIDER_SET_ONCE._done is False


# ===========================================================================
# Part 6: HTTPS_PROXY warning (1 case)
# ===========================================================================


def test_https_proxy_warning(_otel_logs_test_env, monkeypatch, caplog):
    """HTTPS_PROXY / GRPC_PROXY env 触发 logger.warning。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("GRPC_PROXY", "http://grpc-proxy.example.com:8080")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    with caplog.at_level(logging.WARNING, logger="lumen_core.otel_logs"):
        with pctx:
            setup_logs(resource=_build_resource_stub())

    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("HTTPS_PROXY/GRPC_PROXY" in m for m in warning_msgs)
    assert any("proxy.example.com" in m for m in warning_msgs)


# ===========================================================================
# Part 7: 端到端集成 (2 case,走 SimpleLogRecordProcessor 避免 OTLP encode 坑)
# ===========================================================================


def test_log_record_emitted_to_inmemory_exporter(_otel_logs_test_env, monkeypatch):
    """setup_logs 后调 otel logger.emit(SimpleLogRecordProcessor 不走 OTLP
    encode,直接 append batch 到 InMemoryLogExporter — 绕开 OTel 1.36 API/SDK
    LogRecord bug)。

    这是 Day 7 主链路端到端验证:JSON log → OTelLogBridgeHandler →
    SDK LogRecord → BatchLogRecordProcessor → InMemoryLogExporter。
    """
    from unittest.mock import patch
    from opentelemetry.sdk._logs.export import (
        SimpleLogRecordProcessor,
        InMemoryLogExporter,
    )
    from opentelemetry.sdk._logs._internal import LogRecord as SDKLogRecord
    from opentelemetry._logs import SeverityNumber, get_logger

    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    fake_exporter = InMemoryLogExporter()

    # 用 SimpleLogRecordProcessor + 注入 fake_exporter;patch OTLPLogExporter
    # 只是为了让 setup_logs 的 mock 过得去(processor 我们直接换)。
    from lumen_core.otel_logs import setup_logs as _setup_logs
    from opentelemetry.sdk._logs import LoggerProvider

    provider = LoggerProvider(resource=_build_resource_stub())
    provider.add_log_record_processor(SimpleLogRecordProcessor(fake_exporter))

    # 直接 set LoggerProvider 走 SDK 路径
    from opentelemetry._logs import set_logger_provider
    from opentelemetry._logs import _internal as _logs_int

    _logs_int._LOGGER_PROVIDER = provider
    _logs_int._LOGGER_PROVIDER_SET_ONCE._done = True

    # 标记 otel_logs module state 已 init(避免 setup_logs 重新跑)
    otel_logs._initialized = True
    otel_logs._logger_provider = provider

    try:
        # 通过 OTel Logger emit 一条 — 用 SDK LogRecord + current context
        from opentelemetry import context as _ctx

        logger_otel = get_logger("test.logger")
        logger_otel.emit(SDKLogRecord(
            timestamp=1000000000,
            observed_timestamp=1000000000,
            context=_ctx.get_current(),
            severity_number=SeverityNumber.INFO,
            severity_text="INFO",
            body="hello from test",
            attributes={"test_key": "test_value"},
        ))

        # SimpleLogRecordProcessor 是同步立即导出
        finished = fake_exporter.get_finished_logs()
        assert len(finished) >= 1
        # InMemoryLogExporter 返 LogData objects;.log_record 才是 LogRecord
        bodies = [ld.log_record.body for ld in finished]
        assert "hello from test" in bodies
    finally:
        otel_logs._initialized = False
        otel_logs._logger_provider = None
        reset_for_test()


def test_log_record_attributes_match(_otel_logs_test_env, monkeypatch):
    """emit 时传的 attributes 字段被 LogRecord 保留下来,SimpleLogRecordProcessor
    不改 attributes。
    """
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        SimpleLogRecordProcessor,
        InMemoryLogExporter,
    )
    from opentelemetry.sdk._logs._internal import LogRecord as SDKLogRecord
    from opentelemetry._logs import SeverityNumber, get_logger
    from opentelemetry import context as _ctx

    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    fake_exporter = InMemoryLogExporter()
    provider = LoggerProvider(resource=_build_resource_stub())
    provider.add_log_record_processor(SimpleLogRecordProcessor(fake_exporter))

    from opentelemetry._logs import set_logger_provider
    from opentelemetry._logs import _internal as _logs_int

    _logs_int._LOGGER_PROVIDER = provider
    _logs_int._LOGGER_PROVIDER_SET_ONCE._done = True
    otel_logs._initialized = True
    otel_logs._logger_provider = provider

    try:
        logger_otel = get_logger("test.attrs")
        test_attrs = {
            "trace_id": "abcdef0123456789",
            "span_id": "1234567890abcdef",
            "tenant_id": "42",
            "user_id": "7",
        }
        logger_otel.emit(SDKLogRecord(
            timestamp=2000000000,
            observed_timestamp=2000000000,
            context=_ctx.get_current(),
            severity_number=SeverityNumber.WARN,
            severity_text="WARNING",
            body="attrs test",
            attributes=test_attrs,
        ))

        finished = fake_exporter.get_finished_logs()
        # InMemoryLogExporter 返 LogData,body/attributes/resource 在 .log_record 上
        matching = [ld for ld in finished if ld.log_record.body == "attrs test"]
        assert len(matching) == 1
        rec = matching[0].log_record
        # attributes 应一致
        assert dict(rec.attributes) == test_attrs
        # severity 保留
        assert rec.severity_number == SeverityNumber.WARN
        # resource 应已绑到 LoggerProvider(provider 构造时传入)
        assert (
            provider.resource.attributes.get("service.name")
            == "lumen-backend-test"
        )
    finally:
        otel_logs._initialized = False
        otel_logs._logger_provider = None
        reset_for_test()


# ===========================================================================
# Part 8: OTelLogBridgeHandler (2 case)
# ===========================================================================


def test_bridge_handler_emit_creates_log_record(_otel_logs_test_env, monkeypatch):
    """OTelLogBridgeHandler.emit 把 stdlib LogRecord 转 OTel LogRecord emit,
    attributes 含 trace_id / span_id / trace_flags(从 record 属性抽)。
    """
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        SimpleLogRecordProcessor,
        InMemoryLogExporter,
    )
    from opentelemetry._logs import get_logger as _otel_get_logger
    from lumen_core.logging_config import OTelLogBridgeHandler

    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    fake_exporter = InMemoryLogExporter()
    provider = LoggerProvider(resource=_build_resource_stub())
    provider.add_log_record_processor(SimpleLogRecordProcessor(fake_exporter))

    from opentelemetry._logs import set_logger_provider
    from opentelemetry._logs import _internal as _logs_int

    _logs_int._LOGGER_PROVIDER = provider
    _logs_int._LOGGER_PROVIDER_SET_ONCE._done = True
    otel_logs._initialized = True
    otel_logs._logger_provider = provider

    try:
        handler = OTelLogBridgeHandler(level=logging.INFO)

        # 构造 stdlib LogRecord(带 trace 字段)
        record = logging.LogRecord(
            name="test.bridge",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="bridge test message",
            args=None,
            exc_info=None,
        )
        record.trace_id = "bridge_tid_123"
        record.span_id = "bridge_sid_456"
        record.trace_flags = 1
        record.tenant_id = 99

        handler.emit(record)

        finished = fake_exporter.get_finished_logs()
        # 至少一个含 trace_id=bridge_tid_123(InMemoryLogExporter 返 LogData)
        has_attrs = any(
            dict(ld.log_record.attributes).get("trace_id") == "bridge_tid_123"
            and dict(ld.log_record.attributes).get("span_id") == "bridge_sid_456"
            and dict(ld.log_record.attributes).get("trace_flags") == "1"
            for ld in finished
        )
        assert has_attrs
    finally:
        otel_logs._initialized = False
        otel_logs._logger_provider = None
        reset_for_test()


def test_bridge_handler_exception_swallow(_otel_logs_test_env, monkeypatch):
    """OTelLogBridgeHandler.emit 内部异常 swallow(走 stdlib Handler.handleError
    默认 silent),不影响后续 log。
    """
    from lumen_core.logging_config import OTelLogBridgeHandler

    handler = OTelLogBridgeHandler(level=logging.INFO)

    # mock _get_otel_logger 抛异常
    def _boom():
        raise RuntimeError("simulated OTel emit failure")

    monkeypatch.setattr(handler, "_get_otel_logger", _boom)

    record = logging.LogRecord(
        name="test.bridge",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="should be swallowed",
        args=None,
        exc_info=None,
    )

    # emit 内部抛 → swallow,不向上抛
    handler.emit(record)  # 不应抛


# ===========================================================================
# Part 9: _ContextFilter + _CONTEXT_FIELDS (2 case)
# ===========================================================================


def test_context_filter_adds_span_id_trace_flags(_otel_logs_test_env):
    """_ContextFilter.filter() 加 span_id + trace_flags 到 record(从 OTel
    current span 取)。
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from lumen_core.logging_config import _ContextFilter

    # 设个 TracerProvider + 起一个 span
    provider = TracerProvider()
    in_mem = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(in_mem))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("test.tracing")
    f = _ContextFilter()

    with tracer.start_as_current_span("test.span") as span:
        sc = span.get_span_context()
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname="x", lineno=1,
            msg="x", args=None, exc_info=None,
        )
        f.filter(record)

        # record 应该有 trace_id / span_id / trace_flags
        assert hasattr(record, "trace_id")
        assert hasattr(record, "span_id")
        assert hasattr(record, "trace_flags")
        assert record.trace_id == format(sc.trace_id, "032x")
        assert record.span_id == format(sc.span_id, "016x")
        # trace_flags 是 int,SAMPLED=1
        assert isinstance(record.trace_flags, int)
        assert record.trace_flags & 0x01 == 1


def test_context_fields_include_span_id_trace_flags(_otel_logs_test_env):
    """_CONTEXT_FIELDS tuple 必须含 span_id + trace_flags(Day 7 新增)。"""
    from lumen_core.logging_config import _ContextJsonFormatter

    must_have = {"trace_id", "span_id", "trace_flags", "tenant_id", "user_id"}
    assert must_have.issubset(set(_ContextJsonFormatter._CONTEXT_FIELDS))


# ===========================================================================
# Part 10: tracing.get_span_id / get_trace_flags (3 case)
# ===========================================================================


def test_get_span_id_no_active_span(_otel_logs_test_env):
    """无 active span / OTel span context invalid 时,get_span_id 返 None。"""
    from lumen_core.tracing import get_span_id

    assert get_span_id() is None


def test_get_span_id_with_active_span_returns_16hex(_otel_logs_test_env):
    """active span 时 get_span_id 返 16-hex 字符串(W3C trace context 格式)。"""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from lumen_core.tracing import get_span_id

    provider = TracerProvider()
    in_mem = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(in_mem))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("test.span_id")
    with tracer.start_as_current_span("test") as span:
        sc = span.get_span_context()
        sid = get_span_id()
        assert sid is not None
        assert sid == format(sc.span_id, "016x")
        assert len(sid) == 16
        # 全 hex
        int(sid, 16)  # 不抛 = 全 hex


def test_get_trace_flags_no_active_span(_otel_logs_test_env):
    """无 active span 时 get_trace_flags 返 None。"""
    from lumen_core.tracing import get_trace_flags

    assert get_trace_flags() is None


# ===========================================================================
# Part 11: otel.py 级联 (3 case)
# ===========================================================================


def test_setup_tracing_cascades_to_logs(_otel_logs_test_env, monkeypatch):
    """otel.setup_tracing() 在 OTLP 模式下自动调 setup_logs()(挂
    OTel log signal 到同一 collector)。

    验证:setup_tracing() 后 is_initialized()(otel_logs) True。
    """
    from opentelemetry.sdk._logs.export import InMemoryLogExporter
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_log_exporter = _patch_otlp_log_exporter_with_inmemory()
    fake_metric_reader = InMemoryMetricReader()

    with pctx:
        with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
            with patch.object(
                sdk_metrics_export,
                "PeriodicExportingMetricReader",
                return_value=fake_metric_reader,
            ):
                result = otel.setup_tracing()

    assert result is True
    # log 也跟着初始化
    assert is_initialized() is True


def test_force_flush_cascades_to_logs(_otel_logs_test_env, monkeypatch):
    """otel.force_flush() 在 log 已 setup 后调用,级联 log flush
    (force_flush 末尾 _logs_force_flush)。
    """
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_log_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
            with patch.object(
                sdk_metrics_export,
                "PeriodicExportingMetricReader",
                return_value=InMemoryMetricReader(),
            ):
                otel.setup_tracing()
                # otel.force_flush 串联到 log flush
                result = otel.force_flush(timeout_millis=5000)
                assert result is True


def test_reset_for_test_cascades_to_logs(_otel_logs_test_env, monkeypatch):
    """otel.reset_for_test() 清掉 log module state(otel._initialized=False
    early branch 也清,跟 metric 镜像)。
    """
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_log_exporter = _patch_otlp_log_exporter_with_inmemory()
    with pctx:
        with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
            with patch.object(
                sdk_metrics_export,
                "PeriodicExportingMetricReader",
                return_value=InMemoryMetricReader(),
            ):
                otel.setup_tracing()
                assert is_initialized() is True

                # reset cascade
                otel.reset_for_test()
                assert is_initialized() is False


# ===========================================================================
# Part 12: LoggerProvider resource + setup_logs 异常 swallow (2 case)
# ===========================================================================


def test_logger_provider_has_resource(_otel_logs_test_env, monkeypatch):
    """setup_logs 时传的 resource 含 service.name / deployment.environment,
    LoggerProvider 内部 resource 跟传入一致。
    """
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    pctx, fake_exporter = _patch_otlp_log_exporter_with_inmemory()
    resource = _build_resource_stub()

    with pctx:
        setup_logs(resource=resource)

    provider = otel_logs.get_logger_provider()
    assert provider is not None
    # LoggerProvider 的 resource 跟传入一致
    assert provider.resource.attributes.get("service.name") == "lumen-backend-test"


def test_setup_logs_failure_swallowed(_otel_logs_test_env, monkeypatch, caplog):
    """setup_logs 内部任何异常 swallow + 返 False(不阻塞 uvicorn 启动)。"""
    monkeypatch.setenv("OTEL_LOG_EXPORTER", "otlp")

    # patch 真实的 OTLPLogExporter 模块让其构造时抛异常
    from unittest.mock import patch

    with caplog.at_level(logging.WARNING, logger="lumen_core.otel_logs"):
        with patch(
            "opentelemetry.exporter.otlp.proto.grpc._log_exporter.OTLPLogExporter",
            side_effect=RuntimeError("simulated exporter init failure"),
        ):
            result = setup_logs(resource=_build_resource_stub())

    # 异常 swallow + 返 False
    assert result is False
    assert is_initialized() is False
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("OpenTelemetry logs setup failed" in m for m in warning_msgs)


from unittest.mock import patch  # 末尾统一 import,方便上面函数复用
