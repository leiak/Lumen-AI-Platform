"""Phase 0 Unit 5 4.2 (2026-09-02):trace_id contextvar 测试。

覆盖:
- new_trace_id 生成 32-hex + set
- set_trace_id / get_trace_id / clear_trace_id round-trip
- ensure_trace_id 无则生成,有则透传
- ContextVar 隔离(异步 / set-then-reset)
- reset_for_test 兜底
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio

import pytest

from lumen_core import tracing


@pytest.fixture(autouse=True)
def _reset():
    """每个 test 后清 contextvar(autouse 防串)。"""
    tracing.reset_for_test()


# ===== 基础读写 =====


def test_new_trace_id_generates_32hex_and_sets():
    """new_trace_id 返 32 hex 字符(uuid4)+ set 到 ctx。"""
    tid = tracing.new_trace_id()
    assert len(tid) == 32
    assert all(c in "0123456789abcdef" for c in tid)
    assert tracing.get_trace_id() == tid


def test_new_trace_id_returns_unique_values():
    """连续两次 new_trace_id 返不同值(防碰撞)。"""
    t1 = tracing.new_trace_id()
    t2 = tracing.new_trace_id()
    assert t1 != t2


def test_set_and_get_round_trip():
    """set_trace_id → get_trace_id 透传。"""
    tracing.set_trace_id("abc123def456")
    assert tracing.get_trace_id() == "abc123def456"


def test_set_trace_id_none_clears():
    """set_trace_id(None) 等价于 clear。"""
    tracing.new_trace_id()
    tracing.set_trace_id(None)
    assert tracing.get_trace_id() is None


def test_clear_trace_id():
    """clear_trace_id 直接清。"""
    tracing.new_trace_id()
    tracing.clear_trace_id()
    assert tracing.get_trace_id() is None


def test_get_default_is_none():
    """未设过 → get_trace_id 返 None(默认)。"""
    assert tracing.get_trace_id() is None


# ===== ensure_trace_id =====


def test_ensure_trace_id_generates_when_none():
    """ensure_trace_id 在 None 时生成新的。"""
    assert tracing.get_trace_id() is None
    tid = tracing.ensure_trace_id()
    assert tid is not None
    assert len(tid) == 32
    assert tracing.get_trace_id() == tid


def test_ensure_trace_id_returns_existing():
    """ensure_trace_id 在已有时透传(不重新生成)。"""
    tracing.set_trace_id("existing-tid")
    tid = tracing.ensure_trace_id()
    assert tid == "existing-tid"


# ===== ContextVar 隔离:同步 reset 不影响后续 set =====


def test_contextvar_isolation_with_explicit_reset():
    """手动 set + clear 隔离(模拟 save/restore 模式)。"""
    tracing.set_trace_id("outer")
    assert tracing.get_trace_id() == "outer"

    tracing.clear_trace_id()
    assert tracing.get_trace_id() is None

    tracing.set_trace_id("inner")
    assert tracing.get_trace_id() == "inner"


# ===== 异步 isolation:asyncio.Task 各自 context =====


def test_async_tasks_have_independent_context():
    """asyncio.Task 各自 copy context,互不影响。"""
    results: dict = {}

    async def task_a():
        tracing.set_trace_id("trace-a")
        await asyncio.sleep(0)  # 让出执行权
        results["a"] = tracing.get_trace_id()

    async def task_b():
        tracing.set_trace_id("trace-b")
        await asyncio.sleep(0)
        results["b"] = tracing.get_trace_id()

    async def main():
        await asyncio.gather(task_a(), task_b())

    asyncio.run(main())
    assert results["a"] == "trace-a"
    assert results["b"] == "trace-b"


def test_async_task_inherits_parent_context():
    """子 task 默认继承父 task 的 contextvar(set 后子能看到)。"""
    results: dict = {}

    async def child():
        # child 没显式 set,应继承 parent
        results["child"] = tracing.get_trace_id()

    async def parent():
        tracing.set_trace_id("parent-tid")
        await asyncio.gather(child())

    asyncio.run(parent())
    assert results["child"] == "parent-tid"


# ===== HEADER_NAMES 常量 =====


def test_header_names_includes_x_trace_id():
    """HEADER_NAMES 包含 X-Trace-Id。"""
    assert "X-Trace-Id" in tracing.HEADER_NAMES


def test_header_names_includes_x_request_id():
    """HEADER_NAMES 包含 X-Request-Id(兼容行业惯例)。"""
    assert "X-Request-Id" in tracing.HEADER_NAMES


def test_header_names_includes_traceparent():
    """HEADER_NAMES 包含 traceparent(W3C Trace Context,OTel 互操作)。"""
    assert "traceparent" in tracing.HEADER_NAMES


# ===== reset_for_test =====


def test_reset_for_test_clears_context():
    """reset_for_test 兜底清空(autouse fixture 已隐式验,这里再单测)。"""
    tracing.new_trace_id()
    assert tracing.get_trace_id() is not None
    tracing.reset_for_test()
    assert tracing.get_trace_id() is None