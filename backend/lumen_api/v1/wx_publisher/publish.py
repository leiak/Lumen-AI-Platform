"""M32 公众号助手 - 发布 HTTP endpoints.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1 / §4.2

CP4 范围 (T22) — 共 2 个 endpoint:
- POST /                    发起发布(202 Accepted,后台任务 + WS 通知)
- GET  /{record_id}         查发布记录详情

BackgroundTasks 不能直接 await async 函数(spec 提示)—— 用
``background_tasks.add_task(_run_publish, record.id)``,``_run_publish``
是 sync wrapper 内部 ``asyncio.run`` 跑 async 核心。

跨租户 IDOR 防 404(由 WxPublishService.create_publish_record 内部
抛 HTTPException(404))。

注册位置: ``backend/app/api/v1/__init__.py`` 顶层 - 在 4 个已注册
的 wx_publisher router 之后追加 ``publish.router``。
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_models.wx_publisher import WxPublishRecord
from lumen_schemas.common import SingleResponse
from lumen_schemas.wx_publisher import (
    WxPublishRecordResponse,
    WxPublishRequest,
)
from lumen_services.wx_publisher.publish_service import (
    WxPublishService,
    _run_publish,
)

log = logging.getLogger(__name__)


router = APIRouter(prefix="/wx-publisher/publish", tags=["wx-publisher"])


@router.post("/", response_model=SingleResponse[WxPublishRecordResponse], status_code=202)
async def create_publish(
    payload: WxPublishRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> SingleResponse[WxPublishRecordResponse]:
    """POST /api/v1/wx-publisher/publish/ — 发起发布。

    spec §4.2:
    - body: ``{draft_id, account_id, scheduled_at?}``
    - 返 202 Accepted + ``SingleResponse<WxPublishRecordResponse>``
    - ``scheduled_at`` 为 None 时:BackgroundTasks 立即跑 ``_run_publish``;
      跑完写 wx_publish_records + 发 WS 通知(WX_PUBLISH_COMPLETED / FAILED)
    - ``scheduled_at`` 为未来时间:APScheduler.add_job(在 service.publish_sync 内),
      此 endpoint 不调度 BackgroundTasks,返 202 让前端 polling
      ``GET /publish/{id}`` 看状态
    """
    service = WxPublishService(db, current_user)
    record = service.publish_sync(payload)
    # 只在「立即发」路径调 BackgroundTasks(scheduled_at 走 APScheduler,
    # service 内已 add_job)
    if payload.scheduled_at is None:
        background_tasks.add_task(_run_publish, record.id)
    return SingleResponse(data=WxPublishRecordResponse.model_validate(record))


@router.get("/{record_id}", response_model=SingleResponse[WxPublishRecordResponse])
async def get_publish(
    record_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> SingleResponse[WxPublishRecordResponse]:
    """GET /api/v1/wx-publisher/publish/{id} — 查发布记录详情。

    跨租户 IDOR 一律返 404(防信息泄露)。返回完整 WxPublishRecordResponse
    (含 error_code / error_message / wechat_msg_id)。
    """
    record = (
        db.query(WxPublishRecord)
        .filter(
            WxPublishRecord.id == record_id,
            WxPublishRecord.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="publish record not found")
    return SingleResponse(data=WxPublishRecordResponse.model_validate(record))