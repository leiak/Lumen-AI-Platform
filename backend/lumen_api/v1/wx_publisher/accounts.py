"""M32 公众号助手 - 账号管理 HTTP endpoints.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1 / §4.2

CP1 范围: 6 个 endpoint
- GET    /                          分页列表
- POST   /                          创建账号
- GET    /{account_id}              详情
- PUT    /{account_id}              更新元数据 (name / is_active / ip_whitelist / is_mock)
- DELETE /{account_id}              软删 (is_active=False)
- POST   /{account_id}/verify       校验 AppID/AppSecret

Cross-tenant 隔离由 ``WxAccountService.get_account`` 内部完成:
它对另一租户的 row 返 404 (而非 403),防止 IDOR 信息泄露。

注册位置: ``backend/app/api/v1/__init__.py`` 顶层 — 这是 T13
(另一个 subagent 跑) 的责任。本文件 self-contained 可独立 import。
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user, require_admin
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_models.wx_publisher import WxAccount
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.wx_publisher import (
    WxAccountCreate,
    WxAccountDetail,
    WxAccountPurgeResponse,
    WxAccountResponse,
    WxAccountUpdate,
    WxAccountVerifyRequest,
    WxAccountVerifyResponse,
)
from lumen_services.wx_publisher.account_service import (
    WxAccountService,
    mask_app_secret,
)

log = logging.getLogger(__name__)

# Prefix matches spec §4.1 exactly. The trailing ``/accounts`` lets
# the T13 wiring add a single ``include_router`` call at
# ``/api/v1/wx-publisher`` (with sibling routers for templates,
# drafts, materials, publish).
router = APIRouter(prefix="/wx-publisher/accounts", tags=["wx-publisher"])

# Module-level service instance (M22 / M28 / M14 / M21 all do this
# pattern — services are stateless wrappers so a singleton is safe).
service = WxAccountService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(row: WxAccount) -> WxAccountResponse:
    """Build a list-item shape from an ORM row. AppSecret is masked
    via the service's module-level helper.
    """
    # Decrypt-then-mask. We re-decrypt every list response which is
    # O(small) per row — fine at MVP scale, V2 can cache plaintext
    # in-process if list latency becomes an issue.
    try:
        plain = service.decrypt_app_secret(row.app_secret_encrypted)
    except Exception as e:
        # If decrypt fails (key rotated, row tampered) we still
        # surface a list entry — with a sentinel mask. Operator
        # can re-create the account.
        log.warning("decrypt failed for account %s: %s", row.id, e)
        plain = "??"
    return WxAccountResponse(
        id=row.id,
        name=row.name,
        app_id=row.app_id,
        app_secret_masked=mask_app_secret(plain),
        account_type=row.account_type,
        is_mock=row.is_mock,
        is_active=row.is_active,
        last_verified_at=row.last_verified_at,
        created_at=row.created_at,
    )


def _to_detail(row: WxAccount) -> WxAccountDetail:
    """Build the detail shape — same as list item + 2 extra fields."""
    base = _to_response(row)
    return WxAccountDetail(
        **base.model_dump(),
        access_token_expires_at=row.access_token_expires_at,
        ip_whitelist=_parse_ip_whitelist(row.ip_whitelist),
    )


def _parse_ip_whitelist(text: Optional[str]) -> Optional[List[str]]:
    """Parse the JSON-encoded TEXT column back into a list. Returns
    ``None`` for empty rows so the API consumer sees a clean null
    instead of ``[]`` (semantically different: empty list is a
    *configured empty whitelist*; null is *unconfigured*).
    """
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError) as e:
        log.warning("ip_whitelist parse failed: %s — returning None", e)
        return None
    if not isinstance(parsed, list):
        return None
    return [str(x) for x in parsed]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[WxAccountResponse])
def list_accounts(
    page: int = 1,
    page_size: int = 20,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页列出当前租户的公众号账号。可选 ``is_active`` 过滤。"""
    rows, total = service.list_accounts(
        db, current_user=current_user,
        page=page, page_size=page_size, is_active=is_active,
    )
    return PaginatedResponse(
        data=[_to_response(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[WxAccountResponse], status_code=201)
def create_account(
    data: WxAccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建公众号账号。AppSecret 入参即加密 — 响应只返 masked 版本。

    注意: AppSecret 在响应中**永不**出现。前端需要在创建成功后弹
    一次性显示 Modal(spec §5.6),但因为我们不在响应里返明文,
    V2 流程是后端先把明文缓存在 session/内存,前端用一次性 token
    调 ``GET /accounts/{id}/secret-reveal`` 拉一次。M21 的实现
    走的是先返明文再客户端立即丢弃。MVP 阶段不返明文,operator
    必须在创建时自己记下来。
    """
    try:
        row = service.create_account(db, current_user=current_user, payload=data)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("create_account: unexpected error")
        raise HTTPException(500, f"Failed to create account: {e}")
    return SingleResponse(data=_to_response(row))


@router.get("/{account_id}", response_model=SingleResponse[WxAccountDetail])
def get_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """账号详情。"""
    row = service.get_account(db, current_user=current_user, account_id=account_id)
    return SingleResponse(data=_to_detail(row))


@router.put("/{account_id}", response_model=SingleResponse[WxAccountResponse])
def update_account(
    account_id: int,
    data: WxAccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新账号元数据。AppID / AppSecret 不可在此接口修改
    (V2 提供专门的 rotate 端点)。
    """
    row = service.update_account(
        db, current_user=current_user,
        account_id=account_id, payload=data,
    )
    return SingleResponse(data=_to_response(row))


@router.delete("/{account_id}", status_code=204)
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """软删账号 (``is_active=False``)。审计记录 (``wx_publish_records``)
    通过 ON DELETE RESTRICT 保留 — 即使账号被禁用,发布历史仍
    完整可查。
    """
    service.delete_account(db, current_user=current_user, account_id=account_id)
    return None  # 204 No Content


@router.post(
    "/{account_id}/verify",
    response_model=SingleResponse[WxAccountVerifyResponse],
)
def verify_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """校验 AppID/AppSecret 是否有效。

    Mock 账号: 跳过网络调用,直接 mark ``last_verified_at = now()``。
    真实账号: 调 Wechat API 拉新 access_token (T20 实现)。
    T20 之前真实账号会返 501 (NotImplementedError 在 service 层捕获)。
    """
    result = service.verify_account(
        db, current_user=current_user, account_id=account_id,
    )
    return SingleResponse(data=WxAccountVerifyResponse(**result))


@router.post(
    "/{account_id}/purge",
    response_model=SingleResponse[WxAccountPurgeResponse],
)
def purge_account(
    account_id: int,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Admin-only hard delete — bypasses the spec §3.6 audit-trail guard.

    Differences from ``DELETE /accounts/{id}`` (soft delete):

    - ``DELETE`` flips ``is_active=False`` and keeps the row. This is
      the default behavior; ``wx_publish_records`` keep their FK target.
    - This endpoint cascades through and **destroys** the audit trail:
      every ``wx_publish_records`` row pointing at the account is
      deleted, ``wx_drafts.account_id`` is auto-nulled via FK SET NULL,
      and the ``wx_accounts`` row itself is hard-deleted.

    Use only when the operator has explicitly decided to break the
    audit chain (e.g. cleaning up a long-disabled mock account that
    never had any real publishes). Non-admin callers get 403 via
    ``require_admin``.
    """
    result = service.purge_account(
        db, admin_user=admin_user, account_id=account_id,
    )
    return SingleResponse(data=WxAccountPurgeResponse(**result))
