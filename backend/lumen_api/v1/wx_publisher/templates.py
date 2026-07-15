"""M32 公众号助手 - 排版模板 HTTP endpoints.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1

CP2 范围: 6 个 endpoint
- GET    /                        分页列表 (page/page_size/category/is_system)
- POST   /                        创建模板
- GET    /{template_id}            详情
- PUT    /{template_id}            更新 (系统模板 403)
- DELETE /{template_id}            删除 (系统模板 403, usage_count>0 422)
- GET    /{template_id}/thumbnail  缩略图 bytes (ETag 304)

Cross-tenant 隔离由 ``WxTemplateService.get_template`` 内部完成:
它对另一租户的 row 返 404 (而非 403),防止 IDOR 信息泄露。

注册位置: ``backend/app/api/v1/__init__.py`` 顶层 — 这是 T13
(另一个 subagent 跑) 的责任。本文件 self-contained 可独立 import。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_models.wx_publisher import WxTemplate
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.wx_publisher import (
    WxTemplateCreate,
    WxTemplateDetail,
    WxTemplateListItem,
    WxTemplateResponse,
    WxTemplateUpdate,
)
from lumen_services.wx_publisher.template_service import WxTemplateService

log = logging.getLogger(__name__)

# Prefix matches spec §4.1 exactly. The trailing ``/templates`` lets
# the T13 wiring add a single ``include_router`` call at
# ``/api/v1/wx-publisher`` (with sibling routers for accounts, drafts,
# materials, publish).
router = APIRouter(prefix="/wx-publisher/templates", tags=["wx-publisher"])

# Module-level service instance (M22 / M28 / M14 / M21 / accounts
# all do this pattern — services are stateless wrappers so a
# singleton is safe).
service = WxTemplateService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_list_item(row: WxTemplate) -> WxTemplateListItem:
    """Build a list-item shape from an ORM row.

    ``has_thumbnail`` is a cheap boolean (``thumbnail is not None``)
    so the UI can render a placeholder for templates without a
    generated preview image without paying the byte-decode cost.
    """
    return WxTemplateListItem(
        id=row.id,  # type: ignore[arg-type]
        name=row.name,
        category=row.category,
        description=row.description,
        is_system=row.is_system,
        usage_count=row.usage_count or 0,  # type: ignore[arg-type]
        has_thumbnail=row.thumbnail is not None,
        created_at=row.created_at,
    )


def _to_detail(row: WxTemplate) -> WxTemplateDetail:
    """Build the detail shape — list item + full HTML/CSS payload.

    ``thumbnail_size`` is the byte size of the JPEG blob, useful for
    the UI to decide whether to show "preview ready" or a spinner.
    """
    base = _to_list_item(row)
    return WxTemplateDetail(
        **base.model_dump(),
        html_body=row.html_body,
        css_variables=row.css_variables or {},  # type: ignore[arg-type]
        preview_html=row.preview_html,
        thumbnail_size=len(row.thumbnail) if row.thumbnail else None,  # type: ignore[arg-type]
        created_by=row.created_by,  # type: ignore[arg-type]
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[WxTemplateListItem])
def list_templates(
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    is_system: bool | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页列出当前租户的模板。可选 ``category`` / ``is_system`` 过滤。

    Order: 系统模板优先,其次 usage_count DESC,最后 recency(由 service 层保证)。
    """
    rows, total = service.list_templates(
        db, current_user=current_user,
        page=page, page_size=page_size,
        category=category, is_system=is_system,
    )
    return PaginatedResponse(
        data=[_to_list_item(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[WxTemplateResponse], status_code=201)
def create_template(
    data: WxTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建模板。

    ``is_system=True`` 仅 superuser 有效;非 superuser 客户端传
    ``is_system=True`` 会被 service 静默降级为 False(不让客户端提权)。
    """
    try:
        row = service.create_template(
            db, current_user=current_user, payload=data,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("create_template: unexpected error")
        raise HTTPException(500, f"Failed to create template: {e}")
    return SingleResponse(data=_to_list_item(row))


@router.get("/{template_id}", response_model=SingleResponse[WxTemplateDetail])
def get_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """模板详情(含完整 HTML/CSS payload)。"""
    row = service.get_template(
        db, current_user=current_user, template_id=template_id,
    )
    return SingleResponse(data=_to_detail(row))


@router.put("/{template_id}", response_model=SingleResponse[WxTemplateResponse])
def update_template(
    template_id: int,
    data: WxTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新模板元数据/HTML/CSS variables。系统模板(``is_system=True``)
    不可编辑 — service 层返 403。"""
    try:
        row = service.update_template(
            db, current_user=current_user,
            template_id=template_id, payload=data,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("update_template: unexpected error")
        raise HTTPException(500, f"Failed to update template: {e}")
    return SingleResponse(data=_to_list_item(row))


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除模板。系统模板 403,``usage_count>0`` 422(防误删已被草稿引用的模板)。"""
    try:
        service.delete_template(
            db, current_user=current_user, template_id=template_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("delete_template: unexpected error")
        raise HTTPException(500, f"Failed to delete template: {e}")
    return Response(status_code=204)


@router.post(
    "/{template_id}/generate-thumbnail",
    response_model=SingleResponse[WxTemplateDetail],
)
def generate_template_thumbnail(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用 image-generation API 自动生成模板缩略图 (M32.1)。

    同步等待 (max 60s): 调租户内第一个 ``is_image_generation=True`` 的
    ModelConfig, 用模板 name + category + description 拼英文 prompt,
    创建 generated_images 行, busy-poll 等 status=completed, 读 file
    → 写 template.thumbnail.

    Returns:
        更新后的模板详情 (thumbnail 已写入, has_thumbnail=True).

    Raises:
        404 — 模板不存在或跨租户
        422 — 租户没有可用的 image-gen 模型
        500 — image-gen 任务失败 / 文件丢失
        504 — 60s 超时
    """
    try:
        row = service.generate_thumbnail_inline(
            db, current_user=current_user, template_id=template_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("generate_template_thumbnail: unexpected error")
        raise HTTPException(500, f"Generate thumbnail failed: {e}")
    return SingleResponse(data=_to_detail(row))


@router.get("/{template_id}/thumbnail")
def get_template_thumbnail(
    template_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """缩略图 bytes(``image/jpeg``) + ETag 304 支持。

    模式同 M22 image-generation 的缩略图:基于 thumbnail 字节的 SHA-256
    算 weak ETag(``W/"<hash>"``)。客户端传 ``If-None-Match`` 命中时
    返 304(不返 body),省传输。缩略图缺失返 404(而不是空 200)。
    """
    try:
        etag = service.get_thumbnail_etag(
            db, current_user=current_user, template_id=template_id,
        )
    except HTTPException:
        raise
    if etag is None:
        raise HTTPException(404, "Thumbnail not available")

    # ETag 304 — match RFC 7232: client sends ``If-None-Match: W/"..."``,
    # server responds 304 with no body. We compare loosely (ignore W/
    # vs strong distinction) so clients using either flavor work.
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and etag in if_none_match:
        return Response(status_code=304, headers={"ETag": etag})

    # Full path: stream the bytes.
    blob = service.get_thumbnail_bytes(
        db, current_user=current_user, template_id=template_id,
    )
    if blob is None:
        # Race: row had ETag (computed from a thumbnail) but the
        # blob vanished between calls. Same 404 — UI will refetch.
        raise HTTPException(404, "Thumbnail not available")
    return Response(
        content=blob,
        media_type="image/jpeg",
        headers={"ETag": etag, "Cache-Control": "private, max-age=300"},
    )
