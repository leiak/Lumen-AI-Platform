"""NotificationService: write a notification row and broadcast it.

Used by Celery tasks (e.g. document processing) to notify the uploader
when a long-running job finishes. The row is written and committed
BEFORE the broadcast so that a failed broadcast still leaves a
durable record visible to the user on their next page load.
"""
from typing import Optional

from sqlalchemy.orm import Session

from lumen_models.notification import Notification
from lumen_services.electron_service import broadcast_event_sync

# Notification type constants. Use these instead of inline string literals
# so that the set of supported types is grep-able and typo-proof.
NOTIFICATION_TYPE_IMAGE_GEN_COMPLETED = "IMAGE_GENERATION_COMPLETED"
NOTIFICATION_TYPE_IMAGE_GEN_FAILED = "IMAGE_GENERATION_FAILED"

# M32 公众号助手发布(spec §5.7):
# - WX_PUBLISH_COMPLETED: 真发布成功 — BellBadge +1,点跳草稿编辑页
# - WX_PUBLISH_FAILED: 真发布失败 — BellBadge +1,带 errcode 前 30 字
# 4 个 AI 调用(WX_AI_OUTLINE_COMPLETED 等)故意不发通知(spec §5.7
# 「同步响应,前端 loading 即可」),WX_COVER_GENERATED 复用 M22 的
# IMAGE_GENERATION_COMPLETED(M22 ship 后已统一)。
NOTIFICATION_TYPE_WX_PUBLISH_COMPLETED = "WX_PUBLISH_COMPLETED"
NOTIFICATION_TYPE_WX_PUBLISH_FAILED = "WX_PUBLISH_FAILED"


class NotificationService:
    @staticmethod
    def publish_event(
        db: Session,
        *,
        user_id: int,
        type: str,
        title: str,
        body: Optional[str],
        resource_type: Optional[str],
        resource_id: Optional[int],
        metadata: dict,
    ) -> Notification:
        n = Notification(
            user_id=user_id, type=type, title=title, body=body,
            resource_type=resource_type, resource_id=resource_id,
            metadata_json=metadata,
        )
        db.add(n)
        db.commit()
        db.refresh(n)

        payload = {
            "id": n.id, "type": n.type, "title": n.title, "body": n.body,
            "resource_type": n.resource_type, "resource_id": n.resource_id,
            "metadata": n.metadata_json,
            "created_at": n.created_at.isoformat(),
        }
        broadcast_event_sync(
            event="notification_created",
            payload=payload,
            target_user_id=user_id,
        )
        return n
