"""Phase 1 Group A 2.3 (2026-09-03): circuit_breaker.py 单元测试。"""
from __future__ import annotations

import asyncio
import time

import pytest

from lumen_services.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitOpenError,
)


# ---------------------------------------------------------------------------
# CircuitBreaker 单实例
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closed_state_allows_calls():
    cb = CircuitBreaker("test_closed", failure_threshold=3, recovery_timeout=1)

    async def ok():
        return "value"

    result = await cb.call_async(ok)
    assert result == "value"
    assert cb.state == "closed"
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_closed_transitions_to_open_after_threshold():
    cb = CircuitBreaker("test_open_after_threshold", failure_threshold=3, recovery_timeout=10)

    async def boom():
        raise ValueError("fail")

    for i in range(3):
        with pytest.raises(ValueError):
            await cb.call_async(boom)
    assert cb.state == "open"
    assert cb.failure_count == 3


@pytest.mark.asyncio
async def test_open_state_rejects_calls():
    cb = CircuitBreaker("test_open_reject", failure_threshold=2, recovery_timeout=10)
    cb.force_open()
    assert cb.state == "open"

    async def should_not_run():
        pytest.fail("should not reach inner func when breaker open")

    with pytest.raises(CircuitOpenError, match="OPEN"):
        await cb.call_async(should_not_run)


@pytest.mark.asyncio
async def test_open_to_half_open_after_recovery_timeout():
    cb = CircuitBreaker("test_recovery", failure_threshold=2, recovery_timeout=0.1)
    cb.force_open()
    assert cb.state == "open"

    # 等 recovery_timeout
    await asyncio.sleep(0.15)

    async def ok():
        return "recovered"

    # 下一次 call 应该转入 half_open + 放行
    result = await cb.call_async(ok)
    assert result == "recovered"
    assert cb.state == "half_open"


@pytest.mark.asyncio
async def test_half_open_to_closed_after_max_successes():
    cb = CircuitBreaker(
        "test_half_to_closed", failure_threshold=2, recovery_timeout=0.05,
        half_open_max=3,
    )
    cb.force_open()
    await asyncio.sleep(0.1)

    async def ok():
        return "ok"

    for _ in range(3):
        await cb.call_async(ok)
    assert cb.state == "closed"
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_half_open_failure_returns_to_open():
    cb = CircuitBreaker(
        "test_half_to_open", failure_threshold=2, recovery_timeout=0.05,
        half_open_max=3,
    )
    cb.force_open()
    await asyncio.sleep(0.1)

    async def boom():
        raise RuntimeError("fail during half_open")

    with pytest.raises(RuntimeError):
        await cb.call_async(boom)
    assert cb.state == "open"
    assert cb.success_count == 0


@pytest.mark.asyncio
async def test_closed_resets_failure_count_on_success():
    """closed 阶段偶发成功应重置 failure_count,避免累积误触。"""
    cb = CircuitBreaker("test_reset_on_success", failure_threshold=3, recovery_timeout=10)

    async def boom():
        raise ValueError("fail")

    async def ok():
        return "ok"

    with pytest.raises(ValueError):
        await cb.call_async(boom)
    with pytest.raises(ValueError):
        await cb.call_async(boom)
    assert cb.failure_count == 2

    # 一次成功应该重置
    await cb.call_async(ok)
    assert cb.failure_count == 0
    assert cb.state == "closed"


# ---------------------------------------------------------------------------
# sync call_sync
# ---------------------------------------------------------------------------


def test_sync_call_succeeds():
    cb = CircuitBreaker("test_sync", failure_threshold=2, recovery_timeout=10)
    assert cb.call_sync(lambda: 42) == 42
    assert cb.state == "closed"


def test_sync_call_failure_opens_after_threshold():
    cb = CircuitBreaker("test_sync_open", failure_threshold=2, recovery_timeout=10)
    for _ in range(2):
        with pytest.raises(ValueError):
            cb.call_sync(lambda: (_ for _ in ()).throw(ValueError("x")))
    assert cb.state == "open"


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry
# ---------------------------------------------------------------------------


def test_registry_returns_same_instance():
    CircuitBreakerRegistry.reset_all()
    a = CircuitBreakerRegistry.get("ollama")
    b = CircuitBreakerRegistry.get("ollama")
    assert a is b


def test_registry_uses_default_config():
    CircuitBreakerRegistry.reset_all()
    cb = CircuitBreakerRegistry.get("ollama")
    # ollama default: failure_threshold=5
    assert cb.failure_threshold == 5
    assert cb.recovery_timeout == 30
    assert cb.half_open_max == 3


def test_registry_kwargs_override_defaults():
    CircuitBreakerRegistry.reset_all()
    cb = CircuitBreakerRegistry.get("custom", failure_threshold=99)
    assert cb.failure_threshold == 99


def test_registry_unknown_uses_fallback():
    CircuitBreakerRegistry.reset_all()
    cb = CircuitBreakerRegistry.get("unknown_thing")
    # fallback: empty cfg + kwargs,意味着 CircuitBreaker defaults
    # failure_threshold=5 (default __init__ value)
    assert cb.failure_threshold == 5
    assert cb.recovery_timeout == 30


def test_registry_reset_all():
    CircuitBreakerRegistry.reset_all()
    CircuitBreakerRegistry.get("ollama")
    CircuitBreakerRegistry.get("openai")
    assert len(CircuitBreakerRegistry.get_all()) == 2
    CircuitBreakerRegistry.reset_all()
    assert len(CircuitBreakerRegistry.get_all()) == 0


# ---------------------------------------------------------------------------
# CircuitOpenError + state transitions
# ---------------------------------------------------------------------------


def test_circuit_open_error_message_includes_name():
    err = CircuitOpenError("circuit_breaker[ollama] is OPEN; refusing call")
    assert "ollama" in str(err)
    assert "OPEN" in str(err)


def test_force_close_resets_state():
    cb = CircuitBreaker("test_force_close", failure_threshold=2, recovery_timeout=10)
    cb.force_open()
    assert cb.state == "open"
    cb.force_close()
    assert cb.state == "closed"
    assert cb.failure_count == 0
    assert cb.success_count == 0


@pytest.mark.asyncio
async def test_state_change_logs(caplog):
    """验证 state 切换会写 INFO log(运维 / debug 友好)。"""
    import logging
    caplog.set_level(logging.INFO, logger="lumen_services.circuit_breaker")
    cb = CircuitBreaker("test_log", failure_threshold=2, recovery_timeout=10)

    async def boom():
        raise ValueError("x")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call_async(boom)
    assert any("closed -> open" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_coro_factory_called_each_attempt():
    """coro_factory 必须每次调用创建新 coroutine(避免重用已 await 的)。"""
    cb = CircuitBreaker("test_factory", failure_threshold=10, recovery_timeout=10)
    call_count = {"n": 0}

    def factory():
        call_count["n"] += 1

        async def _coro():
            return call_count["n"]

        return _coro()

    result = await cb.call_async(factory)
    assert result == 1
    assert call_count["n"] == 1
