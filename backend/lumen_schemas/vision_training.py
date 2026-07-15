from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

class VisionClassificationBase(BaseModel):
    name: str
    description: Optional[str] = None

class VisionClassificationCreate(VisionClassificationBase):
    pass

class VisionClassificationResponse(VisionClassificationBase):
    id: int
    tenant_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VisionImageBase(BaseModel):
    filename: str
    file_path: str
    classification_id: int

class VisionImageCreate(VisionImageBase):
    pass

class VisionImageResponse(VisionImageBase):
    id: int
    features: Optional[dict]
    tenant_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VisionTrainRequest(BaseModel):
    classification_id: int

class VisionTrainResponse(BaseModel):
    status: str
    message: str
    accuracy: Optional[float] = None
