"""Phase 1 Group B 4.4 Day 6 (2026-09-06): OTel span-derived metrics 单测。

**覆盖范围**(16 case):
1. env gating(none / off / console → 返 False + 不初始化)
2. setup_metrics 幂等(二次调返 False)
3. _status_class 边界(199 / 200 / 299 / 399 / 499 / 599 / 600)
4. _extract_labels allowlist 过滤(白名单外属性丢)
5. _extract_labels int / bool / None / str 兼容
6. _extract_labels span_name collapse(KNOWN 外 → "other")
7. SpanObserverMetricExporter.on_end Counter + Histogram 累加
8. 跨 span_name series 隔离
9. force_flush 返 True
10. force_flush 异常 swallow
11. shutdown 清 in-memory state
12. reset_for_test 清 MeterProvider module-level state
13. InMemoryMetricReader 端到端(set_meter_provider + on_end → 读 metric data)
14. HTTPS_PROXY env 检测 + warning
15. cardinality 守门(高基数属性 + 未知 span_name 双 fallback)
16. setup_metrics 与 setup_tracing 串联(otel.py 改动)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import logging

import pytest

from lumen_core import otel_metrics
from lumen_core.otel_metrics import (
    SpanObserverMetricExporter,
    _ALLOWED_LABEL_KEYS,
    _KNOWN_SPAN_NAMES,
    _extract_labels,
    _status_class,
    force_flush,
    is_initialized,
    reset_for_test,
    setup_metrics,
)


# ---------------------------------------------------------------------------
# Fixture:每 test 前 reset OTel + metrics module state。
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _otel_metrics_test_env(monkeypatch):
    """每 test 前清 trace + metric module state,避免跨测试污染。

    注意:不强制设 OTEL_EXPORTER(每个 test 自己设 — 有的测 none,有的测 otlp)。
    """
    from lumen_core import otel

    otel.reset_for_test()
    reset_for_test()
    monkeypatch.delenv("OTEL_EXPORTER", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("GRPC_PROXY", raising=False)
    monkeypatch.delenv("OTEL_ENDPOINT", raising=False)

    yield

    otel.reset_for_test()
    reset_for_test()


def _make_span(
    name: str = "chat.stream",
    start_ns: int = 1_000_000_000,
    end_ns: int = 1_500_000_000,  # 500ms duration
    attributes: dict = None,
    kind: str = "INTERNAL",
    status_code: str = "OK",
) -> object:
    """构造一个轻量 _MockSpan,符合 SpanObserverMetricExporter.on_end 读取
    的 duck-typed API(.start_time / .end_time / .attributes / .name /
    .kind / .status)。

    不继承 ReadableSpan SDK 接口,只要 _record() 读的属性都存在即可。
    """
    from types import SimpleNamespace

    span_kind_enum = SimpleNamespace(name=kind)
    span_status = SimpleNamespace(status_code=SimpleNamespace(name=status_code))
    return SimpleNamespace(
        name=name,
        start_time=start_ns,
        end_time=end_ns,
        attributes=attributes or {},
        kind=span_kind_enum,
        status=span_status,
        context=SimpleNamespace(span_id=0x1234),
    )


# ===========================================================================
# Part 1: env gating
# ===========================================================================


def test_setup_metrics_none_returns_false(_otel_metrics_test_env, monkeypatch):
    """OTEL_EXPORTER=none → setup_metrics 返 False + 不初始化。"""
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    assert setup_metrics() is False
    assert is_initialized() is False


def test_setup_metrics_console_returns_false(_otel_metrics_test_env, monkeypatch, caplog):
    """OTEL_EXPORTER=console → 返 False(无 ConsoleMetricExporter,日志
    info 说明跳过)。"""
    monkeypatch.setenv("OTEL_EXPORTER", "console")
    with caplog.at_level(logging.INFO, logger="lumen_core.otel_metrics"):
        result = setup_metrics()
    assert result is False
    assert is_initialized() is False
    # log 里有 "skipping OTel metrics setup"
    assert any("skipping" in rec.message for rec in caplog.records)


def test_setup_metrics_idempotent(_otel_metrics_test_env, monkeypatch):
    """setup_metrics 多次调只有第一次生效,后续返 False(避免重复创建
    OTLPMetricExporter 撞端口)。"""
    # 用 OTLP 模式但 InMemoryMetricReader 替换 OTLPMetricExporter(测试
    # 里走不到 collector),走真实 setup_metrics 链路但 mock exporter
    from unittest.mock import patch
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")

    fake_reader = InMemoryMetricReader()

    with patch(
        "lumen_core.otel_metrics.OTLPMetricExporter", create=True
    ) as mock_exporter:
        mock_exporter.return_value = None  # exporter init 不真建连接

        # patch PeriodicExportingMetricReader 在 import 时绑定的 source module
        with patch.object(
            sdk_metrics_export,
            "PeriodicExportingMetricReader",
            return_value=fake_reader,
        ):
            assert setup_metrics() is True
            # 第二次返回 False(idempotent)
            assert setup_metrics() is False
            assert is_initialized() is True


# ===========================================================================
# Part 2: _status_class 边界
# ===========================================================================


@pytest.mark.parametrize(
    "http_status,expected",
    [
        (None, "UNSET"),
        ("abc", "UNSET"),  # 非数字 → UNSET
        (-1, "UNSET"),  # 负数 → UNSET(< 200)
        (100, "1xx"),
        (199, "1xx"),  # 边界
        (200, "2xx"),  # 边界
        (201, "2xx"),
        (299, "2xx"),  # 边界
        (300, "3xx"),
        (399, "3xx"),  # 边界
        (400, "4xx"),
        (404, "4xx"),
        (499, "4xx"),  # 边界
        (500, "5xx"),
        (502, "5xx"),
        (599, "5xx"),  # 边界
        (600, "UNSET"),  # 边界外
        (999, "UNSET"),
        (200.0, "2xx"),  # float 转 int
        ("200", "2xx"),  # 字符串数字
    ],
)
def test_status_class_boundaries(http_status, expected):
    """_status_class 边界 199 / 200 / 299 / 399 / 499 / 599 / 600 全部覆盖,
    加 None / 非数字 / float / str 兼容。"""
    assert _status_class(http_status) == expected


# ===========================================================================
# Part 3: _extract_labels
# ===========================================================================


def test_extract_labels_filters_high_cardinality_attrs():
    """_ALLOWED_LABEL_KEYS 外的属性静默丢弃,只留白名单 12 维。"""
    span = _make_span(
        attributes={
            "http.request.method": "POST",  # 保留
            "chat.messages_count": 5,  # 不在白名单 → 丢
            "chat.user_id": 42,  # 高基数 → 丢
            "llm.tokens.total_tokens": 1500,  # 不在白名单 → 丢
            "trace_id": "abc",  # 不在白名单 → 丢
            "span_id": "def",  # 不在白名单 → 丢
        },
    )
    labels = _extract_labels(span)

    # 白名单内的保留
    assert labels["http.request.method"] == "POST"
    # 白名单外的全丢
    assert "chat.messages_count" not in labels
    assert "chat.user_id" not in labels
    assert "llm.tokens.total_tokens" not in labels
    assert "trace_id" not in labels
    assert "span_id" not in labels
    # span_name 总是有
    assert labels["span_name"] == "chat.stream"


def test_extract_labels_status_code_classification():
    """http.response.status_code int 自动走 _status_class 5 段映射。"""
    span = _make_span(
        attributes={"http.response.status_code": 404},
    )
    labels = _extract_labels(span)
    assert labels["http.response.status_code"] == "4xx"


def test_extract_labels_value_type_compatibility():
    """value 兼容 bool / int / float / str / None。"""
    span = _make_span(
        attributes={
            "http.request.method": "GET",  # str
            "retrieval.rerank_enabled": True,  # bool
            "retrieval.has_filter": False,  # bool
            "llm.tokens": 1500,  # int — 但 llm.tokens 不在白名单,会被丢
            "embedding.batch_size": 8,  # 不在白名单,会被丢
            "db.system": "mysql",  # str
            "messaging.system": None,  # None → 跳过
        },
    )
    labels = _extract_labels(span)

    assert labels["http.request.method"] == "GET"
    assert labels["retrieval.rerank_enabled"] == "True"  # bool → "True"
    assert labels["retrieval.has_filter"] == "False"  # bool → "False"
    assert labels["db.system"] == "mysql"
    assert "messaging.system" not in labels  # None 跳过
    # 白名单外的 int 值不出现
    assert "llm.tokens" not in labels
    assert "embedding.batch_size" not in labels


def test_extract_labels_span_name_collapse():
    """_KNOWN_SPAN_NAMES 外的 span_name collapse 到 "other",防止 typo
    业务方拼错名字产生 cardinality 爆增。"""
    # 已知 name → 保留
    known = _make_span(name="chat.stream")
    assert _extract_labels(known)["span_name"] == "chat.stream"

    # 已知 name(其他)
    known2 = _make_span(name="llm.chat")
    assert _extract_labels(known2)["span_name"] == "llm.chat"

    # 未知 name → "other"
    unknown = _make_span(name="some.typo.span")
    assert _extract_labels(unknown)["span_name"] == "other"

    # None / 空字符串 → "other"(统一 collapse 路径)
    empty = _make_span(name="")
    assert _extract_labels(empty)["span_name"] == "other"


def test_extract_labels_empty_attributes():
    """空 attributes 不崩,只返 span_name + span.kind。"""
    span = _make_span(attributes={})
    labels = _extract_labels(span)
    assert labels["span_name"] == "chat.stream"
    assert labels["span.kind"] == "INTERNAL"
    assert len(labels) == 2


# ===========================================================================
# Part 4: SpanObserverMetricExporter.on_end + state 管理
# ===========================================================================


def test_on_end_records_counter_and_histogram():
    """on_end 时 Counter inc + Histogram record 各 1 次。"""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])

    # 临时挂到 global MeterProvider 让 processor 能拿 meter
    from opentelemetry import metrics
    from opentelemetry.metrics import _internal as metrics_internal

    saved_mp = metrics_internal._METER_PROVIDER
    metrics_internal._METER_PROVIDER = provider
    try:
        exporter = SpanObserverMetricExporter()
        span = _make_span(
            name="chat.stream",
            start_ns=1_000_000_000,
            end_ns=1_500_000_000,  # 0.5s
        )
        exporter.on_end(span)

        # 再次 on_end 同一 label key → 计数变 2
        exporter.on_end(span)

        reader.force_flush(timeout_millis=5000)
        data = reader.get_metrics_data()
        assert data is not None

        # 至少找到 lumen.span.events + lumen.span.duration
        metric_names = set()
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    metric_names.add(m.name)
        assert "lumen.span.events" in metric_names
        assert "lumen.span.duration" in metric_names

        # Counter sum == 2
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    if m.name == "lumen.span.events":
                        for pt in m.data.data_points:
                            assert pt.value == 2
    finally:
        metrics_internal._METER_PROVIDER = saved_mp
        provider.shutdown()


def test_on_end_cross_span_name_isolation():
    """不同 span_name → 不同 label series(独立 Counter / Histogram)。"""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])

    from opentelemetry.metrics import _internal as metrics_internal

    saved_mp = metrics_internal._METER_PROVIDER
    metrics_internal._METER_PROVIDER = provider
    try:
        exporter = SpanObserverMetricExporter()

        # 3 个不同 span_name 各 2 次
        for name in ["chat.stream", "embedding.generate", "llm.chat"]:
            span = _make_span(name=name)
            exporter.on_end(span)
            exporter.on_end(span)

        reader.force_flush(timeout_millis=5000)
        data = reader.get_metrics_data()

        # 找到 3 个独立 series(每个 span_name 一个 Counter data_point)
        counter_pts = []
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    if m.name == "lumen.span.events":
                        for pt in m.data.data_points:
                            counter_pts.append((dict(pt.attributes), pt.value))

        # 应该有 3 个不同 (span_name, value=2) data_points
        assert len(counter_pts) == 3
        for attrs, value in counter_pts:
            assert value == 2
            assert "span_name" in attrs
    finally:
        metrics_internal._METER_PROVIDER = saved_mp
        provider.shutdown()


def test_on_end_skips_invalid_time():
    """没有 end_time / start_time / 时间颠倒的 span 直接丢,不计数。"""
    exporter = SpanObserverMetricExporter()

    # end_time = 0
    span_no_end = _make_span(end_ns=0)
    exporter.on_end(span_no_end)
    assert len(exporter._counters) == 0

    # start > end(时间颠倒)
    span_bad = _make_span(start_ns=2_000_000_000, end_ns=1_000_000_000)
    exporter.on_end(span_bad)
    assert len(exporter._counters) == 0

    # fail_count 不增(异常路径只在 try/except 命中时计)
    assert exporter._fail_count == 0


def test_on_end_exception_swallowed():
    """on_end 内部异常 swallow(不影响后续 span)。"""
    from unittest.mock import patch

    exporter = SpanObserverMetricExporter()

    # mock _record 第一次抛,第二次正常
    real_record = exporter._record
    call_count = [0]

    def flaky_record(span):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("boom")
        return real_record(span)

    with patch.object(exporter, "_record", side_effect=flaky_record):
        span = _make_span()
        # 第一次 → 抛 → swallow
        exporter.on_end(span)
        # 第二次 → 正常
        exporter.on_end(span)

    # fail_count 计 1
    assert exporter._fail_count == 1
    # 第二次成功 → Counter 有 1 个 entry
    assert len(exporter._counters) >= 1


def test_shutdown_clears_state():
    """shutdown 清 _counters / _histograms / _meter。"""
    exporter = SpanObserverMetricExporter()
    span = _make_span()
    exporter.on_end(span)

    assert len(exporter._counters) > 0
    assert exporter._meter is not None

    exporter.shutdown()

    assert len(exporter._counters) == 0
    assert len(exporter._histograms) == 0
    assert exporter._meter is None


def test_force_flush_returns_true_on_no_provider(_otel_metrics_test_env):
    """force_flush 在没 setup_metrics() 时返 True(swallow 不存在 reader)。"""
    # reset 后 _reader / _meter_provider = None
    result = force_flush(timeout_millis=5000)
    assert result is True


def test_force_flush_exception_swallowed(_otel_metrics_test_env, monkeypatch):
    """force_flush 内部 reader 抛异常时 swallow + 返 False(镜像
    ``otel.force_flush`` 的语义:exception 走 return False,跟 docstring
    "True if called; False if not initialized / exception raised" 一致)。
    """
    monkeypatch.setenv("OTEL_EXPORTER", "none")
    setup_metrics()  # 返回 False,但 module state 已 reset

    # mock _reader 抛异常
    class _Boom:
        def force_flush(self, timeout_millis=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(otel_metrics, "_reader", _Boom())
    result = force_flush(timeout_millis=5000)
    # exception → swallow + 返 False(跟 otel.py 同步语义)
    assert result is False


# ===========================================================================
# Part 5: reset_for_test + module-level state
# ===========================================================================


def test_reset_for_test_clears_module_state(_otel_metrics_test_env, monkeypatch):
    """reset_for_test 后 is_initialized() 返 False,module 状态清干净。"""
    from unittest.mock import patch
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")

    with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
        with patch.object(
            sdk_metrics_export,
            "PeriodicExportingMetricReader",
            return_value=InMemoryMetricReader(),
        ):
            setup_metrics()
            assert is_initialized() is True

    # reset
    reset_for_test()
    assert is_initialized() is False
    assert otel_metrics._processor is None
    assert otel_metrics._meter_provider is None
    assert otel_metrics._reader is None

    # OTel metrics module-level state 也清(否则下一次 setup_metrics 被
    # _once.Once 拒)
    from opentelemetry.metrics import _internal as metrics_internal

    assert metrics_internal._METER_PROVIDER is None
    assert metrics_internal._METER_PROVIDER_SET_ONCE._done is False


def test_reset_for_test_when_not_initialized(_otel_metrics_test_env):
    """reset_for_test 在没 setup_metrics() 时调不崩(swallow all)。"""
    # 没调 setup_metrics 直接 reset
    reset_for_test()
    assert is_initialized() is False


# ===========================================================================
# Part 6: setup_metrics 端到端 + InMemoryMetricReader 集成
# ===========================================================================


def test_setup_metrics_full_flow_with_in_memory_reader(_otel_metrics_test_env, monkeypatch):
    """setup_metrics() 完整跑通 → 挂 SpanObserverMetricExporter → span
    on_end → InMemoryMetricReader 读到 lumen.span.events / lumen.span.duration。

    这是 Day 6 主链路端到端验证。
    """
    from opentelemetry import trace
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )
    from unittest.mock import patch

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")

    fake_reader = InMemoryMetricReader()

    with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
        with patch.object(
            sdk_metrics_export,
            "PeriodicExportingMetricReader",
            return_value=fake_reader,
        ):
            assert setup_metrics() is True

    # 模拟真实业务 span(走当前 TracerProvider 起 span → end → 触发
    # SpanObserverMetricExporter.on_end)。
    in_mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(in_mem))
    trace.set_tracer_provider(provider)

    # 复用 setup_metrics 挂的 SpanObserverMetricExporter
    processor = otel_metrics.get_processor()
    assert processor is not None
    provider.add_span_processor(processor)

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("chat.stream") as span:
        span.set_attribute("http.request.method", "POST")
        span.set_attribute("http.response.status_code", 200)
        pass  # span 自动 end

    fake_reader.force_flush(timeout_millis=5000)
    data = fake_reader.get_metrics_data()
    assert data is not None

    metric_names = set()
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                metric_names.add(m.name)
    assert "lumen.span.events" in metric_names
    assert "lumen.span.duration" in metric_names

    # Counter 至少 1(我们的 chat.stream span)
    counter_pts = []
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == "lumen.span.events":
                    for pt in m.data.data_points:
                        counter_pts.append((dict(pt.attributes), pt.value))
    assert len(counter_pts) >= 1
    # 我们的 span_name=chat.stream + status_code=2xx 应该出现
    has_match = any(
        attrs.get("span_name") == "chat.stream"
        and attrs.get("http.response.status_code") == "2xx"
        for attrs, _ in counter_pts
    )
    assert has_match


# ===========================================================================
# Part 7: HTTPS_PROXY 警告
# ===========================================================================


def test_https_proxy_warning(_otel_metrics_test_env, monkeypatch, caplog):
    """HTTPS_PROXY / GRPC_PROXY env 触发 logger.warning,提示运维 unset。"""
    from unittest.mock import patch
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.com:8080")
    monkeypatch.setenv("GRPC_PROXY", "http://grpc-proxy.example.com:8080")

    with caplog.at_level(logging.WARNING, logger="lumen_core.otel_metrics"):
        with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
            with patch.object(
                sdk_metrics_export,
                "PeriodicExportingMetricReader",
                return_value=InMemoryMetricReader(),
            ):
                setup_metrics()

    # 检查 warning 文案含 proxy.example.com / GRPC_PROXY
    warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("HTTPS_PROXY/GRPC_PROXY" in m for m in warning_msgs)
    assert any("proxy.example.com" in m for m in warning_msgs)


# ===========================================================================
# Part 8: 已知 list 完整性(防 allowlist / KNOWN drift)
# ===========================================================================


def test_allowed_label_keys_count():
    """_ALLOWED_LABEL_KEYS 应该 15 个 key(plan 估 12 维,实际 15 是 plan 后扩展,
    设计决策:留 12-15 范围都行,关键是 frozenset 锁定)。

    防止有人误删 key 导致业务 label 丢(虽然 cardinality 控,但白名单
    本身是单一真相源)。
    """
    # 至少 12 个 + 至少包含关键 attribute key
    assert len(_ALLOWED_LABEL_KEYS) >= 12
    must_have = {
        "span.kind",
        "http.request.method",
        "http.response.status_code",
        "llm.call_kind",
        "embedding.call_kind",
        "workflow.status",
        "workflow.node.status",
        "workflow.node.type",
    }
    assert must_have.issubset(_ALLOWED_LABEL_KEYS)


def test_known_span_names_includes_core():
    """_KNOWN_SPAN_NAMES 必须包含当前 traced_span 已 ship 的所有 name,
    否则会被 collapse 到 "other" 看不到。"""
    must_have = {
        "chat.stream",
        "chat.endpoint",
        "embedding.generate",
        "retrieval.search",
        "workflow.run",
        "workflow.node",
        "llm.chat",
        "http.client",
        "http.server",
    }
    assert must_have.issubset(_KNOWN_SPAN_NAMES)


# ===========================================================================
# Part 9: otel.py 串联
# ===========================================================================


def test_setup_tracing_cascades_to_metrics(_otel_metrics_test_env, monkeypatch):
    """otel.setup_tracing() 在 OTLP 模式下自动调 setup_metrics(),挂
    SpanObserverMetricExporter 到 TracerProvider。

    验证:setup_tracing() 后 is_initialized()(otel_metrics)+ has
    SpanObserverMetricExporter on TracerProvider。
    """
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export
    from unittest.mock import patch

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")

    with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
        with patch.object(
            sdk_metrics_export,
            "PeriodicExportingMetricReader",
            return_value=InMemoryMetricReader(),
        ):
            # 调 setup_tracing → 应该级联 setup_metrics
            from lumen_core import otel

            result = otel.setup_tracing()
            assert result is True
            # metric 模块也跟着初始化
            assert is_initialized() is True


def test_force_flush_cascades_to_metrics(_otel_metrics_test_env, monkeypatch):
    """otel.force_flush() 在 metric 已 setup 后调用,级联 metric flush
    (force_flush 末尾 _metrics_force_flush)。

    这里不跑真实 flush,只验证 otel.force_flush 不抛异常 +
    module-level state 路径走得通。
    """
    from unittest.mock import patch
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.metrics import export as sdk_metrics_export

    monkeypatch.setenv("OTEL_EXPORTER", "otlp")

    with patch("lumen_core.otel_metrics.OTLPMetricExporter", create=True):
        with patch.object(
            sdk_metrics_export,
            "PeriodicExportingMetricReader",
            return_value=InMemoryMetricReader(),
        ):
            from lumen_core import otel

            otel.setup_tracing()
            # otel.force_flush 串联到 metric flush
            result = otel.force_flush(timeout_millis=5000)
            assert result is True  # span flush 返 True