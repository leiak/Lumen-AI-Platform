"""M32 公众号助手 - 素材库 service.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.5 / §4.2

Responsibilities (CP2 scope, T11):
- 手动录入素材 (source_type='manual')
- KB 检索结果导入 (走 M28 RetrievalPipeline, source_type='kb')
- 分页列表 + tag / source_type / title 过滤
- Hard delete (无 soft-delete — 素材丢就丢, 无副作用, 跟 M14 草稿 soft-delete 不同)
- 标签聚合 (按 tenant 收集所有用过的 tag, UI 做 autocomplete)

MVP 简化 (T11 范围, 不进 V2):
- KB 导入不做 ``kb_chunk_id`` 去重 — 每次 import 都新建一行。
  Spec §3.5 把 ``kb_chunk_id`` 设计成 nullable + ON DELETE SET NULL,
  本意是「KB chunk 删了不级联删素材」, 没要求 unique。
  V2 加去重, 字段是 ``UNIQUE(tenant_id, kb_chunk_id) WHERE kb_chunk_id IS NOT NULL``
  (MySQL 8 functional index 或 unique + NULL distinct)。
- 标签聚合用 Python 端 ``json.loads`` + ``set``, 数据量 < 10k 行
  时 O(N) 完全可接受;V2 改 SQL JSON_TABLE。

跟 ``AccountService`` 一样的多租户隔离模式:
``current_user.tenant_id`` 在所有 query 显式 filter, 跨租户 row 返
404 (不是 403, 防 IDOR 信息泄露)。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from lumen_models.knowledge import KnowledgeBase
from lumen_models.user import User
from lumen_models.wx_publisher import WxMaterial
from lumen_schemas.wx_publisher import (
    WxMaterialCreate,
    WxMaterialImportFromKBRequest,
    WxMaterialListItem,
    WxMaterialResponse,
)

log = logging.getLogger(__name__)

# List 截断预览长度 — 跟 ``WxMaterialListItem.content_preview`` 的
# 设计契约一致: 超过这个长度的 content 在 list 里用 ``"...(truncated)"``
# 尾巴表示, 详情接口 (WxMaterialResponse) 返全文。
CONTENT_PREVIEW_MAX_LEN = 200


def _parse_tags(raw: Optional[str]) -> Optional[List[str]]:
    """JSON column -> list[str]. 容忍坏数据 (返 None + 警告, 不抛)。"""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as e:
        log.warning("material tags parse failed: %s", e)
        return None
    if not isinstance(parsed, list):
        return None
    return [str(x) for x in parsed]


def _build_preview(content: str) -> str:
    """生成列表项的 ``content_preview``。超过 ``CONTENT_PREVIEW_MAX_LEN``
    时截断并附加 ``"…"``。空白字符串保留 (前端不显示而不是显示 None)。
    """
    if not content:
        return ""
    if len(content) <= CONTENT_PREVIEW_MAX_LEN:
        return content
    return content[:CONTENT_PREVIEW_MAX_LEN] + "…"


def _to_list_item(row: WxMaterial) -> WxMaterialListItem:
    """ORM row -> list-item shape. content 截 200 字符。"""
    return WxMaterialListItem(
        id=row.id,
        title=row.title,
        content_preview=_build_preview(row.content),
        source_type=row.source_type,
        kb_chunk_id=row.kb_chunk_id,
        tags=_parse_tags(row.tags),
        is_used=row.is_used,
        created_at=row.created_at,
    )


def _to_response(row: WxMaterial) -> WxMaterialResponse:
    """ORM row -> detail shape. content 全文。"""
    return WxMaterialResponse(
        id=row.id,
        title=row.title,
        content=row.content,
        source_type=row.source_type,
        kb_chunk_id=row.kb_chunk_id,
        tags=_parse_tags(row.tags),
        is_used=row.is_used,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class WxMaterialService:
    """素材库业务逻辑。Multi-tenant 通过 ``current_user.tenant_id`` 隔离。"""

    # --- 手动录入 -----------------------------------------------------------

    def create_material(
        self, db: Session, *, current_user: User, payload: WxMaterialCreate,
    ) -> WxMaterial:
        """手动录入。``source_type`` 强制 ``'manual'`` — 防止 caller
        偷偷传 ``'kb'`` 但不提供 ``kb_chunk_id`` (那样会变成「来自 KB」
        的素材却没有 KB 来源, 误导排版环节)。

        同样的道理, ``kb_chunk_id`` 在 manual 录入时也可空:
        这是「operator 看到一段 KB 内容, 手动复制过来」的场景, 有
        chunk_id 是 bonus, 没有也 OK。
        """
        row = WxMaterial(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            title=payload.title,
            content=payload.content,
            source_type="manual",
            kb_chunk_id=payload.kb_chunk_id,
            tags=json.dumps(payload.tags) if payload.tags else None,
            is_used=False,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    # --- 查询 --------------------------------------------------------------

    def get_material(
        self, db: Session, *, current_user: User, material_id: int,
    ) -> WxMaterial:
        """Load a material scoped to ``current_user.tenant_id``.

        跨租户访问返 404 (而非 403), 防止 IDOR 信息泄露 —
        跟 ``AccountService.get_account`` 同模式。
        """
        row = db.query(WxMaterial).filter(
            WxMaterial.id == material_id,
            WxMaterial.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(404, "Material not found")
        return row

    def list_materials(
        self, db: Session, *, current_user: User,
        page: int = 1, page_size: int = 20,
        source_type: Optional[str] = None,
        tag: Optional[str] = None,
        title_search: Optional[str] = None,
    ) -> Tuple[List[WxMaterial], int]:
        """分页列表。可选 filter:
        - ``source_type``: 精确匹配 ('manual' / 'kb' / 'url')
        - ``tag``: JSON 包含, MySQL 8 用 ``JSON_CONTAINS`` —
          spec §3.5 设计的 JSON column。
          MVP 简化: 在 Python 端 fetch 完后 filter (tag 数量
          少, page_size 一般 20, 可接受)。V2 改 SQL。
        - ``title_search``: ``LIKE %x%`` 模糊匹配。
        """
        q = db.query(WxMaterial).filter(
            WxMaterial.tenant_id == current_user.tenant_id,
        )
        if source_type is not None:
            q = q.filter(WxMaterial.source_type == source_type)
        if title_search is not None and title_search.strip():
            q = q.filter(WxMaterial.title.like(f"%{title_search.strip()}%"))

        # tag filter 在 Python 端做, 因为 MySQL JSON_CONTAINS 在 tag
        # 含特殊字符时容易踩坑; 一次性 fetch 一页 (default 20) 内存
        # 可控。
        total = q.count()
        q = q.order_by(WxMaterial.created_at.desc())
        offset = (page - 1) * page_size
        rows = q.offset(offset).limit(page_size).all()

        if tag is not None:
            rows = [
                r for r in rows
                if _parse_tags(r.tags) is not None
                and tag in (_parse_tags(r.tags) or [])
            ]
        return rows, total

    # --- 删除 --------------------------------------------------------------

    def delete_material(
        self, db: Session, *, current_user: User, material_id: int,
    ) -> None:
        """Hard delete. 素材没有 soft-delete 概念:
        1. 素材无 FK 引用 (wx_drafts 不引用素材, 引用是单向的: 草稿手动
           复制内容, 没有外键)。
        2. 素材无审计价值 (不是发布记录)。
        3. 用户在 UI 上点删就是真删。
        """
        row = self.get_material(
            db, current_user=current_user, material_id=material_id,
        )
        db.delete(row)
        db.commit()

    # --- 从 KB 导入 --------------------------------------------------------

    def import_from_kb(
        self, db: Session, *, current_user: User,
        payload: WxMaterialImportFromKBRequest,
    ) -> Dict[str, Any]:
        """从 KB 检索结果批量创建素材。

        流程:
        1. 校验 kb 存在且属于当前 tenant (404 防 IDOR)
        2. 调 ``RetrievalPipeline.search`` (M28) 拉 top_k 条候选
        3. 遍历候选, 每条建一个 WxMaterial row
           - ``source_type='kb'``
           - ``kb_chunk_id`` 从 result['chunk_id'] 取 (int str);
             非整数就降级 None (不阻塞导入)
           - ``title`` 截 content 前 50 字符 + '…'
           - ``tags`` 默认 None, caller 可在 UI 上加
        4. MVP 不去重: 每次 import 都新建 (see module docstring)
        5. 返 ``{imported, skipped, materials}``

        Note: pipeline.search 是 **同步** 方法 (M28 设计) — service
        不用 async, 这跟 ``local_demo.search_knowledge_base`` 同步调
        用一致。
        """
        kb = db.query(KnowledgeBase).filter(
            KnowledgeBase.id == payload.kb_id,
            KnowledgeBase.tenant_id == current_user.tenant_id,
        ).first()
        if not kb:
            raise HTTPException(404, "Knowledge base not found")

        # 懒 import 避免在 import 阶段拉整个 ollama/httpx 客户端
        # (跟 local_demo.search_knowledge_base 同样的模式)
        from lumen_services.retrieval.pipeline import get_retrieval_pipeline

        model_config_id = kb.embedding_model_config_id or 0
        pipeline = get_retrieval_pipeline(
            kb_id=kb.id,
            model_config_id=model_config_id,
            db=db,
        )
        filter_expr = (
            f"tenant_id == {current_user.tenant_id} and kb_id == {kb.id}"
        )
        results = pipeline.search(
            query=payload.query,
            k=payload.top_k,
            filter_expr=filter_expr,
        )

        materials: List[WxMaterial] = []
        for r in results:
            # chunk_id 可能是 int (ES path) 或 str (FAISS path / 别的)
            chunk_id_raw = r.get("chunk_id") or r.get("id")
            chunk_id_int: Optional[int] = None
            if chunk_id_raw is not None:
                try:
                    chunk_id_int = int(chunk_id_raw)
                except (TypeError, ValueError):
                    # FAISS 路径 chunk_id 是 vector_id 字符串, 无法
                    # 关联到 document_chunks.id; 降级 None, 不阻塞导入。
                    log.debug(
                        "import_from_kb: non-int chunk_id %r (FAISS?), "
                        "storing with kb_chunk_id=None",
                        chunk_id_raw,
                    )
                    chunk_id_int = None

            content = r.get("content") or r.get("text") or ""
            if not content:
                # 跳过空内容候选 — 检索偶尔会返 0 长 text, 不存 DB
                # 也不计入 imported。
                continue

            # title 截前 50 字符 + "…" — UI 上能 hover 看全文,
            # 真要改可在 detail 页 inline rename (V2)
            title_source = content.strip().splitlines()[0] if content.strip() else content
            title = title_source[:50]
            if len(title_source) > 50:
                title = title + "…"

            row = WxMaterial(
                tenant_id=current_user.tenant_id,
                user_id=current_user.id,
                title=title or "(无标题)",
                content=content,
                source_type="kb",
                kb_chunk_id=chunk_id_int,
                tags=None,
                is_used=False,
            )
            db.add(row)
            materials.append(row)

        # 一次性 commit 走单事务;失败全 rollback
        if materials:
            db.commit()
            for m in materials:
                db.refresh(m)

        return {
            "imported": len(materials),
            # MVP 永远 0; V2 加去重时返真实 skipped 数
            "skipped": 0,
            "materials": [_to_response(m) for m in materials],
        }

    # --- 标签聚合 -----------------------------------------------------------

    def aggregate_tags(
        self, db: Session, *, current_user: User,
    ) -> List[str]:
        """返当前 tenant 内所有素材用过的 tag (去重 + 排序)。

        用途: UI 列表页 tag 过滤 dropdown 的 autocomplete 候选项。

        实现: Python 端 fetch 所有 (id, tags) → 内存 set 去重 → sort。
        MVP 接受 O(N); V2 用 SQL ``JSON_TABLE`` 在 DB 端做。
        """
        rows = db.query(WxMaterial.id, WxMaterial.tags).filter(
            WxMaterial.tenant_id == current_user.tenant_id,
        ).all()
        seen: set[str] = set()
        for _, tags_raw in rows:
            parsed = _parse_tags(tags_raw)
            if not parsed:
                continue
            for t in parsed:
                seen.add(t)
        return sorted(seen)
