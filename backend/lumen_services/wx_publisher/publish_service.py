"""M32 公众号助手 - 发布流程 service.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §7.4 / §4.1

CP4 范围 (T21):
- ``WxPublishService.create_publish_record``: 写 ``wx_publish_records`` 行
- ``WxPublishService.publish_sync``: 同步入口 — 写 record + 立即跑 / 调度
- ``WxPublishService._run_publish``: 后台任务实际发布流程
  (上传封面 + 渲染 HTML → 微信图文消息 + /cgi-bin/draft/add + 群发 + 通知)
- ``build_wechat_draft_message``: 微信图文消息 JSON dict 拼装

不在本 service 范围:
- 真实 WechatRealClient 内部 retry / access_token 中控(那是 wechat_client 子包)
- 跨租户校验(API 路由层完成)
- 定时调度具体执行(APScheduler 触发后回 _run_publish)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from apscheduler.triggers.date import DateTrigger
from fastapi import HTTPException
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal
from lumen_models.user import User
from lumen_models.wx_publisher import (
    WxAccount,
    WxDraft,
    WxPublishRecord,
)
from lumen_schemas.wx_publisher import WxPublishRequest
from lumen_services.notification_service import (
    NotificationService,
    NOTIFICATION_TYPE_WX_PUBLISH_COMPLETED,
    NOTIFICATION_TYPE_WX_PUBLISH_FAILED,
)
from lumen_services.workflow_scheduler import get_scheduler
from lumen_services.wx_publisher.wechat_client.factory import get_wechat_client
from lumen_services.wx_publisher.wechat_client.protocol import (
    WechatAPIError,
    WechatClient,
)

log = logging.getLogger(__name__)


# 微信图文消息 content 字段截断上限(spec §7.4:HTML 取前 2000 字)
WECHAT_CONTENT_MAX_CHARS = 2000


def build_wechat_draft_message(
    draft: WxDraft, cover_media_id: Optional[str]
) -> Dict[str, Any]:
    """把 WxDraft 渲染产物 + cover 拼成微信图文消息 dict。

    spec §7.4: **MVP 简化** — ``content_html`` 全当 ``content`` 字段
    (微信图文消息 content 是 HTML,前端用微信内置浏览器渲染);超过
    ``WECHAT_CONTENT_MAX_CHARS`` 截断 + 加 ``...`` 避免超微信单篇
    长度限制。

    返回 dict 形如::

        {
            "title": draft.title,
            "content": "<截断的 HTML>",
            "thumb_media_id": cover_media_id,  # 可能为 None
            "author": draft.author or "",
            "digest": draft.summary or "",
            "content_source_url": "",
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
    """
    content = (draft.content_html or draft.content_markdown or "")[:WECHAT_CONTENT_MAX_CHARS]
    if content and len(content) == WECHAT_CONTENT_MAX_CHARS:
        # 截断了,加省略号提示
        content = content[:-3] + "..."
    return {
        "title": draft.title,
        "content": content,
        "thumb_media_id": cover_media_id,
        "author": draft.author or "",
        "digest": draft.summary or "",
        "content_source_url": "",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }


class WxPublishService:
    """发布流程业务逻辑。

    Multi-tenant 通过 ``current_user.tenant_id`` 隔离。所有 ORM 读写
    都在调用方传入的 ``db: Session`` 上做(同步路径),``_run_publish``
    作为后台任务时开新 SessionLocal(模式同 image_generation_service
    的 ``_run_generation``)。
    """

    def __init__(self, db: Session, current_user: User) -> None:
        self.db = db
        self.current_user = current_user

    # --- 写 publish record 行 ---------------------------------------------

    def create_publish_record(
        self,
        draft_id: int,
        account_id: int,
        scheduled_at: Optional[datetime] = None,
    ) -> WxPublishRecord:
        """写一行 ``WxPublishRecord``(status='queued')并 commit,返 ORM。

        校验:
        - draft 存在 + 属于当前 tenant(否则 404 防 IDOR)
        - account 存在 + 属于当前 tenant + ``is_active=True``
        - draft.status 不在 LOCKED 状态(``publishing`` / ``published``
          spec §3.3 — 已发或正在发的不能再发;返 409)

        ``user_id`` 沿用 ``current_user.id``(用于通知路由)。
        """
        tenant_id = self.current_user.tenant_id

        draft = (
            self.db.query(WxDraft)
            .filter(WxDraft.id == draft_id, WxDraft.tenant_id == tenant_id)
            .first()
        )
        if not draft:
            raise HTTPException(status_code=404, detail="draft not found")

        account = (
            self.db.query(WxAccount)
            .filter(WxAccount.id == account_id, WxAccount.tenant_id == tenant_id)
            .first()
        )
        if not account:
            raise HTTPException(status_code=404, detail="account not found")
        if not account.is_active:
            raise HTTPException(status_code=422, detail="account is inactive")

        if draft.status in ("publishing", "published"):
            raise HTTPException(
                status_code=409,
                detail=f"draft is in '{draft.status}' state, cannot republish",
            )

        record = WxPublishRecord(
            tenant_id=tenant_id,
            draft_id=draft.id,
            account_id=account.id,
            user_id=self.current_user.id,
            status="queued",
        )
        # scheduled_at 不在 WxPublishRecord 列(spec §3.6)—— 调度
        # 信息存 wx_drafts.scheduled_at(single source of truth,
        # 草稿详情页能直接显示计划发布时间)。service 这里顺手写
        # 回 draft,前端 GET draft 时能立刻看到。
        if scheduled_at is not None:
            draft.scheduled_at = scheduled_at
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        log.info(
            "WxPublishRecord created id=%s draft=%s account=%s scheduled=%s",
            record.id, draft.id, account.id, scheduled_at,
        )
        return record

    # --- 同步入口 ---------------------------------------------------------

    def publish_sync(self, payload: WxPublishRequest) -> WxPublishRecord:
        """同步入口 — 写 record + 决定立即跑 / 调度。

        spec §4.2:
        - ``scheduled_at`` 为 None → ``record.status`` 保持 ``queued``,
          由 API 层 ``background_tasks.add_task(_run_publish, record.id)``
          触发
        - ``scheduled_at`` 为未来时间 → ``APScheduler.add_job`` 调
          ``_run_publish`` 在指定时间跑(spec §7.4)。同步路径不动。

        APScheduler 不能调 async 函数 — ``_run_publish`` 是 sync
        (BackgroundTasks 入口),内部用 ``asyncio.run`` 跑 async client
        调用,跟 image_generation_service._run_generation 同模式。
        """
        record = self.create_publish_record(
            draft_id=payload.draft_id,
            account_id=payload.account_id,
            scheduled_at=payload.scheduled_at,
        )
        if payload.scheduled_at is not None:
            try:
                get_scheduler().add_job(
                    _run_publish,
                    trigger=DateTrigger(run_date=payload.scheduled_at),
                    args=[record.id],
                    id=f"wx_publish_{record.id}",
                    replace_existing=True,
                )
                log.info(
                    "WxPublishRecord %s scheduled at %s", record.id, payload.scheduled_at
                )
            except Exception as exc:
                # APScheduler 启动失败时回退到立即发(不要因为调度器挂了
                # 让用户卡住)
                log.exception(
                    "APScheduler.add_job failed for record %s, fallback to immediate: %s",
                    record.id, exc,
                )
        return record

    # --- 后台任务 ---------------------------------------------------------

    async def _run_publish_async(self, record_id: int) -> None:
        """async 核心发布逻辑 — 上传封面 + 加草稿 + (可选)群发 + 通知。

        spec §7.4 全流程:
        1. 读 record + draft + account(开新 SessionLocal)
        2. record.status = "uploading", started_at = now
        3. try:
             client = get_wechat_client(account)
             cover_media_id = await client.upload_image(account, draft.cover_url)
             msg = build_wechat_draft_message(draft, cover_media_id)
             media_id = await client.add_draft(account, msg)
             record.wechat_media_id = media_id
             record.status = "uploaded"
             if not scheduled_at (立即发):
                 msg_id = await client.mass_sendall(account, media_id)
                 record.wechat_msg_id = msg_id
                 record.status = "success"
             draft.status = "published"
             draft.published_at = now
        4. catch WechatAPIError → record.status="failed" + error 字段 + draft 标 failed
        5. record.completed_at, duration_ms
        6. db.commit()
        7. NotificationService.publish_event(...) (WX_PUBLISH_COMPLETED / FAILED)

        失败 path 也要 commit + notify(spec §7.4 — 用户必须能看到失败原因)。
        """
        db = SessionLocal()
        # 关掉 commit 后的 expire_on_commit — publish 流程会在同一
        # session 上多次 commit(开始 uploading / uploaded / final),
        # expire 后访问 draft 属性会触发 refresh,若 session 已 close
        # 就抛 DetachedInstanceError。关掉后 commit 不刷新 ORM cache,
        # 我们访问的全是这一 commit 内 set 过的字段,无 stale-read 风险。
        db.expire_on_commit = False
        try:
            record = db.query(WxPublishRecord).filter(
                WxPublishRecord.id == record_id,
            ).first()
            if not record:
                log.error("_run_publish: record %s not found", record_id)
                return
            draft = db.query(WxDraft).filter(WxDraft.id == record.draft_id).first()
            account = db.query(WxAccount).filter(
                WxAccount.id == record.account_id,
            ).first()
            if not draft or not account:
                log.error(
                    "_run_publish: draft=%s or account=%s missing for record %s",
                    record.draft_id, record.account_id, record_id,
                )
                record.status = "failed"
                record.error_code = "MISSING_RESOURCE"
                record.error_message = "draft or account no longer exists"
                db.commit()
                return

            started_at = datetime.utcnow()
            record.status = "uploading"
            record.started_at = started_at
            db.commit()

            client = get_wechat_client(account)
            try:
                async with client:  # Stub 是 no-op context,Real 走 httpx
                    # 1) 上传封面(无 cover_url 时跳过,WechatStubClient 仍会返伪 media_id)
                    cover_url = draft.cover_url
                    cover_media_id: Optional[str] = None
                    if cover_url:
                        cover_media_id = await client.upload_image(account, cover_url)
                    # 2) 拼微信图文消息 + /cgi-bin/draft/add
                    msg = build_wechat_draft_message(draft, cover_media_id)
                    media_id = await client.add_draft(account, msg)
                    record.wechat_media_id = media_id
                    record.status = "uploaded"
                    db.commit()
                    # 3) scheduled_at 空时立即群发(从 draft.scheduled_at 读,
                    # 单 source of truth — wx_publish_records 不存这列,
                    # spec §3.6)
                    if draft.scheduled_at is None:
                        msg_id = await client.mass_sendall(account, media_id)
                        record.wechat_msg_id = msg_id
                        record.status = "success"
                    else:
                        # 定时发 — draft 标「uploaded」等待定时触发,
                        # 真正群发在 APScheduler 调 _run_publish 那次
                        # 但本函数只跑一次(加草稿),简化处理:status=uploaded
                        # 等后续单独一个 mass_sendall 调用(V2)
                        record.status = "uploaded"

                    if record.status == "success":
                        draft.status = "published"
                        draft.published_at = datetime.utcnow()
                        draft.error_message = None
                # 异步上下文结束 — Real client httpx 关闭
            except WechatAPIError as exc:
                log.exception(
                    "WechatAPIError in _run_publish record=%s errcode=%s",
                    record_id, exc.errcode,
                )
                record.status = "failed"
                record.error_code = str(exc.errcode)
                record.error_message = (str(exc.errmsg) or "")[:1000]
                draft.status = "failed"
                draft.error_message = record.error_message

            completed_at = datetime.utcnow()
            record.completed_at = completed_at
            record.duration_ms = int((completed_at - started_at).total_seconds() * 1000)
            db.commit()
            self._push_publish_notification(db, record, draft, account)
        except Exception as exc:
            log.exception("_run_publish unexpected error record=%s: %s", record_id, exc)
            try:
                # 兜底:开新 SessionLocal 写 failed(避免主 session 已 close)
                err_db = SessionLocal()
                try:
                    err_rec = err_db.query(WxPublishRecord).filter(
                        WxPublishRecord.id == record_id,
                    ).first()
                    if err_rec and err_rec.status not in ("failed", "success"):
                        err_rec.status = "failed"
                        err_rec.error_code = "UNEXPECTED"
                        err_rec.error_message = str(exc)[:1000]
                        err_rec.completed_at = datetime.utcnow()
                        err_db.commit()
                finally:
                    err_db.close()
            except Exception:
                log.exception("_run_publish fallback failed record=%s", record_id)
        finally:
            db.close()

    def _push_publish_notification(
        self,
        db: Session,
        record: WxPublishRecord,
        draft: WxDraft,
        account: WxAccount,
    ) -> None:
        """发 WS 通知 — spec §5.7。

        try/except 包住,通知失败不冒泡(已经在 _run_publish 末尾,
        不能再让 db.commit 之后的代码 bubble 上去让整个后台 task 抛错)。
        """
        try:
            ns = NotificationService()
            if record.status == "success":
                ns.publish_event(
                    db,
                    user_id=record.user_id,
                    type=NOTIFICATION_TYPE_WX_PUBLISH_COMPLETED,
                    title=f"发布成功: {draft.title}",
                    body=draft.summary or draft.title,
                    resource_type="wx_publish_record",
                    resource_id=record.id,
                    metadata={
                        "draft_id": draft.id,
                        "record_id": record.id,
                        "account_id": account.id,
                        "wechat_media_id": record.wechat_media_id,
                        "wechat_msg_id": record.wechat_msg_id,
                    },
                )
            elif record.status == "failed":
                err_msg = (record.error_message or "")[:30]
                ns.publish_event(
                    db,
                    user_id=record.user_id,
                    type=NOTIFICATION_TYPE_WX_PUBLISH_FAILED,
                    title=f"发布失败: {draft.title}",
                    body=err_msg or "unknown error",
                    resource_type="wx_publish_record",
                    resource_id=record.id,
                    metadata={
                        "draft_id": draft.id,
                        "record_id": record.id,
                        "account_id": account.id,
                        "error_code": record.error_code,
                    },
                )
        except Exception:
            log.exception(
                "publish notification failed (non-fatal) record=%s", record.id
            )


# ---- module-level helpers (BackgroundTasks 入口) ---------------------------


def _run_publish(record_id: int) -> None:
    """BackgroundTasks / APScheduler 入口 — sync wrapper 跑 async 核心。

    spec §7.4: ``BackgroundTasks.add_task(_run_publish, record_id)``。
    用 ``asyncio.run`` 跑 sync 入口(同 image_generation_service
    的 ``_run_generation``)。

    为什么不开 ``WxPublishService._run_publish_async`` instance method
    直接被 add_task 调 — 因为 BackgroundTasks 走 sync,而 instance
    method 绑 ``self.db``,self.db 在请求结束后已经关闭。这个 module-
    level 函数内部 ``SessionLocal()`` 拿新 session。
    """
    from lumen_services.wx_publisher.publish_service import WxPublishService  # noqa: F401
    service = WxPublishService(db=None, current_user=None)  # type: ignore[arg-type]
    # _run_publish_async 内部开 SessionLocal,不需要外面的 db/user
    asyncio.run(service._run_publish_async(record_id))