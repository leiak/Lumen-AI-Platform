from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


class ClassificationBase(BaseModel):
    name: str
    description: Optional[str] = None
    keywords: List[str] = []


class ClassificationCreate(ClassificationBase):
    pass


class ClassificationUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None


class ClassificationResponse(ClassificationBase):
    id: int
    tenant_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnnotationBase(BaseModel):
    content: str
    classification_id: int


class AnnotationCreate(AnnotationBase):
    pass


class AnnotationResponse(AnnotationBase):
    id: int
    tenant_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QABase(BaseModel):
    question: str
    answer: str


class QACreate(QABase):
    pass


class QAUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None


class QAResponse(QABase):
    id: int
    tenant_id: Optional[int]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TrainRequest(BaseModel):
    classification_id: int


class TrainResponse(BaseModel):
    status: str
    model_path: Optional[str] = None
    accuracy: Optional[float] = None
    message: str
