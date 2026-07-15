"""Pydantic schemas for /api/v1/text2sql and /api/v1/text2sql/datasources.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §4

Conventions (mirror the M22 image-generation schemas):

- All request / response models live here; the SQLAlchemy ORM
  (``app/models/text2sql.py``) stays in the persistence layer.
- List / detail projections strip the heavy ``rows_json`` /
  ``columns_json`` blobs from the list payload — those are only
  embedded in the detail view, where the user explicitly opened a
  historical query.
- Boolean flags use ``int`` (0/1) to match the MySQL TINYINT(1)
  columns; the schema keeps them as ``bool`` for the API.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# DataSource CRUD                                                             #
# --------------------------------------------------------------------------- #


class Text2SqlDataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    db_name: str = Field(default="ai_platform", max_length=64)
    table_allowlist: Optional[List[str]] = None
    field_allowlist: Optional[Dict[str, List[str]]] = None
    max_rows: int = Field(default=100, ge=1, le=10000)
    timeout_ms: int = Field(default=5000, ge=100, le=60000)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_active: bool = True


class Text2SqlDataSourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    db_name: Optional[str] = Field(default=None, max_length=64)
    table_allowlist: Optional[List[str]] = None
    field_allowlist: Optional[Dict[str, List[str]]] = None
    max_rows: Optional[int] = Field(default=None, ge=1, le=10000)
    timeout_ms: Optional[int] = Field(default=None, ge=100, le=60000)
    description: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None


class Text2SqlDataSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    db_name: str
    table_allowlist: Optional[List[str]] = None
    field_allowlist: Optional[Dict[str, List[str]]] = None
    max_rows: int
    timeout_ms: int
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Ask request / response                                                      #
# --------------------------------------------------------------------------- #


class Text2SqlAskRequest(BaseModel):
    """Body for ``POST /api/v1/text2sql/ask``."""
    data_source_id: int
    question: str = Field(min_length=1, max_length=2000)
    # If true, return immediately with a pending row and run the
    # engine in the background. The caller can poll
    # ``GET /history/{id}`` for the result.
    async_run: bool = False


class Text2SqlAskResponse(BaseModel):
    """Returned by the sync path. ``status="pending"`` is impossible here
    because the sync path waits for the engine to finish.
    """
    query_id: int
    status: str  # success | rejected | failed
    generated_sql: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    explanation: Optional[str] = None
    confidence: Optional[int] = None
    attempts: int = 1
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None


# --------------------------------------------------------------------------- #
# History list / detail                                                       #
# --------------------------------------------------------------------------- #


class Text2SqlHistoryItem(BaseModel):
    """Row in the history list — strips the heavy ``rows_json`` blob."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    data_source_id: int
    question: str
    question_preview: str
    status: str
    row_count: Optional[int] = None
    attempts: int = 1
    duration_ms: Optional[int] = None
    error_type: Optional[str] = None
    created_at: datetime


class Text2SqlDetail(BaseModel):
    """Full detail of a historical query."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    user_id: int
    data_source_id: int
    question: str
    generated_sql: Optional[str] = None
    status: str
    attempts: int
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: Optional[int] = None
    truncated: bool = False
    explanation: Optional[str] = None
    confidence: Optional[int] = None
    duration_ms: Optional[int] = None
    generate_call_id: Optional[str] = None
    explain_call_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Schema browser                                                              #
# --------------------------------------------------------------------------- #


class Text2SqlSchemaResponse(BaseModel):
    """Return value of ``GET /api/v1/text2sql/schema``."""
    data_source_id: int
    db_name: str
    table_count: int
    schema_text: str
    tables: List[Dict[str, Any]] = Field(default_factory=list)
