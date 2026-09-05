"""Phase 1 Group B 2.4.4 (2026-09-04):trace_id bridge OTel 单测。

覆盖:
- contextvar 有值时优先(向后兼容 14 个老 test)
- contextvar 空 + OTel span context valid → 返 OTel trace_id 32-hex
- contextvar 空 + OTel 未安装 → 返 None(不抛 ImportError)
- contextvar 空 + OTel 安装但当前无 span → 返 None
- contextvar 空 + OTel span context invalid → 返 None
- contextvar 空 + OTel SDK 内部异常 → swallow + 返 None
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest

from lumen_core import tracing


@pytest.fixture(autouse=True)
def _reset():
    """每个 test 后清 contextvar(autouse 防串)。"""
    yield
    tracing.reset_for_test()


# ===== contextvar 优先级 — 向后兼容老 14 个 test =====


def test_contextvar_wins_over_otel():
    """contextvar 有值时 get_trace_id() 返 contextvar 值,不查 OTel。

    重要:这是 back-compat 守门 — Phase 0 ship 的 14 个 trace_id 测试
    全部假设 get_trace_id 优先看 contextvar。"""
    tracing.set_trace_id("contextvar-value")

    # 假设 OTel 当前无 span / 无有效 span
    # 不 import OTel → 模拟 "OTel 未装" 也得返回 contextvar 值
    tid = tracing.get_trace_id()
    assert tid == "contextvar-value"


def test_contextvar_wins_over_otel_even_with_valid_span(monkeypatch):
    """即使 OTel 当前有 valid span,contextvar 仍优先(防 OTel-first 改顺序回归)。"""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    # 用 SDK TracerProvider 起 span(避免 ProxyTracerProvider 的 SpanContext.INVALID)
    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("test-span") as span:
        # span 应有 valid SpanContext
        assert span.get_span_context().is_valid

        tracing.set_trace_id("ctx-priority")

        tid = tracing.get_trace_id()
        # contextvar 值优先,不是 OTel span 的 32-hex
        assert tid == "ctx-priority"


# ===== OTel 回退路径 =====


def test_otel_fallback_when_contextvar_empty(monkeypatch):
    """contextvar 空 + OTel valid span → 返 OTel trace_id 32-hex。"""
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    # 确保 contextvar 空
    assert tracing.get_trace_id() is None

    with tracer.start_as_current_span("otel-span") as span:
        tid = tracing.get_trace_id()
        assert tid is not None
        # OTel trace_id 是 int → 32-hex 格式
        assert len(tid) == 32
        assert all(c in "0123456789abcdef" for c in tid)
        # 应等于 OTel span context 的 trace_id
        sc = span.get_span_context()
        assert tid == format(sc.trace_id, "032x")


def test_otel_fallback_returns_correct_trace_id_across_spans(monkeypatch):
    """不同 span → 返不同 trace_id(不会缓存上次的)。"""
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("span-a"):
        tid_a = tracing.get_trace_id()

    with tracer.start_as_current_span("span-b"):
        tid_b = tracing.get_trace_id()

    assert tid_a is not None
    assert tid_b is not None
    assert tid_a != tid_b


# ===== OTel 未安装路径 =====


def test_returns_none_when_otel_not_installed(monkeypatch):
    """contextvar 空 + OTel import 失败 → 返 None,不抛异常。

    防 OTEL_EXPORTER=none 的 dev / pytest 场景 OTel SDK 没装时炸。
    """
    # mock opentelemetry import 失败
    import sys
    # 删 sys.modules 里所有 opentelemetry entries → 模拟 "未装"
    otel_modules = {k: v for k, v in sys.modules.items() if k.startswith("opentelemetry")}
    for k in otel_modules:
        monkeypatch.delitem(sys.modules, k)

    # 强行让 import opentelemetry 失败(builtins.__import__ hook)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("simulated: opentelemetry not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert tracing.get_trace_id() is None  # 不能炸


# ===== OTel 安装但当前无 valid span =====


def test_returns_none_when_otel_no_active_span(monkeypatch):
    """OTel 装了但当前 NoOp / 无 valid span → 返 None。

    用 NoOpTracer(ProxyTracerProvider 默认)模拟 "OTel 未 setup" 的常见情形。
    """
    # ProxyTracerProvider 默认给 NoOp tracer,get_current_span().get_span_context().is_valid == False
    assert tracing.get_trace_id() is None


# ===== OTel SDK 内部异常 — bridge 必须 swallow =====


def test_swallows_otel_sdk_exception(monkeypatch):
    """OTel SDK 在 get_current_span / get_span_context 抛任何异常 → swallow + 返 None。

    bridge 是 observability helper,不能拖垮业务。
    """
    from opentelemetry import trace as otel_trace

    class _BoomSpan:
        def get_span_context(self):
            raise RuntimeError("simulated OTel internal error")

    class _BoomTracer:
        def get_current_span(self):
            return _BoomSpan()

    monkeypatch.setattr(otel_trace, "get_current_span", _BoomTracer().get_current_span)

    # 应 swallow + 返 None
    assert tracing.get_trace_id() is None


# ===== set_trace_id(None) 后回退到 OTel =====


def test_set_none_falls_back_to_otel(monkeypatch):
    """set_trace_id(None) 清掉 contextvar 后,get_trace_id 应回退到 OTel(如果 OTel 有 valid span)。

    测试两种场景:
    (a) 当前 OTel 有 valid span → 返 OTel trace_id 32-hex
    (b) 当前 OTel 无 valid span / NoOp → 返 None
    """
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    # (a) span 内:set(None) 后,fallback 应给 OTel trace_id
    with tracer.start_as_current_span("bridge-span") as span:
        sc = span.get_span_context()

        tracing.set_trace_id("temp")
        assert tracing.get_trace_id() == "temp"
        tracing.set_trace_id(None)

        tid = tracing.get_trace_id()
        assert tid is not None
        assert tid == format(sc.trace_id, "032x")

    # (b) span 外(set(None) 后):OTel 仍在 process state 但 current span 无效 → 返 None
    tracing.set_trace_id(None)
    tid = tracing.get_trace_id()
    # 出 span 后 current_span 是 NoOp(SpanContext.INVALID)→ 返 None
    assert tid is None


# ===== 整链路:contextvar → OTel fallback 优先级不变 =====


def test_bridge_priority_does_not_change_with_otel_state(monkeypatch):
    """无论 OTel 装了 / 未装 / span valid / invalid,contextvar 优先级都不变。"""
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    # 4 种 OTel 状态,contextvar 优先应该一致
    states = [
        "no_otel",          # OTel 未装 / proxy NoOp
        "otel_with_span",   # OTel 装了 + valid span
    ]

    for state in states:
        tracing.reset_for_test()
        tracing.set_trace_id(f"ctx-{state}")

        if state == "otel_with_span":
            with tracer.start_as_current_span(f"span-{state}"):
                assert tracing.get_trace_id() == f"ctx-{state}"
        else:
            # no_otel 状态 — 不起 SDK span
            assert tracing.get_trace_id() == f"ctx-{state}"
