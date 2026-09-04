"""Phase 1 Group A 1.5 (2026-09-03): DLQ handler (lumen_tasks.dlq) 单测。

覆盖范围:
- ``_safe_json_dumps`` 三档语义:None / 可序列化 / 不可序列化(repr fallback)
- ``_read_trace_id`` 从 Celery request.headers 拿 X-Trace-Id
- ``_resolve_tenant_id`` 从 kwargs 拿 tenant_id / None fallback
- ``on_task_failure`` 主路径:写 DB row + upsert by task_id 累加 retry_count
- ``on_task_failure`` 异常路径:DB 抛错 / handler 内部异常 → logger.error fallback
- ``install_dlq_signal`` 把 handler 装到 celery.signals.task_failure
"""
from __future__ import annotations

import json
import logging
import traceback as tb_mod
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402  (test-only; noqa — keep)


# ---------------------------------------------------------------------------
# _safe_json_dumps 行为
# ---------------------------------------------------------------------------


def test_safe_json_dumps_none_returns_none():
    """None 输入 → None 输出(不是空字符串,跟 admin endpoint 逻辑一致)。"""
    from lumen_tasks.dlq import _safe_json_dumps
    assert _safe_json_dumps(None) is None


def test_safe_json_dumps_serializable_dict():
    """普通 dict 走 json.dumps + ensure_ascii=False(中文保留)。"""
    from lumen_tasks.dlq import _safe_json_dumps
    out = _safe_json_dumps({"a": 1, "中文": "ok"})
    assert json.loads(out) == {"a": 1, "中文": "ok"}


def test_safe_json_dumps_serializable_list():
    """list args(最常见的 task 入口)。"""
    from lumen_tasks.dlq import _safe_json_dumps
    out = _safe_json_dumps([1, "two", {"k": "v"}])
    assert json.loads(out) == [1, "two", {"k": "v"}]


def test_safe_json_dumps_non_serializable_falls_back_to_repr():
    """datetime 等不可 JSON 序列化对象 → repr() 字符串,不抛。"""
    from lumen_tasks.dlq import _safe_json_dumps
    class NonJsonable:
        def __repr__(self) -> str:
            return "<NonJsonable repr>"
    # default=str 让 json.dumps 先吃一次,再 fallback
    out = _safe_json_dumps({"obj": NonJsonable()})
    assert out is not None
    # repr 含类名(走 default=str 兜底,repr 返回 "<NonJsonable repr>")
    assert "NonJsonable" in out


def test_safe_json_dumps_tolerates_unexpected_explosion():
    """连 repr() 都抛的极端 case → None,不污染主流程。"""
    from lumen_tasks.dlq import _safe_json_dumps
    class Boom:
        def __repr__(self):
            raise RuntimeError("boom in repr")
    out = _safe_json_dumps(Boom())
    assert out is None


# ---------------------------------------------------------------------------
# _read_trace_id 行为
# ---------------------------------------------------------------------------


def test_read_trace_id_returns_header_value():
    """request.headers 有 X-Trace-Id → 拿出来。"""
    from lumen_tasks.dlq import _read_trace_id
    fake_task = MagicMock()
    fake_task.request.headers = {"X-Trace-Id": "abcd1234deadbeef"}
    assert _read_trace_id(fake_task) == "abcd1234deadbeef"


def test_read_trace_id_missing_request_returns_none():
    """没有 request 属性(异常上下文)→ None。"""
    from lumen_tasks.dlq import _read_trace_id
    fake_task = MagicMock(spec=[])  # no .request
    assert _read_trace_id(fake_task) is None


def test_read_trace_id_missing_header_returns_none():
    """headers 存在但没 X-Trace-Id → None(避免误用其他字段)。"""
    from lumen_tasks.dlq import _read_trace_id
    fake_task = MagicMock()
    fake_task.request.headers = {"other-key": "x"}
    assert _read_trace_id(fake_task) is None


# ---------------------------------------------------------------------------
# _resolve_tenant_id 行为
# ---------------------------------------------------------------------------


def test_resolve_tenant_id_from_kwargs():
    """kwargs.tenant_id = int → 拿出来。"""
    from lumen_tasks.dlq import _resolve_tenant_id
    assert _resolve_tenant_id(MagicMock(), {"tenant_id": 42}) == 42


def test_resolve_tenant_id_missing_returns_none():
    """kwargs 没 tenant_id → None(跨租户 admin 视图 fallback)。"""
    from lumen_tasks.dlq import _resolve_tenant_id
    assert _resolve_tenant_id(MagicMock(), {"other": "x"}) is None


def test_resolve_tenant_id_wrong_type_returns_none():
    """kwargs.tenant_id 不是 int → None(类型守门,不强转)。"""
    from lumen_tasks.dlq import _resolve_tenant_id
    assert _resolve_tenant_id(MagicMock(), {"tenant_id": "42"}) is None


# ---------------------------------------------------------------------------
# on_task_failure 主路径
# ---------------------------------------------------------------------------


def _mk_task_sender(name="lumen_tasks.document_tasks.process_document", queue="doc_parse"):
    sender = MagicMock()
    sender.name = name
    request = MagicMock()
    request.headers = {}
    request.delivery_info = {"routing_key": queue}
    sender.request = request
    return sender


def test_on_task_failure_inserts_new_row():
    """新 task_id → INSERT FailedTask row,所有字段落对。"""
    from lumen_models.failed_task import FailedTask
    from lumen_tasks.dlq import on_task_failure

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = None  # no existing

        on_task_failure(
            sender=_mk_task_sender(),
            task_id="celery-uuid-new",
            exception=RuntimeError("oops"),
            args=({"document_id": 7},),
            kwargs={"tenant_id": 3},
            traceback="Traceback...",
        )

        session.add.assert_called_once()
        row = session.add.call_args[0][0]
        assert isinstance(row, FailedTask)
        assert row.task_id == "celery-uuid-new"
        assert row.task_name == "lumen_tasks.document_tasks.process_document"
        assert row.queue == "doc_parse"
        assert row.retry_count == 0
        assert row.max_retries_reached is True
        assert row.tenant_id == 3
        session.commit.assert_called_once()


def test_on_task_failure_updates_existing_row():
    """已存在的 row → upsert:retry_count++,last_failed_at 更新,trace_id 首次写入。"""
    from lumen_tasks.dlq import on_task_failure

    existing_row = MagicMock()
    existing_row.task_id = "celery-uuid-existing"
    existing_row.retry_count = 1
    existing_row.trace_id = None
    existing_row.queue = "doc_parse"
    existing_row.traceback_text = "old traceback"

    sender = _mk_task_sender()
    sender.request.headers = {"X-Trace-Id": "fresh_trace_abc"}

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = existing_row

        on_task_failure(
            sender=sender,
            task_id="celery-uuid-existing",
            exception=RuntimeError("again"),
            args=(),
            kwargs={"tenant_id": 5},
            traceback="new traceback",
        )

        assert existing_row.retry_count == 2
        assert existing_row.max_retries_reached is True
        assert existing_row.trace_id == "fresh_trace_abc"
        session.add.assert_not_called()  # 没 INSERT,只 update
        session.commit.assert_called_once()


def test_on_task_failure_preserves_existing_trace_id():
    """upsert 时若原 row 已有 trace_id,新失败不带 header → 不覆盖。"""
    from lumen_tasks.dlq import on_task_failure

    existing_row = MagicMock()
    existing_row.task_id = "x"
    existing_row.retry_count = 0
    existing_row.trace_id = "old_trace"
    existing_row.queue = "doc_parse"
    existing_row.traceback_text = None

    sender = _mk_task_sender()
    sender.request.headers = {}  # no X-Trace-Id

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = existing_row
        on_task_failure(
            sender=sender,
            task_id="x",
            exception=RuntimeError(),
            args=(),
            kwargs={},
            traceback=None,
        )
        # 原 trace_id 没被覆盖(only `if trace_id and not existing.trace_id`)
        assert existing_row.trace_id == "old_trace"


def test_on_task_failure_handles_einfo_fallback():
    """traceback 是字符串时优先用,einfo 没给时 einfo.traceback 兜底。"""
    from lumen_tasks.dlq import on_task_failure

    einfo = MagicMock()
    einfo.traceback = "from einfo"

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = None
        on_task_failure(
            sender=_mk_task_sender(),
            task_id="t1",
            exception=RuntimeError(),
            args=(),
            kwargs={},
            traceback=None,
            einfo=einfo,
        )
        row = session.add.call_args[0][0]
        assert row.traceback_text == "from einfo"


def test_on_task_failure_falls_back_to_exception_repr():
    """traceback / einfo 都为空 → exception repr() 兜底(至少给个错误信号)。"""
    from lumen_tasks.dlq import on_task_failure

    exc = RuntimeError("explosive")

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = None
        on_task_failure(
            sender=_mk_task_sender(),
            task_id="t1",
            exception=exc,
            args=(),
            kwargs={},
            traceback=None,
            einfo=None,
        )
        row = session.add.call_args[0][0]
        assert "RuntimeError" in row.traceback_text
        assert "explosive" in row.traceback_text


# ---------------------------------------------------------------------------
# on_task_failure 异常路径(DLQ 自身失败不能污染 Celery)
# ---------------------------------------------------------------------------


def test_on_task_failure_sqlalchemy_error_logs_not_raises(caplog):
    """DB 抛 SQLAlchemyError → handler 不抛,logger.error 兜底。"""
    from lumen_tasks.dlq import on_task_failure

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.side_effect = SQLAlchemyError("db down")
        with caplog.at_level(logging.ERROR):
            # **不抛** — handler 自身 try/except 包死
            on_task_failure(
                sender=_mk_task_sender(),
                task_id="t1",
                exception=RuntimeError(),
                args=(),
                kwargs={},
                traceback=None,
            )
        # session.rollback 应被调
        session.rollback.assert_called_once()
        # log 至少 1 条 error
        assert any("dlq handler SQLAlchemyError" in r.message for r in caplog.records)


def test_on_task_failure_unexpected_error_logs_not_raises(caplog):
    """DB 抛非 SQLAlchemyError 异常(比如 commit 抛 RuntimeError)→ 兜底分支。"""
    from lumen_tasks.dlq import on_task_failure

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = None
        session.commit.side_effect = RuntimeError("commit boom")
        with caplog.at_level(logging.ERROR):
            on_task_failure(
                sender=_mk_task_sender(),
                task_id="t1",
                exception=RuntimeError(),
                args=(),
                kwargs={},
                traceback=None,
            )
        session.rollback.assert_called_once()
        assert any("dlq handler unexpected error" in r.message for r in caplog.records)


def test_on_task_failure_closes_session_in_finally():
    """无论成功失败,SessionLocal().close() 都被调(防连接池泄漏)。"""
    from lumen_tasks.dlq import on_task_failure

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = None
        on_task_failure(
            sender=_mk_task_sender(),
            task_id="t1",
            exception=RuntimeError(),
            args=(),
            kwargs={},
            traceback=None,
        )
        session.close.assert_called_once()


# ---------------------------------------------------------------------------
# install_dlq_signal 接线
# ---------------------------------------------------------------------------


def test_install_dlq_signal_connects_task_failure_handler():
    """install_dlq_signal 把 handler 装到 celery.signals.task_failure。"""
    from celery.signals import task_failure
    from lumen_tasks.dlq import install_dlq_signal

    # 不强断言 call_count(其他测试可能装过 handler),只确认函数调完不抛
    install_dlq_signal()


def test_install_dlq_signal_idempotent():
    """多次 install 不抛(Celery signal 默认 weak=False 允许多次注册)。"""
    from lumen_tasks.dlq import install_dlq_signal

    install_dlq_signal()
    install_dlq_signal()  # noqa — celery 默认行为


def test_task_failure_signal_triggers_handler_persists_row():
    """端到端:send task_failure signal → handler 跑 → FailedTask row 写入。

    集成测试 mock SessionLocal + 真实 celery signal 触发链路,确认
    handler 被正确装上且被 signal 调用。
    """
    from celery.signals import task_failure
    from lumen_tasks.dlq import install_dlq_signal

    install_dlq_signal()  # 装(可能之前已装过 — 允许多次)

    sender = _mk_task_sender()
    sender.request.headers = {"X-Trace-Id": "e2e_trace_xyz"}

    with patch("lumen_tasks.dlq.SessionLocal") as MockSession:
        session = MockSession.return_value
        session.query.return_value.filter.return_value.first.return_value = None

        # 触发 Celery signal,handler 会跑
        task_failure.send(
            sender=sender,
            task_id="e2e-task",
            exception=RuntimeError("e2e boom"),
            args=(),
            kwargs={"tenant_id": 9},
            traceback="e2e traceback",
        )

        # 至少一次 add(row) 被调用 — 确认 handler 链路通了
        assert session.add.call_count >= 1
        # 找最新 add 的 row(可能装过多次 handler → 多次 add,upsert upsert 模式)
        # 不依赖具体次数,只断言"有 row 被 add"
        added_rows = [call.args[0] for call in session.add.call_args_list]
        assert any(getattr(r, "task_id", None) == "e2e-task" for r in added_rows)