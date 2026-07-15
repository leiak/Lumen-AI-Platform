from pydantic import BaseModel
from typing import Optional, Generic, TypeVar

T = TypeVar("T")


class ResponseBase(BaseModel):
    code: int = 200
    message: str = "Success"


class PaginatedResponse(ResponseBase, Generic[T]):
    data: list[T]
    total: int
    page: int
    page_size: int


class SingleResponse(ResponseBase, Generic[T]):
    data: Optional[T] = None
