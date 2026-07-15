"""HTTP endpoints for PPT generation.

Spec: docs-internal/superpowers/specs/m35-ppt-generation.md
"""
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.ppt_task import PptTask
from lumen_models.user import User
from lumen_schemas.common import SingleResponse
from lumen_schemas.ppt import PptGenerateRequest, PptSchema, PptTaskResponse
from lumen_tasks.ppt_task import generate_ppt_task

router = APIRouter(prefix="/ppt", tags=["ppt"])


def _build_task_response(task: PptTask) -> PptTaskResponse:
    return PptTaskResponse(
        task_id=task.task_id,
        status=task.status,  # type: ignore[arg-type]
        file_url=task.file_url,
        error=task.error,
    )


@router.post("/generate", response_model=SingleResponse[dict])
def generate_ppt(
    data: PptGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a PPT generation task.

    - mode=frontend: LLM generates PPT JSON synchronously, returns schema directly.
    - mode=backend: creates task, returns task_id for polling.
    """
    if data.mode == "frontend":
        # 同步模式：直接调 LLM 生成 JSON 返回给前端
        from lumen_services.ppt_service import PptService
        service = PptService()
        try:
            schema = service.build_schema(
                db=db,
                tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
                user_id=current_user.id,  # type: ignore[arg-type]
                conversation_id=data.conversation_id,
                title=data.title,
                content_range=data.content_range,
                include_charts=data.include_charts,
                style=data.style,
            )
            return SingleResponse(data={"schema": schema.model_dump()})
        except Exception as e:
            raise HTTPException(500, f"PPT 生成失败: {e}")

    # 后端高精度模式：创建任务，异步执行
    task_id = str(uuid.uuid4())

    # 保存任务记录
    task = PptTask(
        task_id=task_id,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        conversation_id=data.conversation_id,
        title=data.title or "PPT 演示文稿",
        status="pending",
        mode="backend",
        style=data.style,
        include_charts=1 if data.include_charts else 0,
    )
    db.add(task)
    db.commit()

    # 发布 Celery 任务
    generate_ppt_task.delay(
        task_id=task_id,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        conversation_id=data.conversation_id,
        title=data.title or "PPT 演示文稿",
        content_range=data.content_range,
        include_charts=data.include_charts,
        style=data.style,
    )

    return SingleResponse(data={"task_id": task_id})


@router.get("/tasks/{task_id}", response_model=SingleResponse[PptTaskResponse])
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Poll task status."""
    task = db.query(PptTask).filter(
        PptTask.task_id == task_id,
        PptTask.tenant_id == current_user.tenant_id,  # type: ignore[arg-type]
    ).first()
    if not task:
        raise HTTPException(404, "Task not found")
    return SingleResponse(data=_build_task_response(task))


@router.get("/tasks/{task_id}/file")
def download_ppt(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the generated .pptx file."""
    from lumen_core.config import settings

    task = db.query(PptTask).filter(
        PptTask.task_id == task_id,
        PptTask.tenant_id == current_user.tenant_id,  # type: ignore[arg-type]
    ).first()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != "completed":
        raise HTTPException(400, "PPT 还未生成完成")
    if not task.file_url:
        raise HTTPException(404, "文件不存在")

    abs_path = settings.STORAGE_DIR / task.file_url.lstrip("/")
    if not abs_path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(abs_path, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", filename=f"{task.title}.pptx")
