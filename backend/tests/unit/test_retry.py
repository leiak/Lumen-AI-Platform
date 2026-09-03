"""Phase 1 Group A 2.5 (2026-09-03): retry.py 单元测试。"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from lumen_services.retry import (
    TRANSIENT_EXCEPTIONS,
    async_retry_transient,
    call_async_with_retry,
    call_sync_with_retry,
    sync_retry_transient,
)


# ---------------------------------------------------------------------------
# async_retry_transient
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_succeeds_first_attempt_no_retry():
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        return "ok"

    result = await fn()
    assert result == "ok"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_async_retries_transient_then_succeeds():
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("conn refused")
        return "recovered"

    result = await fn()
    assert result == "recovered"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_async_reraises_after_max_attempts():
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        raise httpx.ConnectError(f"fail-{calls['n']}")

    with pytest.raises(httpx.ConnectError, match="fail-3"):
        await fn()
    assert calls["n"] == 3  # 3 attempts total


@pytest.mark.asyncio
async def test_async_no_retry_on_non_transient():
    """ValueError 等业务异常立即抛,不被 retry。"""
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await fn()
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_async_timeout_exception_retried():
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.TimeoutException("read timeout")
        return "ok"

    result = await fn()
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_async_remote_protocol_error_retried():
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.RemoteProtocolError("server closed")
        return "ok"

    result = await fn()
    assert result == "ok"
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_async_builtin_connection_error_retried():
    calls = {"n": 0}

    @async_retry_transient
    async def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("network unreachable")
        return "ok"

    result = await fn()
    assert result == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_async_backoff_exponential():
    """3 attempts: 立即 + 0.5s + 1.0s = 至少 1.5s 总耗时。"""
    @async_retry_transient
    async def fn():
        raise httpx.ConnectError("always fails")

    t0 = time.monotonic()
    with pytest.raises(httpx.ConnectError):
        await fn()
    elapsed = time.monotonic() - t0
    # 0.5 + 1.0 = 1.5s minimum,容差 0.4s 给 tenacity 内部调度
    assert elapsed >= 1.1, f"backoff too fast: {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# sync_retry_transient
# ---------------------------------------------------------------------------


def test_sync_succeeds_first_attempt_no_retry():
    calls = {"n": 0}

    @sync_retry_transient
    def fn():
        calls["n"] += 1
        return "ok"

    assert fn() == "ok"
    assert calls["n"] == 1


def test_sync_retries_transient_then_succeeds():
    calls = {"n": 0}

    @sync_retry_transient
    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("conn refused")
        return "recovered"

    assert fn() == "recovered"
    assert calls["n"] == 2


def test_sync_reraises_after_max_attempts():
    calls = {"n": 0}

    @sync_retry_transient
    def fn():
        calls["n"] += 1
        raise httpx.TimeoutException(f"fail-{calls['n']}")

    with pytest.raises(httpx.TimeoutException, match="fail-3"):
        fn()
    assert calls["n"] == 3


def test_sync_no_retry_on_non_transient():
    calls = {"n": 0}

    @sync_retry_transient
    def fn():
        calls["n"] += 1
        raise KeyError("missing")

    with pytest.raises(KeyError):
        fn()
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# TRANSIENT_EXCEPTIONS 白名单
# ---------------------------------------------------------------------------


def test_transient_exceptions_includes_httpx():
    assert httpx.TimeoutException in TRANSIENT_EXCEPTIONS
    assert httpx.ConnectError in TRANSIENT_EXCEPTIONS
    assert httpx.RemoteProtocolError in TRANSIENT_EXCEPTIONS


def test_transient_exceptions_includes_builtin():
    assert ConnectionError in TRANSIENT_EXCEPTIONS
    assert TimeoutError in TRANSIENT_EXCEPTIONS


# ---------------------------------------------------------------------------
# decorator 保留 func metadata
# ---------------------------------------------------------------------------


def test_decorator_preserves_func_name():
    @async_retry_transient
    async def my_async_func():
        pass

    @sync_retry_transient
    def my_sync_func():
        pass

    assert my_async_func.__name__ == "my_async_func"
    assert my_sync_func.__name__ == "my_sync_func"


# ---------------------------------------------------------------------------
# call_*_with_retry inline helper(不能装饰 method 时用)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_async_with_retry_helper_succeeds():
    calls = {"n": 0}

    def factory():
        calls["n"] += 1

        async def _coro():
            return "ok"

        return _coro()

    result = await call_async_with_retry(factory, func_name="inline")
    assert result == "ok"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_call_async_with_retry_helper_retries():
    calls = {"n": 0}

    def factory():
        calls["n"] += 1

        async def _coro():
            if calls["n"] < 2:
                raise httpx.ConnectError("conn refused")
            return "recovered"

        return _coro()

    result = await call_async_with_retry(factory, func_name="inline")
    assert result == "recovered"
    assert calls["n"] == 2


def test_call_sync_with_retry_helper_succeeds():
    calls = {"n": 0}

    def func():
        calls["n"] += 1
        return "ok"

    assert call_sync_with_retry(func) == "ok"
    assert calls["n"] == 1


def test_call_sync_with_retry_helper_retries():
    calls = {"n": 0}

    def func():
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("conn refused")
        return "recovered"

    assert call_sync_with_retry(func) == "recovered"
    assert calls["n"] == 2
