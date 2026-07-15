"""M32 公众号助手 - 草稿管理 service.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.3 / §3.4 / §7.2

CP2 范围 (T9):
- 草稿 CRUD with multi-tenant 隔离 (row.tenant_id == current_user.tenant_id)
- 章节 (sections) 增删改 + 重排
- 状态流检查: publishing / published 时拒绝编辑(409)
- 跨租户 IDOR 一律返 404(NOT 403,防信息泄露)
- sections 合并 helper:get_full_markdown() 给 T16 renderer 用

不在本 service 范围 (后续任务):
- AI 创作 (T15 ai_creator.py)
- 渲染 (T16 renderer.py)
- 真实发布 (T22 publish_service.py)

status 流转(参考 spec §3.3 + §7.4):
- draft -> rendering -> ready -> publishing -> published / failed
- create_draft 走 'draft'
- update_draft 拒绝 status in ('publishing', 'published')
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen_models.user import User
from lumen_models.wx_publisher import WxDraft, WxDraftSection
from lumen_schemas.wx_publisher import (
    WxDraftCreate,
    WxDraftSectionCreate,
    WxDraftSectionUpdate,
    WxDraftUpdate,
)

log = logging.getLogger(__name__)


# 拒绝编辑的 status(spec §4.4:409 草稿正在发布,不能编辑)
LOCKED_STATUSES_FOR_EDIT = frozenset({"publishing", "published"})

# 拒绝对 sections 增删改的 status
LOCKED_STATUSES_FOR_SECTION = frozenset({"publishing", "published"})


class WxDraftService:
    """草稿管理业务逻辑。Multi-tenant 通过 ``current_user.tenant_id`` 隔离。"""

    # --- 草稿主表 CRUD ----------------------------------------------------

    def create_draft(
        self, db: Session, *, current_user: User, payload: WxDraftCreate
    ) -> WxDraft:
        """Create a new WxDraft.

        只接 ``WxDraftCreate`` 的字段(title / content_markdown / 可选
        account_id / template_id / kb_id / tags)。status 默认 'draft',
        summary / author / cover 留空(后续 PATCH / 单独 endpoint 改)。

        tenant_id 与 user_id 从 current_user 注入,不入 payload(spec §3.3)。
        """
        row = WxDraft(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            title=payload.title,
            content_markdown=payload.content_markdown,
            account_id=payload.account_id,
            template_id=payload.template_id,
            kb_id=payload.kb_id,
            tags=payload.tags,
            # status / summary / author / cover_image_id / cover_url 走 model default
            status="draft",
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            log.warning("create_draft: IntegrityError (FK violation?): %s", e)
            # 多半是 account_id / template_id / kb_id 指向了不存在或不
            # 属于本租户的 row。这里 404(NOT 422)以免泄露存在性。
            raise HTTPException(404, "Referenced resource not found")
        except Exception as e:
            db.rollback()
            log.exception("create_draft: unexpected error")
            raise HTTPException(500, f"Failed to create draft: {e}")
        db.refresh(row)
        return row

    def get_draft(
        self, db: Session, *, current_user: User, draft_id: int,
        include_sections: bool = True,
    ) -> WxDraft:
        """Load a WxDraft scoped to ``current_user.tenant_id``.

        Returns 404 for cross-tenant access — same pattern as
        ``account_service.get_account``(防 IDOR 信息泄露)。

        ``include_sections=True``(默认)在详情页用 — 一次性把 sections
        按 order_index 升序带回;列表页走 list_drafts,不走这里,所以
        不会 N+1。
        """
        row = db.query(WxDraft).filter(
            WxDraft.id == draft_id,
            WxDraft.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(404, "Draft not found")
        # 注:WxDraft model 没有定义 `sections` relationship — sections 走
        # `get_sections()` 单独查询(在 endpoint 层调用)。这里不做 eager load
        # 避免 AttributeError。include_sections 参数保留为兼容性。
        return row

    def list_drafts(
        self, db: Session, *, current_user: User,
        page: int = 1, page_size: int = 20,
        status: Optional[str] = None,
        template_id: Optional[int] = None,
        account_id: Optional[int] = None,
        title_search: Optional[str] = None,
    ) -> Tuple[List[WxDraft], int]:
        """Paginated list with optional filters.

        All filters are AND-combined. ``title_search`` is a case-insensitive
        substring match (``LIKE %x%``) — fine for MVP scale, V2 may switch
        to FULLTEXT index.
        """
        q = db.query(WxDraft).filter(WxDraft.tenant_id == current_user.tenant_id)
        if status is not None:
            q = q.filter(WxDraft.status == status)
        if template_id is not None:
            q = q.filter(WxDraft.template_id == template_id)
        if account_id is not None:
            q = q.filter(WxDraft.account_id == account_id)
        if title_search:
            # MySQL 默认 collation 是 utf8mb4_unicode_ci,LIKE 已大小写不敏感
            escaped = title_search.replace("%", r"\%").replace("_", r"\_")
            q = q.filter(WxDraft.title.like(f"%{escaped}%"))
        total = q.count()
        q = q.order_by(WxDraft.updated_at.desc())
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def update_draft(
        self, db: Session, *, current_user: User, draft_id: int,
        payload: WxDraftUpdate,
    ) -> WxDraft:
        """Partial update — only fields **explicitly provided** in payload
        are changed.

        Pydantic v2 陷阱:``model_dump()`` 默认会把所有 Optional 字段
        (默认值 None) 都 dump 出来 — 哪怕 caller 没传。如果 service 直接
        ``row.account_id = payload.account_id``,未传的字段就会被 None
        覆盖,**擦掉原值**(2026-06-29 真实事故:前端保存时只发 title +
        content_markdown,结果 account_id / template_id 被清空)。

        修法:用 ``model_dump(exclude_unset=True)`` 只取 payload 里 caller
        实际 set 过的字段 — 这才是 docstring 承诺的 "partial update" 语义。

        Reject edit if status in {publishing, published}(spec §4.4:409)。
        允许显式传 null 字段把已存值清空(通过 ``exclude_unset`` 区分
        "未传" 和 "传了 None" — ``exclude_unset`` 只过滤前者)。
        """
        row = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        if row.status in LOCKED_STATUSES_FOR_EDIT:
            raise HTTPException(
                409,
                f"草稿正在发布或已发布,不能编辑 (status={row.status})",
            )
        # 关键:exclude_unset=True → 只 dump caller 实际 set 过的字段,
        # 未传的 Optional 字段不在 dict 里,不会覆盖 ORM。
        update_data = payload.model_dump(exclude_unset=True)
        # title / content_markdown 是 required, schema 已保证存在,
        # 但 ``exclude_unset`` 对 required 字段也工作(title 永远在 dict 里)。
        for field, value in update_data.items():
            setattr(row, field, value)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            log.warning("update_draft: IntegrityError (FK violation?): %s", e)
            raise HTTPException(404, "Referenced resource not found")
        except Exception as e:
            db.rollback()
            log.exception("update_draft: unexpected error")
            raise HTTPException(500, f"Failed to update draft: {e}")
        db.refresh(row)
        return row

    def delete_draft(
        self, db: Session, *, current_user: User, draft_id: int
    ) -> None:
        """Hard delete(MVP)— 走 ``wx_draft_sections`` ON DELETE CASCADE
        自动清理 sections(spec §3.4)。

        spec §4.1 表格里写的是"软删 (archived_at = now)",但 spec §3.3
        字段表里没列 archived_at 列,所以 V2 才会加 archived_at 字段 +
        软删语义。本阶段用 hard delete(同 M31 FAQEntry 模式,无
        audit 需求)。

        拒绝删除 status in {publishing, published}(防止发布流程被
        中断;已经发出的草稿通过 wx_publish_records 审计可查)。
        """
        row = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        if row.status in LOCKED_STATUSES_FOR_EDIT:
            raise HTTPException(
                409,
                f"草稿正在发布或已发布,不能删除 (status={row.status})",
            )
        db.delete(row)
        db.commit()

    # --- 章节 (sections) -------------------------------------------------

    def get_sections(
        self, db: Session, *, current_user: User, draft_id: int,
    ) -> List[WxDraftSection]:
        """List all sections for a draft, ordered by ``order_index`` ASC.

        Implicitly enforces tenant isolation via the draft's tenant_id
        (we first 404 if the draft itself isn't in the tenant).
        """
        # 404 防 IDOR
        self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        return db.query(WxDraftSection).filter(
            WxDraftSection.draft_id == draft_id,
            WxDraftSection.tenant_id == current_user.tenant_id,
        ).order_by(WxDraftSection.order_index.asc()).all()

    def add_section(
        self, db: Session, *, current_user: User, draft_id: int,
        payload: WxDraftSectionCreate,
    ) -> WxDraftSection:
        """Append a new section to the draft.

        The caller supplies ``order_index`` explicitly(spec §3.4 把
        这个字段放 Pydantic 入参里)— 客户端可指定插入位置,server
        校验不冲突(UNIQUE(draft_id, order_index))。若 order_index
        撞现有 section,直接 409 让客户端重选位置或先调 reorder。

        拒绝在 status in {publishing, published} 时加章节。
        """
        draft = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        if draft.status in LOCKED_STATUSES_FOR_SECTION:
            raise HTTPException(
                409,
                f"草稿正在发布或已发布,不能修改章节 (status={draft.status})",
            )
        row = WxDraftSection(
            tenant_id=current_user.tenant_id,
            draft_id=draft_id,
            order_index=payload.order_index,
            heading=payload.heading,
            content_markdown=payload.content_markdown,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            log.warning("add_section: IntegrityError (order_index dup?): %s", e)
            raise HTTPException(
                409,
                f"order_index={payload.order_index} already exists in this draft",
            )
        except Exception as e:
            db.rollback()
            log.exception("add_section: unexpected error")
            raise HTTPException(500, f"Failed to add section: {e}")
        db.refresh(row)
        return row

    def update_section(
        self, db: Session, *, current_user: User, draft_id: int,
        section_id: int, payload: WxDraftSectionUpdate,
    ) -> WxDraftSection:
        """Update a section's heading / content_markdown / order_index.

        拒绝在 status in {publishing, published} 时改章节。
        """
        draft = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        if draft.status in LOCKED_STATUSES_FOR_SECTION:
            raise HTTPException(
                409,
                f"草稿正在发布或已发布,不能修改章节 (status={draft.status})",
            )
        row = db.query(WxDraftSection).filter(
            WxDraftSection.id == section_id,
            WxDraftSection.draft_id == draft_id,
            WxDraftSection.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(404, "Section not found")
        row.heading = payload.heading
        row.content_markdown = payload.content_markdown
        row.order_index = payload.order_index
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            log.warning("update_section: IntegrityError (order_index dup?): %s", e)
            raise HTTPException(
                409,
                f"order_index={payload.order_index} already exists in this draft",
            )
        except Exception as e:
            db.rollback()
            log.exception("update_section: unexpected error")
            raise HTTPException(500, f"Failed to update section: {e}")
        db.refresh(row)
        return row

    def delete_section(
        self, db: Session, *, current_user: User, draft_id: int,
        section_id: int,
    ) -> None:
        """Hard delete a section.

        拒绝在 status in {publishing, published} 时删章节。
        """
        draft = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        if draft.status in LOCKED_STATUSES_FOR_SECTION:
            raise HTTPException(
                409,
                f"草稿正在发布或已发布,不能修改章节 (status={draft.status})",
            )
        row = db.query(WxDraftSection).filter(
            WxDraftSection.id == section_id,
            WxDraftSection.draft_id == draft_id,
            WxDraftSection.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(404, "Section not found")
        db.delete(row)
        try:
            db.commit()
        except IntegrityError as e:
            # 理论上不会撞 — sections 的 UNIQUE 只有 (draft_id, order_index)
            db.rollback()
            log.warning("delete_section: IntegrityError: %s", e)
            raise HTTPException(500, f"Failed to delete section: {e}")

    def reorder_sections(
        self, db: Session, *, current_user: User, draft_id: int,
        section_orders: List[Tuple[int, int]],
    ) -> None:
        """Bulk reorder: ``section_orders`` is a list of
        ``(section_id, new_order_index)`` pairs.

        Reject edit if status in {publishing, published}(同 update)。
        校验:
        1. 所有 section_id 都属于该 draft
        2. 新的 order_index 互不重复
        3. 校验失败 -> 409 让客户端重排

        实现:逐 row UPDATE(避免一次写多个 row 时部分失败难 rollback)。
        SQLAlchemy session 的 autoflush=False 行为在 SessionLocal 配
        置上 — 我们手动 commit 在最后一步。
        """
        draft = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        if draft.status in LOCKED_STATUSES_FOR_SECTION:
            raise HTTPException(
                409,
                f"草稿正在发布或已发布,不能重排章节 (status={draft.status})",
            )
        # 校验:order_index 互不重复
        new_indices = [o for _, o in section_orders]
        if len(new_indices) != len(set(new_indices)):
            raise HTTPException(
                409,
                "Duplicate order_index values in reorder request",
            )
        if not section_orders:
            return  # 空请求 = no-op
        # 校验:所有 section_id 都属于该 draft
        section_ids = [sid for sid, _ in section_orders]
        existing = db.query(WxDraftSection).filter(
            WxDraftSection.draft_id == draft_id,
            WxDraftSection.tenant_id == current_user.tenant_id,
            WxDraftSection.id.in_(section_ids),
        ).all()
        existing_ids = {s.id for s in existing}
        missing = set(section_ids) - existing_ids
        if missing:
            raise HTTPException(
                404,
                f"Sections not found in this draft: {sorted(missing)}",
            )
        # 应用:逐 row UPDATE
        # 用 dict 索引避免再次查 DB
        section_by_id = {s.id: s for s in existing}
        for sid, new_idx in section_orders:
            section_by_id[sid].order_index = new_idx
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            log.warning("reorder_sections: IntegrityError: %s", e)
            raise HTTPException(
                409,
                "order_index conflict after reorder (race with concurrent edit?)",
            )

    # --- 辅助 helper(给 T16 renderer 用)--------------------------------

    def get_full_markdown(
        self, db: Session, *, current_user: User, draft_id: int,
    ) -> str:
        """Merge all sections into a single markdown string.

        T16 renderer 用这个把 sections 拼成单 md,再走模板 HTML 渲染
        (spec §7.2)。格式:

            ## {section.heading}

            {section.content_markdown}

        sections 之间空一行。若 draft 没有 sections,fallback 到
        ``draft.content_markdown``(单 section / 整段文本模式)。

        这里的 tenant 隔离由 get_draft 内部保证。
        """
        draft = self.get_draft(
            db, current_user=current_user, draft_id=draft_id,
            include_sections=False,
        )
        sections = self.get_sections(
            db, current_user=current_user, draft_id=draft_id,
        )
        if not sections:
            return draft.content_markdown
        parts: List[str] = []
        for s in sections:
            if s.heading:
                parts.append(f"## {s.heading}\n\n{s.content_markdown}")
            else:
                parts.append(s.content_markdown)
        return "\n\n".join(parts)
