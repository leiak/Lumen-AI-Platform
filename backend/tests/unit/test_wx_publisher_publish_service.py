"""WxPublishService 单元测试 (M32 T23 / CP4).

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §7.4 / §4.2

4 tests,验证发布流程核心合约:
- test_publish_sync_creates_queued_record
  ``publish_sync`` 写 record(status='queued')+ user_id/tenant_id 注入正确
- test_run_publish_async_stub_path_sets_success
  mock WechatStubClient,_run_publish_async 走完整流程 → record.status='success'
  + draft.status='published' + WX_PUBLISH_COMPLETED 通知发出
- test_run_publish_async_wechat_api_error_sets_failed
  mock client 抛 WechatAPIError → record.status='failed' + error 字段 +
  draft.status='failed' + WX_PUBLISH_FAILED 通知发出
- test_scheduled_at_triggers_apscheduler
  publish_sync with scheduled_at 未来 → APScheduler.add_job 被调
  (用 monkeypatch 替换 ``get_scheduler``,验证 add_job 调用)

不在范围:
- 真实 BackgroundTasks 异步调度(用 monkeypatch _run_publish)
- 真实 httpx 调用 WechatRealClient(integration test 范围)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from apscheduler.triggers.date import DateTrigger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_models import (  # noqa: F401
    agent as _agent,
    image_generation as _image_generation,
    knowledge as _knowledge,
    model_config as _model_config,
    user as _user_model,
)
from lumen_models.wx_publisher import WxAccount, WxDraft, WxPublishRecord
from lumen_schemas.wx_publisher import WxPublishRequest
from lumen_services.notification_service import (
    NOTIFICATION_TYPE_WX_PUBLISH_COMPLETED,
    NOTIFICATION_TYPE_WX_PUBLISH_FAILED,
)
from lumen_services.wx_publisher.publish_service import (
    WxPublishService,
    build_wechat_draft_message,
)
from lumen_services.wx_publisher.wechat_client.protocol import WechatAPIError

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_account,
    make_draft,
    make_publish_record,
    make_tenant,
    make_user,
)


# ---- fixtures ---------------------------------------------------------------


@pytest.fixture
def db_session():
    db = fresh_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def track_user_ids():
    return []


@pytest.fixture
def track_tenant_ids():
    return []


@pytest.fixture
def track_account_ids():
    return []


@pytest.fixture
def track_draft_ids():
    return []


@pytest.fixture
def track_record_ids():
    return []


@pytest.fixture
def cleanup_rows(
    track_user_ids, track_tenant_ids, track_account_ids,
    track_draft_ids, track_record_ids,
):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        account_ids=track_account_ids, draft_ids=track_draft_ids,
        record_ids=track_record_ids,
    )


# ---- tests ------------------------------------------------------------------


def test_publish_sync_creates_queued_record(
    db_session, cleanup_rows, track_user_ids, track_tenant_ids,
    track_account_ids, track_draft_ids, track_record_ids,
):
    """publish_sync 写 record(status='queued') + user_id/tenant_id 注入。"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    service = WxPublishService(db_session, user)
    payload = WxPublishRequest(draft_id=draft.id, account_id=account.id)
    record = service.publish_sync(payload)
    track_record_ids.append(record.id)

    assert record.id is not None
    assert record.status == "queued"
    assert record.tenant_id == tenant.id
    assert record.user_id == user.id
    assert record.draft_id == draft.id
    assert record.account_id == account.id
    # scheduled_at 不存在 record 列(spec §3.6)—— 写回 draft.scheduled_at
    # (None, 立即发;future, 定时发)
    assert draft.scheduled_at is None
    # 同步落库 — 重新 query 能拿到
    refreshed = db_session.query(WxPublishRecord).filter(
        WxPublishRecord.id == record.id
    ).first()
    assert refreshed is not None
    assert refreshed.status == "queued"


def test_run_publish_async_stub_path_sets_success(
    db_session, cleanup_rows, track_user_ids, track_tenant_ids,
    track_account_ids, track_draft_ids, track_record_ids,
):
    """Stub path: _run_publish_async 走完 → status=success + draft.published +
    WX_PUBLISH_COMPLETED 通知发出。
    """
    import asyncio
    from unittest.mock import AsyncMock

    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    user_id = user.id  # 存 ID 后 close session,避免 lazy-load detach
    track_user_ids.append(user_id)
    account = make_account(
        db_session, tenant_id=tenant.id, user_id=user_id, is_mock=True,
    )
    track_account_ids.append(account.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user_id,
        content_markdown="hello", status="ready",
    )
    draft.content_html = "<p>hello</p>"
    draft.cover_url = "https://example.test/cover.jpg"
    db_session.commit()
    draft_id = draft.id
    track_draft_ids.append(draft_id)

    record = make_publish_record(
        db_session, tenant_id=tenant.id, draft_id=draft_id,
        account_id=account.id, user_id=user_id, status="queued",
    )
    record_id = record.id
    track_record_ids.append(record_id)
    db_session.close()  # 关闭主 session,避免 ORM identity 缓存旧数据

    # 用 AsyncMock 替代 stub(避免触发真实 stub 跨 event loop 副作用)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get_access_token = AsyncMock(return_value="mock_token")
    mock_client.upload_image = AsyncMock(return_value="mock_cover_media_id")
    mock_client.add_draft = AsyncMock(return_value="mock_draft_media_id_xyz")
    mock_client.mass_sendall = AsyncMock(return_value="mock_msg_id_abc")

    with patch(
        "lumen_services.wx_publisher.publish_service.get_wechat_client",
        return_value=mock_client,
    ), patch(
        "lumen_services.wx_publisher.publish_service.NotificationService"
    ) as MockNS:
        ns_instance = MagicMock()
        MockNS.return_value = ns_instance

        service = WxPublishService(db_session, user)
        asyncio.run(service._run_publish_async(record_id))

    # 用新 session 验证 record 终态(主 session 在 publish 后已 close,
    # 且 _run_publish_async 内部用 SessionLocal 提交,跨 connection
    # 在 InnoDB 默认 REPEATABLE READ 不可见 — 必须新 session)
    verify_db = fresh_session()
    try:
        final = verify_db.query(WxPublishRecord).filter(
            WxPublishRecord.id == record_id
        ).first()
        assert final is not None
        # eager-load 字段(在 verify_db close 之前)
        final_status = final.status
        final_wechat_media_id = final.wechat_media_id
        final_wechat_msg_id = final.wechat_msg_id
        final_started_at = final.started_at
        final_completed_at = final.completed_at
        final_duration_ms = final.duration_ms
        final_error_code = final.error_code
        final_error_message = final.error_message
        assert final_status == "success"
        assert final_wechat_media_id is not None
        assert final_wechat_media_id.startswith("mock_draft_media_id_")
        assert final_wechat_msg_id is not None
        assert final_wechat_msg_id.startswith("mock_msg_id_")
        assert final_started_at is not None
        assert final_completed_at is not None
        assert final_duration_ms is not None and final_duration_ms >= 0
        assert final_error_code is None
        assert final_error_message is None

        # 验证 draft 终态
        final_draft = verify_db.query(WxDraft).filter(WxDraft.id == draft_id).first()
        # eager-load 字段(在 verify_db close 之前)
        final_draft_status = final_draft.status
        final_draft_published_at = final_draft.published_at
        assert final_draft_status == "published"
        assert final_draft_published_at is not None
    finally:
        verify_db.close()

    # 验证通知被发
    ns_instance.publish_event.assert_called_once()
    call_kwargs = ns_instance.publish_event.call_args.kwargs
    assert call_kwargs["type"] == NOTIFICATION_TYPE_WX_PUBLISH_COMPLETED
    assert call_kwargs["user_id"] == user_id


def test_run_publish_async_wechat_api_error_sets_failed(
    db_session, cleanup_rows, track_user_ids, track_tenant_ids,
    track_account_ids, track_draft_ids, track_record_ids,
):
    """Failure path: client 抛 WechatAPIError → record=failed + draft=failed
    + WX_PUBLISH_FAILED 通知发出。
    """
    import asyncio

    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    user_id = user.id  # 存 ID 防止 close 后 lazy-load detach
    track_user_ids.append(user_id)
    account = make_account(
        db_session, tenant_id=tenant.id, user_id=user_id, is_mock=True,
    )
    track_account_ids.append(account.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user_id,
        content_markdown="hello", status="ready",
    )
    draft.content_html = "<p>hello</p>"
    draft.cover_url = "https://example.test/cover.jpg"
    db_session.commit()
    draft_id = draft.id
    track_draft_ids.append(draft_id)

    record = make_publish_record(
        db_session, tenant_id=tenant.id, draft_id=draft_id,
        account_id=account.id, user_id=user_id, status="queued",
    )
    record_id = record.id
    track_record_ids.append(record_id)
    db_session.close()  # 关闭主 session,避免 ORM cache

    # 替换 factory 返 mock client,add_draft 抛 WechatAPIError
    # ``async with client:`` 会调 __aenter__/__aexit__,必须是 awaitable。
    # 用 AsyncMock 让 __aenter__/__aexit__ 自动返 awaitable。
    from unittest.mock import AsyncMock

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get_access_token = AsyncMock(return_value="mock_token")
    mock_client.upload_image = AsyncMock(return_value="mock_cover_media_id")
    mock_client.add_draft = AsyncMock(
        side_effect=WechatAPIError(errcode=40001, errmsg="invalid credential")
    )

    with patch(
        "lumen_services.wx_publisher.publish_service.get_wechat_client",
        return_value=mock_client,
    ), patch(
        "lumen_services.wx_publisher.publish_service.NotificationService"
    ) as MockNS:
        ns_instance = MagicMock()
        MockNS.return_value = ns_instance

        service = WxPublishService(db_session, user)
        asyncio.run(service._run_publish_async(record_id))

    # 新 session 验证终态(跨 connection,REPEATABLE READ 看不见)
    verify_db = fresh_session()
    try:
        final = verify_db.query(WxPublishRecord).filter(
            WxPublishRecord.id == record_id
        ).first()
        assert final is not None
        # eager-load 字段
        final_status = final.status
        final_error_code = final.error_code
        final_error_message = final.error_message
        final_completed_at = final.completed_at
        final_duration_ms = final.duration_ms
        assert final_status == "failed"
        assert final_error_code == "40001"
        assert "invalid credential" in (final_error_message or "")
        assert final_completed_at is not None
        assert final_duration_ms is not None and final_duration_ms >= 0

        final_draft = verify_db.query(WxDraft).filter(WxDraft.id == draft_id).first()
        # eager-load 字段(在 verify_db close 之前),避免 detach 后 lazy load 抛
        final_draft_status = final_draft.status
        final_draft_error_msg = final_draft.error_message
        assert final_draft_status == "failed"
        assert final_draft_error_msg is not None
    finally:
        verify_db.close()

    ns_instance.publish_event.assert_called_once()
    call_kwargs = ns_instance.publish_event.call_args.kwargs
    assert call_kwargs["type"] == NOTIFICATION_TYPE_WX_PUBLISH_FAILED
    assert call_kwargs["user_id"] == user_id


def test_scheduled_at_triggers_apscheduler(
    db_session, cleanup_rows, track_user_ids, track_tenant_ids,
    track_account_ids, track_draft_ids, track_record_ids,
):
    """scheduled_at 未来时间 → APScheduler.add_job 被调,BackgroundTasks 不该跑。"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    future = datetime.utcnow() + timedelta(hours=1)

    service = WxPublishService(db_session, user)
    payload = WxPublishRequest(
        draft_id=draft.id, account_id=account.id, scheduled_at=future,
    )

    # 替换 get_scheduler 返 mock scheduler
    with patch(
        "lumen_services.wx_publisher.publish_service.get_scheduler"
    ) as mock_get_scheduler:
        mock_sched = MagicMock()
        mock_get_scheduler.return_value = mock_sched

        record = service.publish_sync(payload)
        track_record_ids.append(record.id)

    # add_job 应被调,带 record.id 作为参数
    mock_sched.add_job.assert_called_once()
    call_args = mock_sched.add_job.call_args
    # APScheduler.add_job 的 positional: (func, trigger, args, ...)
    # 我们 service 里调法:get_scheduler().add_job(_run_publish,
    #   trigger=DateTrigger(...), args=[record.id], ...)
    # 所以 record.id 在 kwargs['args'][0]
    assert call_args.kwargs.get("args") == [record.id], (
        f"kwargs['args']={call_args.kwargs.get('args')}, expected [{record.id}]"
    )
    # 触发器是 DateTrigger
    assert isinstance(call_args.kwargs.get("trigger"), DateTrigger)