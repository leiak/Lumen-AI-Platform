"""M32 公众号助手 - 排版模板 service.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.2 / §4.2

Responsibilities (CP2 scope):
- 模板 CRUD with multi-tenant 隔离 (row.tenant_id == current_user.tenant_id)
- ``is_system`` 保护: 系统模板(种子数据,5 套内置)不可编辑/删除
- ``is_system=True`` 创建权限: 只有 superuser 才能创建系统模板,
  非 admin 客户端即使传 is_system=True 也会被静默降级为 False
- 缩略图 byte 提取 + ``usage_count`` 计数
- 删除采用 hard delete(没有 ``is_active`` / ``archived_at`` 字段 — spec
  §3.2 没列),但 usage_count>0 时 422 拒绝(防误删已被草稿引用的模板)

Tenant 隔离策略与 ``account_service`` 一致: 跨租户访问返 404(不是 403)
防止 IDOR 信息泄露。
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import List, Optional, Tuple

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from lumen_models.user import User
from lumen_models.wx_publisher import WxTemplate
from lumen_schemas.wx_publisher import WxTemplateCreate, WxTemplateUpdate

log = logging.getLogger(__name__)

# generate_thumbnail_inline 的 busy-poll 配置
_GEN_POLL_INTERVAL_SEC = 0.5
_GEN_POLL_MAX_ATTEMPTS = 120  # 120 * 0.5 = 60 秒上限


class WxTemplateService:
    """模板管理业务逻辑。Multi-tenant 通过 ``current_user.tenant_id`` 隔离。"""

    # --- CRUD --------------------------------------------------------------

    def create_template(
        self, db: Session, *, current_user: User, payload: WxTemplateCreate
    ) -> WxTemplate:
        """Create a new WxTemplate.

        is_system 权限: spec §3.2 说系统模板"为 admin user_id=1 创建"。
        如果非 superuser 客户端传 ``is_system=True``,静默降级为 False
        (不让客户端提权)。Superuser 可创建 is_system=True 的模板 —
        这是 seed 工具的核心路径。
        """
        is_system = bool(payload.is_system) and bool(current_user.is_superuser)
        row = WxTemplate(
            tenant_id=current_user.tenant_id,
            name=payload.name,
            category=payload.category,
            description=payload.description,
            html_body=payload.html_body,
            css_variables=payload.css_variables,
            preview_html=payload.preview_html,
            is_system=is_system,
            created_by=current_user.id,
            usage_count=0,
        )  # type: ignore[arg-type]
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def get_template(
        self, db: Session, *, current_user: User, template_id: int
    ) -> WxTemplate:
        """Load a WxTemplate scoped to ``current_user.tenant_id``.

        Returns 404 (NOT 403) for cross-tenant access — leaking the
        existence of another tenant's resource would be an IDOR
        information leak. Same pattern as ``account_service.get_account``
        and M21 ``agent_rag``.
        """
        row = db.query(WxTemplate).filter(
            WxTemplate.id == template_id,
            WxTemplate.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(404, "Template not found")
        return row

    def list_templates(
        self, db: Session, *, current_user: User,
        page: int = 1, page_size: int = 20,
        category: Optional[str] = None,
        is_system: Optional[bool] = None,
    ) -> Tuple[List[WxTemplate], int]:
        """Paginated list. ``category`` / ``is_system`` filters are
        optional and let the UI scope to a style or hide system templates.
        """
        q = db.query(WxTemplate).filter(
            WxTemplate.tenant_id == current_user.tenant_id,
        )
        if category is not None:
            q = q.filter(WxTemplate.category == category)
        if is_system is not None:
            q = q.filter(WxTemplate.is_system == is_system)
        total = q.count()
        # Order: is_system first (so seed templates surface at the top
        # of the gallery), then by usage_count DESC, then by recency.
        # This matches spec §5.4 — system templates are highlighted
        # with a "系统" badge but should be the natural first picks.
        q = q.order_by(
            WxTemplate.is_system.desc(),
            WxTemplate.usage_count.desc(),
            WxTemplate.created_at.desc(),
        )
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def update_template(
        self, db: Session, *, current_user: User, template_id: int,
        payload: WxTemplateUpdate,
    ) -> WxTemplate:
        """Update an operator-editable template. 系统模板(``is_system=True``)
        不可编辑 — spec §3.2 说"系统内置 5 套,不允许编辑/删除"。返 403。

        Only the fields present in the payload are touched; the rest
        keep their existing values (Pydantic ``Optional[None]`` semantics
        match the ``if payload.X is not None`` checks).
        """
        row = self.get_template(
            db, current_user=current_user, template_id=template_id,
        )
        if row.is_system:
            # 403 — caller can read but not modify. Cross-tenant row
            # never reaches here because get_template() already 404'd.
            raise HTTPException(403, "System templates cannot be edited")
        if payload.name is not None:
            row.name = payload.name  # type: ignore[assignment]
        if payload.category is not None:
            row.category = payload.category  # type: ignore[assignment]
        if payload.description is not None:
            row.description = payload.description  # type: ignore[assignment]
        if payload.html_body is not None:
            row.html_body = payload.html_body  # type: ignore[assignment]
        if payload.css_variables is not None:
            row.css_variables = payload.css_variables  # type: ignore[assignment]
        if payload.preview_html is not None:
            row.preview_html = payload.preview_html  # type: ignore[assignment]
        db.commit()
        db.refresh(row)
        return row

    def delete_template(
        self, db: Session, *, current_user: User, template_id: int
    ) -> None:
        """Hard delete a template (spec §3.2 没 ``is_active`` / ``archived_at``
        字段 — 用 hard delete,422 拒绝 usage_count>0)。

        Why hard-delete vs. soft-delete (vs. account's is_active=False):
        1. wx_drafts.template_id is ON DELETE SET NULL — drafts keep
           working after the template is removed, just lose the auto-render
           fallback (operator re-binds a different template).
        2. No audit-trail requirement on templates (they're not
           transactional artifacts like publish records).
        3. Operators expect "Delete" to be permanent in a template
           gallery — ghost rows cluttering the list are worse UX.
        """
        row = self.get_template(
            db, current_user=current_user, template_id=template_id,
        )
        if row.is_system:
            raise HTTPException(403, "System templates cannot be deleted")
        if row.usage_count and row.usage_count > 0:
            # 422 — business rule: usage_count>0 means at least one
            # draft was rendered through this template. Deleting it
            # would orphan draft history references. Operator can
            # first unbind drafts (SET NULL happens automatically on
            # delete though), but for CP2 we keep the conservative
            # 422 to surface the dependency. UI should show a hint
            # listing the dependent drafts.
            raise HTTPException(
                422,
                f"Template has been used {row.usage_count} time(s); "
                "remove dependent drafts first",
            )
        db.delete(row)
        db.commit()

    # --- 缩略图 / usage_count 辅助接口 ------------------------------------

    def get_thumbnail_bytes(
        self, db: Session, *, current_user: User, template_id: int,
    ) -> Optional[bytes]:
        """Return the raw thumbnail JPEG bytes for a template, or None
        if the row has no thumbnail. 404 on cross-tenant access (so
        the API layer can return 404 instead of leaking "exists but
        not yours")."""
        row = self.get_template(
            db, current_user=current_user, template_id=template_id,
        )
        return row.thumbnail  # type: ignore[return-value]

    def get_thumbnail_etag(
        self, db: Session, *, current_user: User, template_id: int,
    ) -> Optional[str]:
        """Compute a stable ETag for the template's thumbnail.

        The ETag is a SHA-256 hash of the JPEG bytes, prefixed with
        ``"W/`` (weak validator) since we don't guarantee byte-for-byte
        stability across re-encodes. If a row is later re-rendered with
        new bytes, the ETag changes and clients refetch.

        Returns None if the template has no thumbnail — the API layer
        uses that to return 404.
        """
        row = self.get_template(
            db, current_user=current_user, template_id=template_id,
        )
        if not row.thumbnail:
            return None
        digest = hashlib.sha256(row.thumbnail).hexdigest()
        return f'W/"{digest}"'

    def increment_usage_count(
        self, db: Session, *, template_id: int,
    ) -> None:
        """Render-time hook: bump ``usage_count`` by 1.

        Called from ``renderer.py`` (T16 / renderer task) on each
        successful Markdown→HTML render. Skips tenant scoping because
        the caller's template_id is already validated by the draft's
        own tenant_id check; this method is a thin counter and would
        only race-condition if two requests rendered the same
        template simultaneously — and the loser just loses a +1, which
        is fine for a UI sort metric.
        """
        row = db.query(WxTemplate).filter(WxTemplate.id == template_id).first()
        if not row:
            log.warning(
                "increment_usage_count: template id=%s not found (caller race?)",
                template_id,
            )
            return
        # Read-modify-write under a single Session; concurrent renders
        # of the same template from the same uvicorn worker would
        # lose updates, but cross-worker races are protected by
        # MySQL row locking. V2 may switch to ``UPDATE ... SET
        # usage_count = usage_count + 1`` for atomicity.
        row.usage_count = (row.usage_count or 0) + 1  # type: ignore[assignment]
        db.commit()

    # --- 自动生成缩略图 (M32.1) --------------------------------------

    def generate_thumbnail_inline(
        self,
        db: Session,
        *,
        current_user: User,
        template_id: int,
    ) -> WxTemplate:
        """用 image-generation 自动生成模板缩略图, 同步等待完成。

        流程:
        1. 取模板 (IDOR 隔离 — 跨租户返 404)
        2. 在租户内找第一个 ``is_image_generation=True`` 的 ModelConfig
        3. 用模板 name + category + description 拼英文 prompt
        4. 调 ImageGenerationService.create() 创建行 (status=pending),
           BackgroundTasks 调度 _run_generation
        5. busy-poll 行 status (max 60s, 间隔 0.5s):
           - completed → 读 file_path → 写 template.thumbnail → commit
           - failed → 抛 500 (把 error_message 带回去)
           - 60s 超时 → 504

        Returns:
            更新后的 WxTemplate 行(thumbnail 字段非空)。

        Raises:
            HTTPException 404 — 模板不存在或跨租户
            HTTPException 422 — 租户内没有 image-gen model_config
            HTTPException 500 — image-gen 任务失败
            HTTPException 504 — 60s 内未完成
        """
        template = self.get_template(
            db, current_user=current_user, template_id=template_id,
        )

        # 1. 找 image-gen model
        from lumen_models.model_config import ModelConfig
        from lumen_models.image_generation import GeneratedImage
        from lumen_services.image_generation_service import ImageGenerationService

        mc = db.query(ModelConfig).filter(
            ModelConfig.tenant_id == current_user.tenant_id,
            ModelConfig.is_image_generation == True,  # noqa: E712
            ModelConfig.is_active == True,  # noqa: E712
        ).order_by(ModelConfig.id).first()
        if mc is None:
            raise HTTPException(
                422,
                "租户内没有可用的 image-generation 模型, 请先在 系统设置 → 模型管理 添加",
            )

        # 2. 拼 prompt (英文 + 模板元数据)
        desc = (template.description or "").strip()
        prompt = (
            f"Abstract decorative header image for a Chinese WeChat public "
            f"account article template. "
            f"Template name: {template.name}. "
            f"Style category: {template.category}. "
            f"Description: {desc}. "
            f"Style: minimalist, modern, professional, suitable for 900x383 "
            f"cover image. No text overlay, no watermarks, no logos."
        )

        # 3. 调 ImageGenerationService.create() (异步写 row + 调度 background)
        #    注意:这里需要一个 BackgroundTasks 实例,但 service.create 不真
        #    正依赖 background_tasks.add_task (只是用来调度), 实际执行走
        #    FastAPI 的 BackgroundTasks middleware — 我们传入 fake 即可。
        bg = BackgroundTasks()
        rows, batch_id = ImageGenerationService().create(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            model_config_id=mc.id,
            prompt=prompt,
            size="1024x1024",
            n=1,
            background_tasks=bg,
        )
        if not rows:
            raise HTTPException(500, "image-generation create returned no rows")
        if batch_id == "not_image_capable":
            raise HTTPException(500, f"model_config id={mc.id} 不是 image-capable")
        row_id = rows[0].id

        # 4. busy-poll 直到 status 完成 (max 60s)
        #    用独立 query 避免 session identity-map 缓存。
        for attempt in range(_GEN_POLL_MAX_ATTEMPTS):
            row = db.query(GeneratedImage).filter(
                GeneratedImage.id == row_id,
            ).first()
            if row is None:
                raise HTTPException(500, "image-generation row disappeared")
            if row.status == "completed":
                break
            if row.status == "failed":
                raise HTTPException(
                    500,
                    f"image generation failed: {row.error_message or 'unknown error'}",
                )
            time.sleep(_GEN_POLL_INTERVAL_SEC)
        else:
            raise HTTPException(504, "image generation timed out (60s)")

        # 5. 读 file_path → 写 template.thumbnail
        file_path = row.file_path
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(
                500,
                f"image-generation file_path missing: {file_path!r}",
            )
        with open(file_path, "rb") as f:
            template.thumbnail = f.read()
        db.commit()
        db.refresh(template)
        log.info(
            "generate_thumbnail_inline: template_id=%s → %d bytes thumbnail (image_gen_id=%s)",
            template.id, len(template.thumbnail or b""), row_id,  # type: ignore[arg-type]
        )
        return template
