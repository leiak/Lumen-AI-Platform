"""Phase 0 Unit 5 4.2 (2026-09-02):Celery trace_id signal handlers 测试。

覆盖:
- task_prerun:从 task.request.headers 读 trace_id → set ctx
- task_prerun:无 header → clear ctx(防串)
- task_postrun:清 ctx
- before_task_publish:从 ctx 拿 trace_id → 写 headers
- apply_async_with_trace 便捷包装:把当前 trace_id 写到 headers
- W3C traceparent 兼容(worker 端解析第二段)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from unittest.mock import MagicMock

import pytest

from lumen_core import tracing
from lumen_tasks.trace_signals import (
    CELERY_HEADER_KEY,
    _read_trace_id_from_task_headers,
    apply_async_with_trace,
    before_task_publish_handler,
    task_postrun_handler,
    task_prerun_handler,
)


@pytest.fixture(autouse=True)
def _reset_trace():
    tracing.reset_for_test()


# ===== _read_trace_id_from_task_headers =====


def test_read_returns_x_trace_id():
    """X-Trace-Id header → 返 trace_id。"""
    task = MagicMock()
    task.request.headers = {CELERY_HEADER_KEY: "abc123"}
    assert _read_trace_id_from_task_headers(task) == "abc123"


def test_read_falls_back_to_x_request_id():
    """没 X-Trace-Id 但有 X-Request-Id → 返 X-Request-Id。"""
    task = MagicMock()
    task.request.headers = {"X-Request-Id": "req-abc"}
    assert _read_trace_id_from_task_headers(task) == "req-abc"


def test_read_parses_traceparent():
    """W3C traceparent "00-{32hex}-{16hex}-{2hex}" → 返 trace-id 段(32 hex)。"""
    task = MagicMock()
    task.request.headers = {
        "traceparent": "00-deadbeefcafebabe1234567890abcdef-0000000000000001-01",
    }
    assert _read_trace_id_from_task_headers(task) == "deadbeefcafebabe1234567890abcdef"


def test_read_returns_none_when_no_request():
    """task 没 request 属性 → 返 None(兜底)。"""
    task = MagicMock(spec=[])  # 无 request 属性
    assert _read_trace_id_from_task_headers(task) is None


def test_read_returns_none_when_no_headers():
    """task.request.headers 是空 → 返 None。"""
    task = MagicMock()
    task.request.headers = {}
    assert _read_trace_id_from_task_headers(task) is None


# ===== task_prerun_handler =====


def test_postrun_handler_sets_trace_id_in_ctx():
    """task_prerun:从 task header 读 trace_id → set 到 ctx。"""
    task = MagicMock()
    task.request.headers = {CELERY_HEADER_KEY: "from-worker"}

    assert tracing.get_trace_id() is None
    task_prerun_handler(task_id="t1", task=task)
    assert tracing.get_trace_id() == "from-worker"


def test_postrun_handler_clears_ctx_when_no_trace_id():
    """task_prerun:task 无 trace_id → clear ctx(防串)。"""
    tracing.set_trace_id("leftover-from-prior-task")
    task = MagicMock()
    task.request.headers = {}

    task_prerun_handler(task_id="t1", task=task)
    assert tracing.get_trace_id() is None


# ===== task_postrun_handler =====


def test_task_postrun_clears_ctx():
    """task_postrun 跑完 task 后清 ctx(防下一个 task 串)。"""
    tracing.set_trace_id("active-task-tid")
    task = MagicMock()
    task_postrun_handler(task_id="t1", task=task)
    assert tracing.get_trace_id() is None


# ===== before_task_publish_handler =====


def test_publish_writes_trace_id_to_headers():
    """before_task_publish:ctx 有 trace_id → 写到 headers(就地改 dict)。"""
    tracing.set_trace_id("publishing-tid")
    headers: dict = {}
    before_task_publish_handler(sender="my_task", headers=headers, body=None)
    assert headers[CELERY_HEADER_KEY] == "publishing-tid"


def test_publish_skips_when_no_trace_id():
    """before_task_publish:ctx 无 trace_id → headers 不动。"""
    headers: dict = {}
    before_task_publish_handler(sender="my_task", headers=headers, body=None)
    assert headers == {}


def test_publish_does_not_override_existing_header():
    """producer 显式设了 X-Trace-Id → 不覆盖。"""
    tracing.set_trace_id("auto-tid")
    headers = {CELERY_HEADER_KEY: "explicit-tid"}
    before_task_publish_handler(sender="my_task", headers=headers, body=None)
    assert headers[CELERY_HEADER_KEY] == "explicit-tid"


def test_publish_handles_none_headers():
    """headers=None 兜底,不抛错。"""
    before_task_publish_handler(sender="my_task", headers=None, body=None)


# ===== apply_async_with_trace 便捷包装 =====


def test_apply_async_with_trace_injects_trace_id():
    """apply_async_with_trace 把 ctx trace_id 写到 apply_async 的 headers。"""
    tracing.set_trace_id("ctx-trace")

    fake_task = MagicMock()
    fake_task.apply_async.return_value = "result"

    result = apply_async_with_trace(fake_task, args=[1, 2], kwargs={"x": 1})

    fake_task.apply_async.assert_called_once()
    call_kwargs = fake_task.apply_async.call_args.kwargs
    assert call_kwargs["headers"][CELERY_HEADER_KEY] == "ctx-trace"
    assert call_kwargs["args"] == [1, 2]  # list 透传(Celery 接受 list / tuple)
    assert call_kwargs["kwargs"] == {"x": 1}
    assert result == "result"


def test_apply_async_with_trace_respects_explicit_headers():
    """调用方显式传 headers → 不覆盖。"""
    tracing.set_trace_id("auto-tid")
    fake_task = MagicMock()
    fake_task.apply_async.return_value = "result"

    apply_async_with_trace(
        fake_task, args=[1],
        headers={CELERY_HEADER_KEY: "explicit-tid"},
    )
    call_kwargs = fake_task.apply_async.call_args.kwargs
    assert call_kwargs["headers"][CELERY_HEADER_KEY] == "explicit-tid"


def test_apply_async_with_trace_no_trace_id_no_header():
    """ctx 无 trace_id → 不挂 header,headers 留空 dict。"""
    fake_task = MagicMock()
    fake_task.apply_async.return_value = "result"

    apply_async_with_trace(fake_task, args=[])
    call_kwargs = fake_task.apply_async.call_args.kwargs
    assert call_kwargs["headers"] == {}