# backend/app/api/v1/nlp.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.nlp_training import NLPTrainingClassification, NLPAnnotation, NLPQA
from lumen_schemas.nlp_training import (
    ClassificationCreate, ClassificationUpdate, ClassificationResponse,
    AnnotationCreate, AnnotationResponse,
    QACreate, QAUpdate, QAResponse,
    TrainRequest, TrainResponse
)
from lumen_schemas.common import SingleResponse, PaginatedResponse

router = APIRouter(prefix="/nlp", tags=["nlp"])

# Classification endpoints
@router.get("/classification/", response_model=PaginatedResponse[ClassificationResponse])
async def list_classifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    start = (page - 1) * page_size
    total = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).count()
    items = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).offset(start).limit(page_size).all()
    return PaginatedResponse(
        data=[ClassificationResponse.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size
    )

@router.post("/classification/", response_model=SingleResponse[ClassificationResponse])
async def create_classification(
    data: ClassificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = NLPTrainingClassification(
        **data.model_dump(),
        tenant_id=current_user.tenant_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=ClassificationResponse.model_validate(item))

@router.get("/classification/{id}", response_model=SingleResponse[ClassificationResponse])
async def get_classification(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.id == id,
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Classification not found")
    return SingleResponse(data=ClassificationResponse.model_validate(item))

@router.put("/classification/{id}", response_model=SingleResponse[ClassificationResponse])
async def update_classification(
    id: int,
    data: ClassificationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.id == id,
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Classification not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=ClassificationResponse.model_validate(item))

@router.delete("/classification/{id}")
async def delete_classification(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.id == id,
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Classification not found")
    db.delete(item)
    db.commit()
    return SingleResponse(message="Deleted successfully")

# Annotation endpoints
# M-FIX-2026-06-25: classification_id 接受空字符串 → None
# 前端 (training/nlp list) 会发 `?classification_id=` 空值作"未筛选"标记,
# FastAPI 默认 int 解析空串抛 422 → 列表页打不开。改为 str 接参 + 手动转 int。
@router.get("/annotation/", response_model=PaginatedResponse[AnnotationResponse])
async def list_annotations(
    classification_id: Optional[str] = Query(None, description="筛选分类 ID,空字符串 = 不筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 空字符串 / 非数字 → None (与前端"未筛选"语义对齐)
    cid: Optional[int] = None
    if classification_id and classification_id.strip():
        try:
            cid = int(classification_id)
        except (ValueError, TypeError):
            cid = None

    start = (page - 1) * page_size
    base_query = db.query(NLPAnnotation).filter(NLPAnnotation.tenant_id == current_user.tenant_id)
    if cid is not None:
        base_query = base_query.filter(NLPAnnotation.classification_id == cid)
    total = base_query.count()
    items = base_query.offset(start).limit(page_size).all()
    return PaginatedResponse(
        data=[AnnotationResponse.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size
    )

@router.post("/annotation/", response_model=SingleResponse[AnnotationResponse])
async def create_annotation(
    data: AnnotationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = NLPAnnotation(
        **data.model_dump(),
        tenant_id=current_user.tenant_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=AnnotationResponse.model_validate(item))

@router.delete("/annotation/{id}")
async def delete_annotation(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(NLPAnnotation).filter(
        NLPAnnotation.id == id,
        NLPAnnotation.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Annotation not found")
    db.delete(item)
    db.commit()
    return SingleResponse(message="Deleted successfully")

# QA endpoints
@router.get("/qa/", response_model=PaginatedResponse[QAResponse])
async def list_qa(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    start = (page - 1) * page_size
    total = db.query(NLPQA).filter(NLPQA.tenant_id == current_user.tenant_id).count()
    items = db.query(NLPQA).filter(NLPQA.tenant_id == current_user.tenant_id).offset(start).limit(page_size).all()
    return PaginatedResponse(
        data=[QAResponse.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size
    )

@router.post("/qa/", response_model=SingleResponse[QAResponse])
async def create_qa(
    data: QACreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = NLPQA(
        **data.model_dump(),
        tenant_id=current_user.tenant_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=QAResponse.model_validate(item))

@router.put("/qa/{id}", response_model=SingleResponse[QAResponse])
async def update_qa(
    id: int,
    data: QAUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(NLPQA).filter(
        NLPQA.id == id,
        NLPQA.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="QA not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=QAResponse.model_validate(item))

@router.delete("/qa/{id}")
async def delete_qa(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(NLPQA).filter(
        NLPQA.id == id,
        NLPQA.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="QA not found")
    db.delete(item)
    db.commit()
    return SingleResponse(message="Deleted successfully")

# Training endpoints
@router.post("/train", response_model=SingleResponse)
async def train_model(
    data: TrainRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """训练分类模型"""
    from lumen_services.nlp_training_service import NLPTrainingService

    # Verify classification exists and belongs to tenant
    classification = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.id == data.classification_id,
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).first()
    if not classification:
        raise HTTPException(status_code=404, detail="Classification not found")

    service = NLPTrainingService()
    try:
        result = service.train_classification(data.classification_id, db, current_user.tenant_id)
        return SingleResponse(data=result)
    except Exception as e:
        return SingleResponse(message=str(e))

@router.post("/predict")
async def predict(
    text: str,
    classification_id: int,
    current_user: User = Depends(get_current_user)
):
    """预测分类"""
    from lumen_services.nlp_training_service import NLPTrainingService

    # Verify classification belongs to tenant
    classification = db.query(NLPTrainingClassification).filter(
        NLPTrainingClassification.id == classification_id,
        NLPTrainingClassification.tenant_id == current_user.tenant_id
    ).first()
    if not classification:
        raise HTTPException(status_code=404, detail="Classification not found")

    service = NLPTrainingService()
    result = service.predict(text, classification_id, current_user.tenant_id)
    return SingleResponse(data=result)