"""M32 公众号助手 - 草稿管理 HTTP endpoints.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1 / §4.2

CP2 范围 (T10) — 共 9 个 endpoint,只做 CRUD + sections:
- GET    /                          分页列表 + status / template / account / title 过滤
- POST   /                          创建草稿(201)
- GET    /{draft_id}                详情(含 sections list)
- PUT    /{draft_id}                更新元数据(title / content / 可选字段)
- DELETE /{draft_id}                hard delete(走 ON DELETE CASCADE 清 sections)
- POST   /{draft_id}/sections       追加章节
- PUT    /{draft_id}/sections/{sid} 更新章节
- DELETE /{draft_id}/sections/{sid} 删除章节
- POST   /{draft_id}/sections/reorder  重排章节

CP3 范围 (T17) — 追加 5 个 AI/render endpoint:
- POST   /{draft_id}/ai/outline     AI 大纲生成(spec §4.2)
- POST   /{draft_id}/ai/rewrite     AI 改写 section
- POST   /{draft_id}/ai/expand      AI 扩写 section
- POST   /{draft_id}/ai/title       AI 标题候选
- POST   /{draft_id}/render         应用模板渲染 Markdown → HTML

不在本文件范围(留给 V2):
- POST /drafts/{id}/cover (M22 ImageGenerationService + WS,本阶段 MVP 跳过)

跨租户隔离由 ``WxDraftService.get_draft`` 内部完成:对另一租户的
row 返 404(NOT 403),防 IDOR 信息泄露。

注册位置: ``backend/app/api/v1/__init__.py`` 顶层 — 这是 T13
(另一个 subagent 跑) 的责任。本文件 self-contained 可独立 import。
"""
from __future__ import annotations

import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_core.llm_call_context import get_call_context
from lumen_models.user import User
from lumen_models.wx_publisher import WxDraft, WxDraftSection
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.wx_publisher import (
    WxAIExpandRequest,
    WxAIExpandResponse,
    WxAIOutlineRequest,
    WxAIOutlineResponse,
    WxAIRewriteRequest,
    WxAIRewriteResponse,
    WxAITitleRequest,
    WxAITitleResponse,
    WxDraftCreate,
    WxDraftDetail,
    WxDraftListItem,
    WxDraftPasteHtmlRequest,
    WxDraftResponse,
    WxDraftSectionCreate,
    WxDraftSectionReorderRequest,
    WxDraftSectionResponse,
    WxDraftSectionUpdate,
    WxDraftUpdate,
    WxRenderRequest,
    WxRenderResponse,
)
from lumen_services.wx_publisher.draft_service import (
    LOCKED_STATUSES_FOR_EDIT,
    WxDraftService,
)

log = logging.getLogger(__name__)

# Prefix matches spec §4.1 exactly. The trailing ``/drafts`` lets the
# T13 wiring add a single ``include_router`` call at ``/api/v1/wx-publisher``.
router = APIRouter(prefix="/wx-publisher/drafts", tags=["wx-publisher"])

# Module-level service instance (M22 / M28 / M14 / M21 all do this
# pattern — services are stateless wrappers so a singleton is safe).
service = WxDraftService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_list_item(row: WxDraft) -> WxDraftListItem:
    """Build the list-item shape from an ORM row."""
    return WxDraftListItem(
        id=row.id,
        title=row.title,
        account_id=row.account_id,
        template_id=row.template_id,
        status=row.status,
        scheduled_at=row.scheduled_at,
        updated_at=row.updated_at,
    )


def _to_response(row: WxDraft) -> WxDraftResponse:
    """Build the response shape (no body, no sections) from an ORM row."""
    base = _to_list_item(row)
    return WxDraftResponse(
        **base.model_dump(),
        cover_image_id=row.cover_image_id,
        kb_id=row.kb_id,
        tags=row.tags,
        published_at=row.published_at,
        wechat_media_id=row.wechat_media_id,
        error_message=row.error_message,
    )


def _to_section_response(row: WxDraftSection) -> WxDraftSectionResponse:
    """Build a section response shape from an ORM row."""
    return WxDraftSectionResponse(
        id=row.id,
        order_index=row.order_index,
        heading=row.heading,
        content_markdown=row.content_markdown,
        content_html=row.content_html,
        ai_prompt=row.ai_prompt,
        ai_model_config_id=row.ai_model_config_id,
    )


def _to_detail(row: WxDraft, sections: List[WxDraftSection]) -> WxDraftDetail:
    """Build the detail shape (response + body + sections)."""
    base = _to_response(row)
    return WxDraftDetail(
        **base.model_dump(),
        user_id=row.user_id,
        summary=row.summary,
        author=row.author,
        content_markdown=row.content_markdown,
        content_html=row.content_html,
        cover_url=row.cover_url,
        created_at=row.created_at,
        sections=[_to_section_response(s) for s in sections],
    )


# ---------------------------------------------------------------------------
# Endpoints — 草稿主表 CRUD (5 个)
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[WxDraftListItem])
def list_drafts(
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    template_id: Optional[int] = None,
    account_id: Optional[int] = None,
    title: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页列出当前租户的草稿。

    可选 filter:
    - ``status``: 精确匹配(draft / rendering / ready / publishing / published / failed)
    - ``template_id``: 绑定的模板 ID
    - ``account_id``: 绑定的公众号账号 ID
    - ``title``: 标题模糊搜索(大小写不敏感)
    """
    rows, total = service.list_drafts(
        db, current_user=current_user,
        page=page, page_size=page_size,
        status=status, template_id=template_id,
        account_id=account_id, title_search=title,
    )
    return PaginatedResponse(
        data=[_to_list_item(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[WxDraftResponse], status_code=201)
def create_draft(
    data: WxDraftCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建草稿。status 强制 'draft'(service 层默认)。"""
    try:
        row = service.create_draft(db, current_user=current_user, payload=data)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("create_draft: unexpected error")
        raise HTTPException(500, f"Failed to create draft: {e}")
    return SingleResponse(data=_to_response(row))


@router.get("/{draft_id}", response_model=SingleResponse[WxDraftDetail])
def get_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """草稿详情 — 包含完整 content_markdown / content_html + sections
    按 order_index 升序。"""
    row = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=True,
    )
    # 一次性按 order_index 拉 sections(避免懒加载的 N+1)
    sections = service.get_sections(
        db, current_user=current_user, draft_id=draft_id,
    )
    return SingleResponse(data=_to_detail(row, sections))


@router.put("/{draft_id}", response_model=SingleResponse[WxDraftResponse])
def update_draft(
    draft_id: int,
    data: WxDraftUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新草稿元数据。

    拒绝编辑 status in {publishing, published}(409)。
    title / content_markdown 必填;其他可选字段(null = 清空)。
    """
    try:
        row = service.update_draft(
            db, current_user=current_user,
            draft_id=draft_id, payload=data,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("update_draft: unexpected error")
        raise HTTPException(500, f"Failed to update draft: {e}")
    return SingleResponse(data=_to_response(row))


@router.delete("/{draft_id}", status_code=204)
def delete_draft(
    draft_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除草稿(走 ``wx_draft_sections`` ON DELETE CASCADE 自动清 sections)。

    拒绝删除 status in {publishing, published}(409)。MVP 用 hard delete
    (同 M31 FAQEntry);V2 引入 archived_at 字段后可改软删。
    """
    service.delete_draft(db, current_user=current_user, draft_id=draft_id)
    return None  # 204 No Content


# ---------------------------------------------------------------------------
# Endpoints — 章节 (4 个)
# ---------------------------------------------------------------------------

@router.post(
    "/{draft_id}/sections",
    response_model=SingleResponse[WxDraftSectionResponse],
    status_code=201,
)
def add_section(
    draft_id: int,
    data: WxDraftSectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """追加章节。order_index 由客户端指定(便于 UI 在指定位置插入)。

    拒绝在 status in {publishing, published} 时加(409)。
    order_index 撞现有 section 也返 409,让客户端重选位置。
    """
    try:
        row = service.add_section(
            db, current_user=current_user,
            draft_id=draft_id, payload=data,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("add_section: unexpected error")
        raise HTTPException(500, f"Failed to add section: {e}")
    return SingleResponse(data=_to_section_response(row))


@router.put(
    "/{draft_id}/sections/{section_id}",
    response_model=SingleResponse[WxDraftSectionResponse],
)
def update_section(
    draft_id: int,
    section_id: int,
    data: WxDraftSectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新章节 heading / content_markdown / order_index。"""
    try:
        row = service.update_section(
            db, current_user=current_user,
            draft_id=draft_id, section_id=section_id, payload=data,
        )
    except HTTPException:
        raise
    except Exception as e:
        log.exception("update_section: unexpected error")
        raise HTTPException(500, f"Failed to update section: {e}")
    return SingleResponse(data=_to_section_response(row))


@router.delete(
    "/{draft_id}/sections/{section_id}",
    status_code=204,
)
def delete_section(
    draft_id: int,
    section_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除章节。"""
    service.delete_section(
        db, current_user=current_user,
        draft_id=draft_id, section_id=section_id,
    )
    return None  # 204 No Content


@router.post(
    "/{draft_id}/sections/reorder",
    response_model=SingleResponse[dict],
)
def reorder_sections(
    draft_id: int,
    data: WxDraftSectionReorderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量重排章节。

    body: ``{"orders": [[section_id, new_order_index], ...]}``

    校验:
    - 所有 section_id 属于该 draft(否则 404)
    - new_order_index 互不重复(否则 409)
    - 拒绝在 status in {publishing, published} 时改(409)

    成功:返 ``{"reordered": N}``(N = 实际重排的 section 数)。
    """
    service.reorder_sections(
        db, current_user=current_user,
        draft_id=draft_id, section_orders=data.orders,
    )
    return SingleResponse(data={"reordered": len(data.orders)})


# ---------------------------------------------------------------------------
# Endpoints — AI 创作 + 渲染 (5 个, T17)
# ---------------------------------------------------------------------------

@router.post(
    "/{draft_id}/ai/outline",
    response_model=SingleResponse[WxAIOutlineResponse],
)
def ai_outline(
    draft_id: int,
    data: WxAIOutlineRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 大纲生成 — 调 ``WxAICreator.generate_outline``。

    同步响应(5-30s LLM 等待)。返回新建的 sections + llm_call_id +
    duration_ms。spec §4.2 + §7.1。
    """
    # 404 防 IDOR(get_draft 内部 tenant 隔离)
    draft = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=False,
    )
    if draft.status in LOCKED_STATUSES_FOR_EDIT:
        raise HTTPException(
            409,
            f"草稿正在发布或已发布,不能 AI 创作 (status={draft.status})",
        )
    from lumen_services.wx_publisher.ai_creator import WxAICreator
    creator = WxAICreator(db, current_user)
    t0 = time.monotonic()
    try:
        sections = creator.generate_outline(
            draft,
            topic=data.topic,
            section_count=data.section_count,
            model_config_id=data.model_config_id,
            style=data.style,
        )
    except Exception as e:
        log.exception("ai_outline: failed (draft_id=%s)", draft.id)
        raise HTTPException(500, f"AI outline failed: {e}")
    duration_ms = int((time.monotonic() - t0) * 1000)
    # llm_call_id 从 LLMCallContext 读(LoggingChatModel 写库时用)
    ctx = get_call_context()
    llm_call_id = ctx.call_id if ctx is not None else ""
    return SingleResponse(
        data=WxAIOutlineResponse(
            sections=[_to_section_response(s) for s in sections],
            llm_call_id=llm_call_id,
            duration_ms=duration_ms,
        )
    )


@router.post(
    "/{draft_id}/ai/rewrite",
    response_model=SingleResponse[WxAIRewriteResponse],
)
def ai_rewrite(
    draft_id: int,
    data: WxAIRewriteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 改写指定 section — 同步响应,不自动写库(让 UI 弹 Diff Modal)。

    spec §4.2。
    """
    draft = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=False,
    )
    if draft.status in LOCKED_STATUSES_FOR_EDIT:
        raise HTTPException(
            409,
            f"草稿正在发布或已发布,不能 AI 创作 (status={draft.status})",
        )
    section = db.query(WxDraftSection).filter(
        WxDraftSection.id == data.section_id,
        WxDraftSection.draft_id == draft_id,
        WxDraftSection.tenant_id == current_user.tenant_id,
    ).first()
    if not section:
        raise HTTPException(404, "Section not found")
    from lumen_services.wx_publisher.ai_creator import WxAICreator
    creator = WxAICreator(db, current_user)
    t0 = time.monotonic()
    try:
        new_md = creator.rewrite_section(
            section, instruction=data.instruction,
            model_config_id=data.model_config_id,
        )
    except Exception as e:
        log.exception("ai_rewrite: failed (section_id=%s)", section.id)
        raise HTTPException(500, f"AI rewrite failed: {e}")
    duration_ms = int((time.monotonic() - t0) * 1000)
    ctx = get_call_context()
    llm_call_id = ctx.call_id if ctx is not None else ""
    return SingleResponse(
        data=WxAIRewriteResponse(
            section_id=section.id,
            new_content_markdown=new_md,
            llm_call_id=llm_call_id,
            duration_ms=duration_ms,
        )
    )


@router.post(
    "/{draft_id}/ai/expand",
    response_model=SingleResponse[WxAIExpandResponse],
)
def ai_expand(
    draft_id: int,
    data: WxAIExpandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 扩写指定 section — 同步响应,不自动写库(让 UI 弹 Diff Modal)。

    spec §4.2。
    """
    draft = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=False,
    )
    if draft.status in LOCKED_STATUSES_FOR_EDIT:
        raise HTTPException(
            409,
            f"草稿正在发布或已发布,不能 AI 创作 (status={draft.status})",
        )
    section = db.query(WxDraftSection).filter(
        WxDraftSection.id == data.section_id,
        WxDraftSection.draft_id == draft_id,
        WxDraftSection.tenant_id == current_user.tenant_id,
    ).first()
    if not section:
        raise HTTPException(404, "Section not found")
    from lumen_services.wx_publisher.ai_creator import WxAICreator
    creator = WxAICreator(db, current_user)
    t0 = time.monotonic()
    try:
        new_md = creator.expand_section(
            section, expansion_ratio=data.expansion_ratio,
            model_config_id=data.model_config_id,
        )
    except Exception as e:
        log.exception("ai_expand: failed (section_id=%s)", section.id)
        raise HTTPException(500, f"AI expand failed: {e}")
    duration_ms = int((time.monotonic() - t0) * 1000)
    ctx = get_call_context()
    llm_call_id = ctx.call_id if ctx is not None else ""
    return SingleResponse(
        data=WxAIExpandResponse(
            section_id=section.id,
            new_content_markdown=new_md,
            llm_call_id=llm_call_id,
            duration_ms=duration_ms,
        )
    )


@router.post(
    "/{draft_id}/ai/title",
    response_model=SingleResponse[WxAITitleResponse],
)
def ai_title(
    draft_id: int,
    data: WxAITitleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 标题候选 — 同步响应,不自动写 ``draft.title``(让 UI 弹候选让用户挑)。

    spec §4.2。
    """
    draft = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=False,
    )
    if draft.status in LOCKED_STATUSES_FOR_EDIT:
        raise HTTPException(
            409,
            f"草稿正在发布或已发布,不能 AI 创作 (status={draft.status})",
        )
    from lumen_services.wx_publisher.ai_creator import WxAICreator
    creator = WxAICreator(db, current_user)
    t0 = time.monotonic()
    try:
        titles = creator.generate_titles(
            draft, count=data.count, model_config_id=data.model_config_id,
        )
    except Exception as e:
        log.exception("ai_title: failed (draft_id=%s)", draft.id)
        raise HTTPException(500, f"AI title failed: {e}")
    duration_ms = int((time.monotonic() - t0) * 1000)
    ctx = get_call_context()
    llm_call_id = ctx.call_id if ctx is not None else ""
    return SingleResponse(
        data=WxAITitleResponse(
            titles=titles,
            llm_call_id=llm_call_id,
            duration_ms=duration_ms,
        )
    )


@router.post(
    "/{draft_id}/render",
    response_model=SingleResponse[WxRenderResponse],
)
def render_draft(
    draft_id: int,
    data: WxRenderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """应用模板渲染 Markdown → HTML — 同步响应,写 ``content_html`` + status='ready'。

    spec §4.2 / §7.2。
    """
    from lumen_models.wx_publisher import WxTemplate
    from lumen_services.wx_publisher.renderer import WxRenderer

    draft = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=False,
    )
    if draft.status in LOCKED_STATUSES_FOR_EDIT:
        raise HTTPException(
            409,
            f"草稿正在发布或已发布,不能排版 (status={draft.status})",
        )
    template = db.query(WxTemplate).filter(
        WxTemplate.id == data.template_id,
        WxTemplate.tenant_id == current_user.tenant_id,
    ).first()
    if not template:
        raise HTTPException(404, "Template not found")
    try:
        renderer = WxRenderer(db)
        final_html = renderer.render(draft=draft, template=template)
    except Exception as e:
        log.exception("render_draft: failed (draft_id=%s)", draft.id)
        raise HTTPException(500, f"Render failed: {e}")
    # template usage_count +1
    template.usage_count = (template.usage_count or 0) + 1
    db.commit()
    preview_url = f"/dashboard/wx-publisher/drafts/{draft.id}?preview=1"
    return SingleResponse(
        data=WxRenderResponse(
            draft_id=draft.id,
            content_html=final_html,
            preview_url=preview_url,
        )
    )


# ---------------------------------------------------------------------------
# M32.1 — 粘贴 HTML 自动转 Markdown (paste-html endpoint)
# ---------------------------------------------------------------------------
#
# 借鉴 lark-to-markdown-main/utils/markdownConverter.ts 的「粘贴飞书」流。
# 用户在 MDEditor 粘贴飞书/网页富文本 → 前端拦截 paste 事件 → 调本 endpoint
# → 后端 HTML → MD → append 到 ``draft.content_markdown``。
#
# 行为:
# - 不覆盖, append 到末尾 + 2 换行(后续用户可手动 reorder / 编辑)
# - status 不动(仍 'draft'),需用户手动 [应用模板] 才进 'ready'
# - 拒绝在 status in {publishing, published} 时改(409, 同 update_draft)

@router.post(
    "/{draft_id}/paste-html",
    response_model=SingleResponse[WxDraftDetail],
)
def paste_html(
    draft_id: int,
    payload: WxDraftPasteHtmlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """粘贴 HTML(飞书/网页) → 转 Markdown → append 到 draft.content_markdown。

    前端用法: ``useHtmlPasteHandler(draftId, onConverted)`` hook 拦截
    MDEditor 的 ``textareaProps.onPaste`` 事件,把 ``clipboardData.getData('text/html')``
    发到这里。后端返 ``WxDraftDetail`` (含完整 content_markdown),
    前端用全文替换 textarea 内容。
    """
    # 404 防 IDOR(get_draft 内部 tenant 隔离)+ 409 状态锁
    draft = service.get_draft(
        db, current_user=current_user, draft_id=draft_id,
        include_sections=False,
    )
    if draft.status in LOCKED_STATUSES_FOR_EDIT:
        raise HTTPException(
            409,
            f"草稿正在发布或已发布,不能粘贴 (status={draft.status})",
        )
    # HTML → MD 转换(独立实现,无新依赖)
    try:
        from lumen_services.wx_publisher.html_converter import HtmlToMarkdownConverter
        converter = HtmlToMarkdownConverter()
        appended_md = converter.convert(payload.html)
    except Exception as e:
        log.exception("paste_html: html conversion failed (draft_id=%s)", draft.id)
        raise HTTPException(500, f"HTML conversion failed: {e}")
    if not appended_md.strip():
        # 粘贴的内容是空 HTML(如只含 ``<span></span>``) — no-op
        # 仍返完整 detail 让前端状态对齐
        sections = service.get_sections(
            db, current_user=current_user, draft_id=draft_id,
        )
        return SingleResponse(data=_to_detail(draft, sections))
    # Append 到现有 markdown(末尾 + 2 换行)
    existing = draft.content_markdown or ""
    separator = "\n\n" if existing and not existing.endswith("\n") else ""
    draft.content_markdown = existing + separator + appended_md
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("paste_html: commit failed (draft_id=%s)", draft.id)
        raise HTTPException(500, f"Save failed: {e}")
    db.refresh(draft)
    log.info(
        "paste_html: appended %d chars (draft_id=%s, total now %d chars)",
        len(appended_md), draft.id, len(draft.content_markdown),
    )
    # 返完整 detail(含 sections)给前端,让前端能用全文 content_markdown
    sections = service.get_sections(
        db, current_user=current_user, draft_id=draft_id,
    )
    return SingleResponse(data=_to_detail(draft, sections))
