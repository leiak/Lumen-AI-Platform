"""Pydantic schemas for /api/v1/ppt.

Spec: docs-internal/superpowers/specs/m35-ppt-generation.md
"""
from typing import Optional, List, Literal, Any
from pydantic import BaseModel, Field, model_validator


class PptGenerateRequest(BaseModel):
    conversation_id: int
    title: Optional[str] = None  # 不传则 LLM 自动生成
    content_range: Literal[0, 1, 5, 10, 20] = 10  # 0=全部, 1=最后1条
    include_charts: bool = False
    style: Literal["simple", "business", "academic"] = "simple"
    mode: Literal["frontend", "backend"] = "backend"


# --- PPT JSON Schema（两套渲染器共用）---

class ChartData(BaseModel):
    type: Literal["bar", "line", "pie"]
    title: str
    labels: List[str]
    datasets: List[dict]  # [{name: str, values: List[float]}]

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_data_field(cls, data: Any) -> Any:
        """兼容 LLM 输出的 ``{type, data: [{name, value}, ...]}`` 老格式。

        LLM 经常返回 ``{type: "bar", data: [{name: "A", value: 78}, ...]}`` 这种典型
        key-value 列表格式，缺少 spec 要求的 ``title/labels/datasets`` 字段。
        这里把它自动改写成标准格式：
          - title: 从 slide.title 兜底，data 里没有时用 "数据概览"
          - labels: 从每个 data 项的 name 字段收集
          - datasets: 单一数据集 ``{name: "数值", values: [...]}``
        """
        if not isinstance(data, dict):
            return data
        if "labels" in data and "datasets" in data:
            return data  # 已是标准格式，跳过
        if "data" not in data or not isinstance(data.get("data"), list):
            return data  # 没有 data 字段，交给 Pydantic 报标准 missing
        legacy = data["data"]
        labels = [str(item.get("name", item.get("label", ""))) for item in legacy]
        values = [item.get("value", item.get("y", 0)) for item in legacy]
        return {
            "type": data.get("type", "bar"),
            "title": data.get("title") or "数据概览",
            "labels": labels,
            "datasets": [{"name": "数值", "values": values}],
        }


class Slide(BaseModel):
    layout: Literal["title_only", "title_content", "two_column", "blank", "chart"]
    title: Optional[str] = None
    content: Optional[List[str]] = None
    leftContent: Optional[List[str]] = None
    rightContent: Optional[List[str]] = None
    chart: Optional[ChartData] = None
    notes: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_nested_lists(cls, data: Any) -> Any:
        """防御：LLM 有时输出 leftContent:[[str,str],...]，展平成字符串。"""
        if not isinstance(data, dict):
            return data
        for field in ("content", "leftContent", "rightContent"):
            if field in data and isinstance(data[field], list):
                flat = []
                for item in data[field]:
                    if isinstance(item, list):
                        flat.append(" | ".join(str(x) for x in item))
                    else:
                        flat.append(str(item))
                data[field] = flat
        return data


class PptSchema(BaseModel):
    title: str
    subtitle: Optional[str] = None
    author: Optional[str] = "Lumen AI"
    slides: List[Slide]


# --- API 响应 ---

class PptTaskResponse(BaseModel):
    task_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    file_url: Optional[str] = None
    error: Optional[str] = None


class PptFrontendResponse(BaseModel):
    schema: PptSchema
