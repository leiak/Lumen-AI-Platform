"""Phase 1 Group A 1.5 (2026-09-03): admin DLQ endpoints 单测。

覆盖范围:
- ``GET /admin/tasks/failed`` — admin-only + 三档 filter(tenant_id /
  task_name / acknowledged)+ 分页
- ``POST /admin/tasks/{id}/retry`` — celery_app.send_task 调用 + 字段
  更新(retry_count++ / last_failed_at 重写 / acknowledged_at 清)
- ``POST /admin/tasks/{id}/ack`` — acknowledged_at/acknowledged_by 写入
- 三 endpoint 都对 non-admin user 返 403
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from lumen_api.v1.admin_tasks import (
    acknowledge_failed_task,
    list_failed_tasks,
    retry_failed_task,
)
from lumen_models.failed_task import FailedTask
from lumen_models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mk_user(*, is_superuser: bool, user_id: int = 1, tenant_id: int = 1) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.tenant_id = tenant_id
    user.is_superuser = is_superuser
    return user


def _mk_db() -> MagicMock:
    """生成 mock Session,默认 query().filter().first() 返回 None。

    同时配置 query().filter().order_by() 等链式调用都返回同一个 chain
    mock(SQLAlchemy 真实行为:每个 filter() 返回新 Query,但 mock
    共享 chain 简化测试)。这样后续的 count/offset/limit/all 配置
    在任一 filter 顺序下都生效。
    """
    db = MagicMock()
    chain = MagicMock()
    chain.first.return_value = None
    db.query.return_value = chain
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.offset.return_value = chain
    chain.limit.return_value = chain
    chain.count.return_value = 0
    chain.all.return_value = []
    return db


def _mk_failed_task(
    *,
    task_id: str = "celery-uuid-1",
    task_name: str = "lumen_tasks.document_tasks.process_document",
    queue: str = "doc_parse",
    tenant_id: int = 1,
    retry_count: int = 0,
    acknowledged: bool = False,
    args: list | None = None,
    kwargs: dict | None = None,
    traceback_text: str | None = "boom",
) -> MagicMock:
    """模拟 FailedTask ORM 行(避免真 DB)。"""
    row = MagicMock(spec=FailedTask)
    row.id = 1
    row.task_id = task_id
    row.task_name = task_name
    row.queue = queue
    row.tenant_id = tenant_id
    row.retry_count = retry_count
    row.max_retries_reached = True
    row.args_json = args if args is not None else [{"document_id": 7}]
    row.kwargs_json = kwargs if kwargs is not None else {"tenant_id": tenant_id}
    row.traceback_text = traceback_text
    row.first_failed_at = datetime(2026, 9, 3, 10, 0, 0)
    row.last_failed_at = datetime(2026, 9, 3, 10, 5, 0)
    row.acknowledged_at = datetime(2026, 9, 3, 11, 0, 0) if acknowledged else None
    row.acknowledged_by = 42 if acknowledged else None
    row.trace_id = "trace_xyz"
    return row


# ---------------------------------------------------------------------------
# _require_admin 单元(抽出来便于 fast-fail 风格断言)
# ---------------------------------------------------------------------------


def test_list_requires_admin_raises_403():
    """非 admin user 调 list → HTTPException 403。"""
    db = _mk_db()
    with pytest.raises(HTTPException) as exc_info:
        # list_failed_tasks 是 async,需要 asyncio.run 触发;同步 raise 会
        # 在 await 之前(depends 中)就触发,所以直接同步调用即可。
        import asyncio
        asyncio.run(
            list_failed_tasks(
                tenant_id=None, task_name=None, acknowledged=None,
                page=1, page_size=50,
                current_user=_mk_user(is_superuser=False),
                db=db,
            )
        )
    assert exc_info.value.status_code == 403


def test_retry_requires_admin_raises_403():
    """非 admin 调 retry → 403。"""
    import asyncio
    db = _mk_db()
    db.query.return_value.filter.return_value.first.return_value = _mk_failed_task()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            retry_failed_task(
                task_id=1,
                current_user=_mk_user(is_superuser=False),
                db=db,
            )
        )
    assert exc_info.value.status_code == 403


def test_ack_requires_admin_raises_403():
    """非 admin 调 ack → 403。"""
    import asyncio
    db = _mk_db()
    db.query.return_value.filter.return_value.first.return_value = _mk_failed_task()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            acknowledge_failed_task(
                task_id=1,
                current_user=_mk_user(is_superuser=False),
                db=db,
            )
        )
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/tasks/failed — list
# ---------------------------------------------------------------------------


def test_list_no_filter_returns_all():
    """admin + 无 filter → query.count + offset/limit 调用,total/items 正确。"""
    import asyncio
    rows = [_mk_failed_task(task_id=f"t{i}") for i in range(3)]
    db = _mk_db()
    db.query.return_value.count.return_value = 3
    db.query.return_value.all.return_value = rows

    resp = asyncio.run(
        list_failed_tasks(
            tenant_id=None, task_name=None, acknowledged=None,
            page=1, page_size=50,
            current_user=_mk_user(is_superuser=True),
            db=db,
        )
    )
    assert resp.total == 3
    assert len(resp.data) == 3


def test_list_filter_by_tenant_id():
    """tenant_id filter → query.filter 被调 1 次以上,filter 表达式含 tenant_id。"""
    import asyncio
    db = _mk_db()
    db.query.return_value.count.return_value = 1
    db.query.return_value.all.return_value = [_mk_failed_task(tenant_id=42)]
    resp = asyncio.run(
        list_failed_tasks(
            tenant_id=42, task_name=None, acknowledged=None,
            page=1, page_size=50,
            current_user=_mk_user(is_superuser=True),
            db=db,
        )
    )
    # query.filter 应被调用至少 1 次(tenant_id 过滤)
    assert db.query.return_value.filter.call_count >= 1
    assert resp.total == 1


def test_list_filter_acknowledged_true():
    """acknowledged=True → filter 加 acknowledged_at IS NOT NULL。"""
    import asyncio
    db = _mk_db()
    db.query.return_value.count.return_value = 0
    asyncio.run(
        list_failed_tasks(
            tenant_id=None, task_name=None, acknowledged=True,
            page=1, page_size=50,
            current_user=_mk_user(is_superuser=True),
            db=db,
        )
    )
    # 至少 1 次 filter call(acknowledged filter)
    assert db.query.return_value.filter.call_count >= 1


def test_list_filter_acknowledged_false():
    """acknowledged=False → filter 加 acknowledged_at IS NULL。"""
    import asyncio
    db = _mk_db()
    db.query.return_value.count.return_value = 5
    db.query.return_value.all.return_value = [_mk_failed_task() for _ in range(5)]
    resp = asyncio.run(
        list_failed_tasks(
            tenant_id=None, task_name=None, acknowledged=False,
            page=1, page_size=10,
            current_user=_mk_user(is_superuser=True),
            db=db,
        )
    )
    assert resp.total == 5
    assert db.query.return_value.filter.call_count >= 1


# ---------------------------------------------------------------------------
# POST /admin/tasks/{id}/retry
# ---------------------------------------------------------------------------


def test_retry_calls_send_task_with_correct_args():
    """retry → celery_app.send_task(name, args=args, kwargs=kwargs, queue=queue) 被调。"""
    import asyncio
    db = _mk_db()
    row = _mk_failed_task(
        args=[{"document_id": 99}],
        kwargs={"tenant_id": 7},
        queue="doc_parse",
        retry_count=0,
    )
    db.query.return_value.filter.return_value.first.return_value = row

    mock_result = MagicMock()
    mock_result.id = "new-celery-uuid-zzz"

    with patch("lumen_api.v1.admin_tasks.celery_app") as mock_celery:
        mock_celery.send_task.return_value = mock_result

        resp = asyncio.run(
            retry_failed_task(
                task_id=1,
                current_user=_mk_user(is_superuser=True),
                db=db,
            )
        )

    mock_celery.send_task.assert_called_once()
    call_kwargs = mock_celery.send_task.call_args
    assert call_kwargs.args[0] == "lumen_tasks.document_tasks.process_document"
    assert call_kwargs.kwargs["queue"] == "doc_parse"
    assert call_kwargs.kwargs["args"] == ({"document_id": 99},)
    assert call_kwargs.kwargs["kwargs"] == {"tenant_id": 7}

    assert resp.data.new_task_id == "new-celery-uuid-zzz"
    assert resp.data.retry_count == 1
    assert row.retry_count == 1
    # 重派后清 ack 状态
    assert row.acknowledged_at is None
    assert row.acknowledged_by is None
    db.commit.assert_called()


def test_retry_increments_existing_retry_count():
    """retry_count 已存在 → +1。"""
    import asyncio
    db = _mk_db()
    row = _mk_failed_task(retry_count=3)
    db.query.return_value.filter.return_value.first.return_value = row

    mock_result = MagicMock()
    mock_result.id = "new-id"

    with patch("lumen_api.v1.admin_tasks.celery_app") as mock_celery:
        mock_celery.send_task.return_value = mock_result
        resp = asyncio.run(
            retry_failed_task(
                task_id=1,
                current_user=_mk_user(is_superuser=True),
                db=db,
            )
        )
    assert resp.data.retry_count == 4
    assert row.retry_count == 4


def test_retry_handles_non_list_args():
    """args_json 不是 list(异常存储)→ fallback 到空 tuple,不抛。"""
    import asyncio
    db = _mk_db()
    row = _mk_failed_task()
    row.args_json = "not-a-list"  # 异常数据
    db.query.return_value.filter.return_value.first.return_value = row

    mock_result = MagicMock()
    mock_result.id = "x"

    with patch("lumen_api.v1.admin_tasks.celery_app") as mock_celery:
        mock_celery.send_task.return_value = mock_result
        resp = asyncio.run(
            retry_failed_task(
                task_id=1,
                current_user=_mk_user(is_superuser=True),
                db=db,
            )
        )
    assert resp.data.new_task_id == "x"
    # send_task 的 args 走 fallback 空 tuple
    assert mock_celery.send_task.call_args.kwargs["args"] == ()


def test_retry_handles_non_dict_kwargs():
    """kwargs_json 不是 dict(异常存储)→ fallback 空 dict。"""
    import asyncio
    db = _mk_db()
    row = _mk_failed_task()
    row.kwargs_json = "not-a-dict"
    db.query.return_value.filter.return_value.first.return_value = row

    mock_result = MagicMock()
    mock_result.id = "y"

    with patch("lumen_api.v1.admin_tasks.celery_app") as mock_celery:
        mock_celery.send_task.return_value = mock_result
        asyncio.run(
            retry_failed_task(
                task_id=1,
                current_user=_mk_user(is_superuser=True),
                db=db,
            )
        )
    assert mock_celery.send_task.call_args.kwargs["kwargs"] == {}


def test_retry_returns_404_when_row_missing():
    """FailedTask id 不存在 → 404,不调 send_task。"""
    import asyncio
    db = _mk_db()  # 默认 first() 返 None

    with patch("lumen_api.v1.admin_tasks.celery_app") as mock_celery:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                retry_failed_task(
                    task_id=999,
                    current_user=_mk_user(is_superuser=True),
                    db=db,
                )
            )
    assert exc_info.value.status_code == 404
    mock_celery.send_task.assert_not_called()


def test_retry_returns_503_when_celery_broker_fails():
    """celery_app.send_task 抛异常(Redis broker 挂)→ 503 + Retry-After。"""
    import asyncio
    db = _mk_db()
    row = _mk_failed_task()
    db.query.return_value.filter.return_value.first.return_value = row

    with patch("lumen_api.v1.admin_tasks.celery_app") as mock_celery:
        mock_celery.send_task.side_effect = ConnectionError("redis broker down")
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                retry_failed_task(
                    task_id=1,
                    current_user=_mk_user(is_superuser=True),
                    db=db,
                )
            )
    assert exc_info.value.status_code == 503
    assert "Retry-After" in exc_info.value.headers


# ---------------------------------------------------------------------------
# POST /admin/tasks/{id}/ack
# ---------------------------------------------------------------------------


def test_ack_writes_acknowledged_at_and_by():
    """ack → acknowledged_at = NOW(approx),acknowledged_by = current_user.id。"""
    import asyncio
    db = _mk_db()
    row = _mk_failed_task()
    db.query.return_value.filter.return_value.first.return_value = row

    admin = _mk_user(is_superuser=True, user_id=42)
    resp = asyncio.run(
        acknowledge_failed_task(
            task_id=1,
            current_user=admin,
            db=db,
        )
    )
    assert resp.data.id == 1
    assert resp.data.acknowledged_by == 42
    assert resp.data.acknowledged_at is not None
    db.commit.assert_called()


def test_ack_returns_404_when_row_missing():
    """FailedTask id 不存在 → 404。"""
    import asyncio
    db = _mk_db()  # first() returns None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            acknowledge_failed_task(
                task_id=999,
                current_user=_mk_user(is_superuser=True),
                db=db,
            )
        )
    assert exc_info.value.status_code == 404