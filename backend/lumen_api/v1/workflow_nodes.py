"""P2 节点 preview 端点:测试-不保存-返回原始结果。

只跑节点 _run() 一次,不调 error_strategy/retry。异常 → 返回 500 + 错误信息。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_core.workflow.nodes.http import HTTPNode
from lumen_core.workflow.nodes.knowledge_retrieval import KnowledgeRetrievalNode
from lumen_core.workflow.nodes.template_transform import TemplateTransformNode
from lumen_core.workflow.variable_pool import VariablePool
from lumen_models.user import User
from lumen_schemas.common import SingleResponse

router = APIRouter(prefix="/workflows/nodes", tags=["workflow-nodes"])


class HTTPPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}
    body_type: str = "none"
    body: str | dict = ""
    auth_type: str = "none"
    auth_config: dict[str, str] = {}
    verify_ssl: bool = True
    follow_redirects: bool = True


class HTTPPreviewResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: Any
    error: str | None = None


@router.post("/http/preview", response_model=SingleResponse[HTTPPreviewResponse])
async def preview_http(
    payload: HTTPPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SingleResponse[HTTPPreviewResponse]:
    pool = VariablePool()
    node = HTTPNode(
        node_id="preview",
        config=payload.model_dump(),
        pool=pool, db=db, tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
    )
    try:
        result = await node._run()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"HTTP preview failed: {e}")
    return SingleResponse(
        code=200,
        message="ok",
        data=HTTPPreviewResponse(
            status_code=result.output_values.get("status_code", 0),
            headers=result.output_values.get("headers", {}),
            body=result.output_values.get("body"),
            error=result.output_values.get("error"),
        ),
    )


class KBPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    kb_id: int
    query: str
    top_k: int = 5
    score_threshold: float = 0.0


class KBPreviewResponse(BaseModel):
    chunks: list[dict]
    count: int
    error: str | None = None


@router.post(
    "/knowledge-retrieval/preview",
    response_model=SingleResponse[KBPreviewResponse],
)
async def preview_kb(
    payload: KBPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SingleResponse[KBPreviewResponse]:
    pool = VariablePool()
    node = KnowledgeRetrievalNode(
        node_id="preview",
        config=payload.model_dump(),
        pool=pool, db=db, tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
    )
    try:
        result = await node._run()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KB preview failed: {e}")
    return SingleResponse(
        code=200,
        message="ok",
        data=KBPreviewResponse(
            chunks=result.output_values.get("chunks", []),
            count=result.output_values.get("count", 0),
            error=result.output_values.get("error"),
        ),
    )


class TemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str
    sample_context: dict[str, Any] = {}


class TemplatePreviewResponse(BaseModel):
    output: str
    error: str | None = None


@router.post(
    "/template-transform/preview",
    response_model=SingleResponse[TemplatePreviewResponse],
)
async def preview_template(
    payload: TemplatePreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SingleResponse[TemplatePreviewResponse]:
    pool = VariablePool()
    for k, v in (payload.sample_context or {}).items():
        # Treat top-level keys as node_ids, inner dict as vars
        if isinstance(v, dict):
            for vk, vv in v.items():
                pool.add([k, vk], vv)
        else:
            pool.add([k, "value"], v)
    node = TemplateTransformNode(
        node_id="preview",
        config={"template": payload.template},
        pool=pool, db=db, tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
    )
    try:
        result = await node._run()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Template preview failed: {e}"
        )
    return SingleResponse(
        code=200,
        message="ok",
        data=TemplatePreviewResponse(
            output=result.output_values.get("output", ""),
            error=result.output_values.get("error"),
        ),
    )
