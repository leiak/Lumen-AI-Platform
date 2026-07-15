from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.vision_training import VisionClassification, VisionImage
from lumen_schemas.vision_training import (
    VisionClassificationCreate, VisionClassificationResponse,
    VisionImageCreate, VisionImageResponse
)
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.vision_training_service import VisionTrainingService
import os
import uuid

router = APIRouter(prefix="/vision", tags=["vision"])

# Classification endpoints
@router.get("/classification/", response_model=PaginatedResponse[VisionClassificationResponse])
async def list_classifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    start = (page - 1) * page_size
    total = db.query(VisionClassification).filter(
        VisionClassification.tenant_id == current_user.tenant_id
    ).count()
    items = db.query(VisionClassification).filter(
        VisionClassification.tenant_id == current_user.tenant_id
    ).offset(start).limit(page_size).all()
    return PaginatedResponse(
        data=[VisionClassificationResponse.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size
    )

@router.post("/classification/", response_model=SingleResponse[VisionClassificationResponse])
async def create_classification(
    data: VisionClassificationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = VisionClassification(
        **data.model_dump(),
        tenant_id=current_user.tenant_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=VisionClassificationResponse.model_validate(item))

@router.delete("/classification/{id}")
async def delete_classification(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(VisionClassification).filter(
        VisionClassification.id == id,
        VisionClassification.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Classification not found")
    db.delete(item)
    db.commit()
    return SingleResponse(message="Deleted successfully")

# Image endpoints
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

@router.post("/image/", response_model=SingleResponse[VisionImageResponse])
async def upload_image(
    classification_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify classification exists and belongs to tenant
    classification = db.query(VisionClassification).filter(
        VisionClassification.id == classification_id,
        VisionClassification.tenant_id == current_user.tenant_id
    ).first()
    if not classification:
        raise HTTPException(status_code=404, detail="Classification not found")

    # Validate content type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="File type not allowed")

    # Read and validate file size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large")

    # Save file with sanitized filename
    upload_dir = f"./uploads/vision/{current_user.tenant_id}/{classification_id}"
    os.makedirs(upload_dir, exist_ok=True)
    safe_filename = os.path.basename(file.filename.replace("\\", "/"))
    unique_filename = f"{uuid.uuid4().hex}_{safe_filename}"
    file_path = os.path.join(upload_dir, unique_filename)

    with open(file_path, "wb") as f:
        f.write(contents)

    # Create record
    item = VisionImage(
        filename=unique_filename,
        file_path=file_path,
        classification_id=classification_id,
        tenant_id=current_user.tenant_id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return SingleResponse(data=VisionImageResponse.model_validate(item))

@router.get("/image/", response_model=PaginatedResponse[VisionImageResponse])
async def list_images(
    classification_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    start = (page - 1) * page_size
    base_query = db.query(VisionImage).filter(VisionImage.tenant_id == current_user.tenant_id)
    if classification_id is not None:
        base_query = base_query.filter(VisionImage.classification_id == classification_id)
    total = base_query.count()
    items = base_query.offset(start).limit(page_size).all()
    return PaginatedResponse(
        data=[VisionImageResponse.model_validate(i) for i in items],
        total=total, page=page, page_size=page_size
    )

@router.delete("/image/{id}")
async def delete_image(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    item = db.query(VisionImage).filter(
        VisionImage.id == id,
        VisionImage.tenant_id == current_user.tenant_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Image not found")
    # Delete file (continue with DB deletion even if file removal fails)
    try:
        if os.path.exists(item.file_path):
            os.remove(item.file_path)
    except OSError:
        pass  # File may already be deleted, continue with DB deletion
    db.delete(item)
    db.commit()
    return SingleResponse(message="Deleted successfully")


# Training and prediction endpoints
@router.post("/train")
async def train_model(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    classification_id = data.get("classification_id")
    if classification_id is None:
        raise HTTPException(status_code=400, detail="classification_id is required")

    service = VisionTrainingService()
    result = service.train_classification(classification_id, db, current_user.tenant_id)
    return SingleResponse(data=result)


@router.post("/predict")
async def predict_image(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    image_path = data.get("image_path")
    image_id = data.get("image_id")

    if image_path is None and image_id is None:
        raise HTTPException(status_code=400, detail="image_path or image_id is required")

    # If image_id is provided, get the image_path from database
    if image_id is not None:
        image = db.query(VisionImage).filter(
            VisionImage.id == image_id,
            VisionImage.tenant_id == current_user.tenant_id
        ).first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        image_path = image.file_path

    # Get classification_id from data or from the image's classification
    classification_id = data.get("classification_id")
    if classification_id is None and image_id is not None:
        classification_id = image.classification_id

    service = VisionTrainingService()
    result = service.predict(image_path, classification_id, current_user.tenant_id)
    return SingleResponse(data=result)