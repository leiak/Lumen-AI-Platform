"""M32 公众号助手 - 素材库 HTTP endpoints.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1 / §4.2

CP2 范围: 5 个 endpoint
- GET    /                          分页列表 + tag/source_type/title 过滤
- GET    /{material_id}             详情 — 全 content (2026-06-29 补,供草稿编辑器
                                    「插入素材」picker 调 materialApi.get(id) 拿全文)
- POST   /                          手动录入 (source_type='manual')
- POST   /from-kb                   从 KB 导入 (走 M28 RetrievalPipeline)
- DELETE /{material_id}             hard delete

**路由顺序铁律** (CLAUDE.md / MEMORY.md 多次踩坑, M16):
``/from-kb`` 静态路径必须注册在 ``/{material_id}`` 之前 —
否则 FastAPI 会把 ``"from-kb"`` 匹配成 ``material_id="from-kb"``
然后再 int() 失败 422。CP1 accounts.py 没这个坑, 是因为 accounts
没有静态 sub-path, 这里有, 所以顺序敏感。

Cross-tenant 隔离由 ``WxMaterialService.get_material`` 内部完成:
跨租户 row 返 404 (不是 403), 防 IDOR 信息泄露。

注册位置: ``backend/app/api/v1/__init__.py`` (T13 责任, 另一个
subagent 跑)。本文件 self-contained 可独立 import。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.wx_publisher import (
    WxMaterialCreate,
    WxMaterialImportFromKBRequest,
    WxMaterialImportResult,
    WxMaterialListItem,
    WxMaterialResponse,
)
from lumen_services.wx_publisher.material_service import (
    WxMaterialService,
    _to_list_item,
    _to_response,
)

log = logging.getLogger(__name__)

# Prefix matches spec §4.1. The trailing ``/materials`` lets
# the T13 wiring add a single ``include_router`` call at
# ``/api/v1/wx-publisher`` alongside the other 4 sibling routers.
router = APIRouter(prefix="/wx-publisher/materials", tags=["wx-publisher"])

# Module-level service instance (跟 accounts.py / M14 / M21 / M22
# 同模式 — services are stateless wrappers so a singleton is safe)。
service = WxMaterialService()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
#
# **路由顺序铁律**:
# FastAPI 按声明顺序匹配;``/from-kb`` 是静态字面路径, 必须排在
# ``/{material_id}`` 动态路径之前, 否则 ``DELETE /from-kb`` 会
# 先被 ``/{material_id}`` 截到然后 int() 失败。
# 同样的反模式在 M16 skill_marketplace 路由顺序里也出现过, 这里
# 我们按 **POST 在前 GET 在后, 静态路径在动态路径之前** 排:
#
#   POST /from-kb    (static, body)
#   POST /            (root create)
#   GET  /            (list)
#   DELETE /{material_id}
#
# 注意 ``POST /from-kb`` 排在 ``POST /`` 之前 — 即使它们都是 POST
# 也不会冲突, 排前面纯粹是因为静态路径优先, 利于排错。

@router.post(
    "/from-kb",
    response_model=SingleResponse[WxMaterialImportResult],
    status_code=201,
)
def import_from_kb(
    data: WxMaterialImportFromKBRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从 KB 检索结果批量导入素材。返回 ``{imported, skipped, materials}``。

    流程: 校验 KB 归属 → 调 ``RetrievalPipeline.search`` (M28) →
    遍历候选建 WxMaterial rows → 一次性 commit。

    MVP 行为: 每次 import 都新建行, ``skipped=0`` (无去重, V2 加)。
    """
    try:
        result = service.import_from_kb(
            db, current_user=current_user, payload=data,
        )
    except Exception as e:
        # 让 HTTPException (404 KB not found 等) 正常冒泡
        from fastapi import HTTPException
        if isinstance(e, HTTPException):
            raise
        log.exception("import_from_kb: unexpected error")
        raise HTTPException(500, f"Failed to import from KB: {e}")
    return SingleResponse(
        data=WxMaterialImportResult(
            imported=result["imported"],
            skipped=result["skipped"],
            materials=result["materials"],
        ),
    )


@router.post("/", response_model=SingleResponse[WxMaterialResponse], status_code=201)
def create_material(
    data: WxMaterialCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手动录入素材。``source_type`` 强制 ``'manual'`` (service 层处理) —
    caller 传什么都覆盖, 防止手动接口偷偷伪装成 KB 来源。
    """
    row = service.create_material(db, current_user=current_user, payload=data)
    return SingleResponse(data=_to_response(row))


@router.get("/", response_model=PaginatedResponse[WxMaterialListItem])
def list_materials(
    page: int = 1,
    page_size: int = 20,
    source_type: Optional[str] = None,
    tag: Optional[str] = None,
    title: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页列出当前 tenant 的素材。3 个可选 filter:
    - ``source_type``: 精确匹配 'manual' / 'kb' / 'url'
    - ``tag``: JSON 包含 (Python 端 filter, MVP 简化)
    - ``title``: ``LIKE %x%`` 模糊匹配
    """
    rows, total = service.list_materials(
        db, current_user=current_user,
        page=page, page_size=page_size,
        source_type=source_type, tag=tag, title_search=title,
    )
    return PaginatedResponse(
        data=[_to_list_item(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


# 2026-06-29 — 草稿编辑器「插入素材」流程需要拿全 content (list 只返 200 字
# content_preview)。前端 materialApi.get(id) 调的就是这里。
# 静态路径 (上文的 ``GET /``) 必须先于动态 ``{material_id}`` — 跟 DELETE 同。
@router.get("/{material_id}", response_model=SingleResponse[WxMaterialResponse])
def get_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get 素材详情(全 content)。

    跨租户 IDOR 走 service.get_material — 返 404 不是 403(防信息泄露)。
    """
    row = service.get_material(
        db, current_user=current_user, material_id=material_id,
    )
    return SingleResponse(data=_to_response(row))


@router.delete("/{material_id}", status_code=204)
def delete_material(
    material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard delete 素材。素材无 FK 引用, 无审计价值, 真删无副作用。"""
    service.delete_material(
        db, current_user=current_user, material_id=material_id,
    )
    return None  # 204 No Content
