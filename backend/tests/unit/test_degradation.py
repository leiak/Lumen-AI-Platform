"""Phase 1 Group A 2.4 (2026-09-03): degradation.py 单元测试。"""
from __future__ import annotations

import asyncio
import pytest

from lumen_services.circuit_breaker import (
    CircuitBreakerRegistry,
    CircuitOpenError,
)
from lumen_services.degradation import degradable


@pytest.fixture(autouse=True)
def _reset_breaker_registry():
    """每个 test 隔离 CircuitBreakerRegistry。"""
    CircuitBreakerRegistry.reset_all()
    yield
    CircuitBreakerRegistry.reset_all()


# ---------------------------------------------------------------------------
# async degradable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_succeeds_no_fallback():
    @degradable(fallback=lambda: "default")
    async def fn():
        return "ok"

    assert await fn() == "ok"


@pytest.mark.asyncio
async def test_async_exception_triggers_fallback_callable():
    @degradable(fallback=lambda *a, **kw: {"results": []})
    async def fn(*args, **kwargs):
        raise ValueError("boom")

    result = await fn("x", y=1)
    assert result == {"results": [], "_degraded": True, "_degraded_reason": "boom"}


@pytest.mark.asyncio
async def test_async_fallback_literal_value():
    @degradable(fallback=[])
    async def fn():
        raise RuntimeError("always fails")

    assert await fn() == []


@pytest.mark.asyncio
async def test_async_no_fallback_reraises():
    @degradable(fallback=None)
    async def fn():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await fn()


@pytest.mark.asyncio
async def test_async_no_metadata_for_non_dict_fallback():
    @degradable(fallback=lambda: "literal")
    async def fn():
        raise ValueError("x")

    # 非 dict 返回值,不注入 _degraded(避免污染)
    assert await fn() == "literal"


@pytest.mark.asyncio
async def test_async_with_breaker_open():
    """breaker open 时,CircuitOpenError 触发 fallback。"""

    @degradable(breaker_name="ollama", fallback=lambda: [])
    async def call_ollama():
        return "should_not_run"

    # 手动 force open
    breaker = CircuitBreakerRegistry.get("ollama")
    breaker.force_open()

    result = await call_ollama()
    assert result == []


@pytest.mark.asyncio
async def test_async_breaker_close_lets_call_through():
    """breaker closed 时,func 正常调用,不触发 fallback。"""

    @degradable(breaker_name="openai", fallback=lambda: "fallback")
    async def call_openai():
        return "real_call"

    breaker = CircuitBreakerRegistry.get("openai")
    # default closed
    assert await call_openai() == "real_call"


@pytest.mark.asyncio
async def test_async_breaker_failure_triggers_fallback():
    """breaker closed 但 func 抛错 → fallback。"""

    @degradable(breaker_name="s3", fallback=lambda: "degraded")
    async def call_s3():
        raise RuntimeError("s3 down")

    breaker = CircuitBreakerRegistry.get("s3")
    # 默认 threshold=3 (s3 config),1 次失败不触发 open
    assert await call_s3() == "degraded"
    assert breaker.state == "closed"


@pytest.mark.asyncio
async def test_async_custom_exceptions_filter():
    """exceptions 参数收紧到指定类型,非白名单异常不被降级。"""

    @degradable(
        fallback=lambda: "caught",
        exceptions=(ValueError,),
    )
    async def fn():
        raise KeyError("not caught")

    with pytest.raises(KeyError):
        await fn()


@pytest.mark.asyncio
async def test_async_callback_invoked_on_degradation():
    calls = {"n": 0}

    def cb(exc):
        calls["n"] += 1

    @degradable(fallback=lambda: None, on_degraded_callback=cb)
    async def fn():
        raise ValueError("x")

    await fn()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_async_callback_failure_does_not_break_degradation():
    """callback 自身抛错时,降级主流程不受影响。"""

    def bad_cb(exc):
        raise RuntimeError("callback boom")

    @degradable(fallback=lambda: "fallback_result", on_degraded_callback=bad_cb)
    async def fn():
        raise ValueError("x")

    # 应该不抛 callback 的错误,而是正常走 fallback
    assert await fn() == "fallback_result"


@pytest.mark.asyncio
async def test_async_log_warning(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="lumen_services.degradation")

    @degradable(fallback=lambda: None)
    async def my_async_func():
        raise ValueError("logged_failure")

    await my_async_func()
    assert any(
        "degraded" in r.message and "my_async_func" in r.message
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_async_silent_log():
    """log_warning=False 时,不写 warning。"""

    @degradable(fallback=lambda: None, log_warning=False)
    async def fn():
        raise ValueError("silent")

    assert await fn() is None


# ---------------------------------------------------------------------------
# sync degradable
# ---------------------------------------------------------------------------


def test_sync_succeeds_no_fallback():
    @degradable(fallback="default")
    def fn():
        return "ok"

    assert fn() == "ok"


def test_sync_exception_triggers_fallback():
    @degradable(fallback=lambda: "default_value")
    def fn():
        raise RuntimeError("sync boom")

    assert fn() == "default_value"


def test_sync_fallback_dict_metadata():
    @degradable(fallback=lambda: {"data": []})
    def fn():
        raise ValueError("x")

    assert fn() == {"data": [], "_degraded": True, "_degraded_reason": "x"}


def test_sync_no_fallback_reraises():
    @degradable(fallback=None)
    def fn():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        fn()


def test_sync_with_breaker_open():
    @degradable(breaker_name="mcp", fallback=lambda: "fb")
    def call_mcp():
        return "real"

    CircuitBreakerRegistry.get("mcp").force_open()
    assert call_mcp() == "fb"


# ---------------------------------------------------------------------------
# decorator 保留 func metadata
# ---------------------------------------------------------------------------


def test_decorator_preserves_func_name():
    @degradable(fallback=lambda: None)
    def my_sync():
        return 1

    @degradable(fallback=lambda: None)
    async def my_async():
        return 1

    assert my_sync.__name__ == "my_sync"
    assert my_async.__name__ == "my_async"


# ---------------------------------------------------------------------------
# 真实场景:hybrid_retriever 用法
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_retriever_like_usage():
    """模拟 hybrid_retriever.vector_search 用法:失败返 [] + _degraded。"""

    @degradable(
        breaker_name="elasticsearch",
        fallback=lambda query, top_k: {"results": [], "total": 0},
        exceptions=(ConnectionError, TimeoutError),
    )
    async def vector_search(query: str, top_k: int = 5):
        raise ConnectionError("ES down")

    result = await vector_search("hello", top_k=3)
    assert result["results"] == []
    assert result["_degraded"] is True
    assert "ES down" in result["_degraded_reason"]
