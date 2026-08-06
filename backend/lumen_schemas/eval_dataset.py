"""M37.1: Pydantic schemas for /api/v1/eval/datasets/*.

All schemas follow project conventions:
- ``Optional[X] = None`` for nullable fields
- ``Field(min_length, max_length)`` for string constraints
- ``Literal[...]`` for enum values (project house style — see stock_asset.py)
- ``ConfigDict(from_attributes=True)`` on Read schemas so the service layer
  can construct them straight from the ORM row (``.from_orm``-style)
- datetimes are timezone-naive UTC by convention (project-wide)
- ``BulkImportResponse`` carries ``partial_errors`` for the 207 Partial
  Content path — single bad row doesn't fail the whole batch (see
  Risk § "bulk import 错误 fail-all" in m37-plan.md)

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enum Literals
# ---------------------------------------------------------------------------

EvalDatasetSource = Literal["manual", "imported", "synthetic"]
EvalDatasetCategory = Literal[
    "factual", "reasoning", "multi_hop", "keyword_heavy", "out_of_scope"
]
EvalDatasetDifficulty = Literal["easy", "medium", "hard"]


# ---------------------------------------------------------------------------
# EvalDataset (parent) schemas
# ---------------------------------------------------------------------------

class EvalDatasetBase(BaseModel):
    """公共字段。Create / Update 共用,Read 通过子 schema 表达。"""

    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)


class EvalDatasetCreate(EvalDatasetBase):
    """Body for ``POST /api/v1/eval/datasets``.

    ``kb_id`` 必填 — 数据集必须绑一个 KB,检索指标才有意义。
    ``tenant_id`` **不接受** —— 由 service 层从当前 user 拿;builtin
    数据集由 seed 脚本单独创建(直接走 ORM,绕过 schema)。
    """

    kb_id: int = Field(ge=1)
    source: EvalDatasetSource = "manual"


class EvalDatasetUpdate(BaseModel):
    """Body for ``PUT /api/v1/eval/datasets/{id}`` — 所有字段 Optional。

    注意 ``kb_id`` 不允许改 —— 数据集一旦建好跟 KB 绑定(评测时 KB 内容变了,
    检索指标变了,但 query / expected_doc_ids 假设的关系不变;改了 KB 等于
    让 expected_doc_ids 指错文档,语义破坏)。
    """

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    source: Optional[EvalDatasetSource] = None
    is_active: Optional[int] = None  # 1 启用 / 0 停用


class EvalDatasetListItem(BaseModel):
    """列表页 row shape — 轻量,不含 description 和 items。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kb_id: int
    tenant_id: Optional[int] = None  # NULL = builtin
    name: str
    source: EvalDatasetSource
    is_active: int
    # ``item_count`` 由 service 层在 list 查询时 ``COUNT(*)`` 填充,
    # 不存在 ORM 列上,故 Read schema 不暴露它,ListItem 这层用 Optional
    item_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class EvalDatasetRead(EvalDatasetListItem):
    """详情 shape —— ListItem + description + created_by。"""

    description: Optional[str] = None
    created_by: Optional[int] = None


# ---------------------------------------------------------------------------
# EvalDatasetItem (child) schemas
# ---------------------------------------------------------------------------

class EvalDatasetItemBase(BaseModel):
    """单条 query + 标注的公共字段。"""

    query: str = Field(min_length=1)
    expected_doc_ids: List[int] = Field(default_factory=list)
    expected_answer: Optional[str] = None
    answer_keywords: Optional[List[str]] = None
    category: Optional[EvalDatasetCategory] = None
    difficulty: Optional[EvalDatasetDifficulty] = "medium"
    notes: Optional[str] = None


class EvalDatasetItemCreate(EvalDatasetItemBase):
    """Body for ``POST /api/v1/eval/datasets/{id}/items``(单条加 item)。"""

    pass  # 全 Optional 沿用 Base


class EvalDatasetItemBulkImportRow(EvalDatasetItemBase):
    """单行 bulk import row — category/difficulty Literal 严格校验。

    单行 try/except 由 service 层做,失败行写 ``partial_errors``,
    整个 batch 不 fail-all(返 207 Partial Content)。
    """


class EvalDatasetItemBulkImportRequest(BaseModel):
    """Body for ``POST /api/v1/eval/datasets/{id}/items/bulk-import``。

    ``rows`` 用 ``List[Dict[str, Any]]`` 而非 ``List[EvalDatasetItemBulkImportRow]``
    是有意的设计 —— 单行 Pydantic 校验(category/difficulty Literal)下沉到
    service 层做 per-row try/except,失败的行进 ``partial_errors``,整批仍然
    200 返回。若在这里用强类型 ``List[EvalDatasetItemBulkImportRow]``,
    FastAPI 会在 HTTP 层就把整批 body 校验完,任意一行 Literal 失败 → 422
    Unprocessable Entity,partial_errors 机制根本跑不起来。
    """

    rows: List[Dict[str, Any]] = Field(min_length=1)


class EvalDatasetItemBulkImportError(BaseModel):
    """bulk import 单行错误细节 —— 给前端表格"哪一行挂了"用。"""

    row_index: int  # 0-based,跟原始 rows 列表下标一致
    error: str  # Pydantic ValidationError 信息或 service 层自定义


class EvalDatasetItemBulkImportResponse(BaseModel):
    """bulk import 响应 — 部分成功也返 200 / 207,前端用 ``imported_count`` + ``partial_errors`` 显示。"""

    imported_count: int
    failed_count: int
    partial_errors: List[EvalDatasetItemBulkImportError] = Field(default_factory=list)


class EvalDatasetItemRead(EvalDatasetItemBase):
    """单条 item 详情 shape —— 给 GET /datasets/{id}?include_items=true 用。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: int
    created_at: datetime