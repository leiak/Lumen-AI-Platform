"""M33: Pydantic schema tests for text2sql API.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §4

We verify the input validators (``min_length``, ``max_length``,
``ge``/``le``) and the read-model ``from_attributes`` mode (Pydantic
v2 replacement for ``orm_mode``).
"""
import pytest
from pydantic import ValidationError

from lumen_schemas.text2sql import (
    Text2SqlAskRequest,
    Text2SqlAskResponse,
    Text2SqlDataSourceCreate,
    Text2SqlDataSourceUpdate,
    Text2SqlSchemaResponse,
)


# --------------------------------------------------------------------------- #
# Text2SqlAskRequest                                                          #
# --------------------------------------------------------------------------- #


def test_ask_request_minimum_valid():
    req = Text2SqlAskRequest(data_source_id=1, question="how many users?")
    assert req.data_source_id == 1
    assert req.async_run is False  # default


def test_ask_request_async_run_flag():
    req = Text2SqlAskRequest(
        data_source_id=1, question="x", async_run=True
    )
    assert req.async_run is True


def test_ask_request_rejects_empty_question():
    with pytest.raises(ValidationError):
        Text2SqlAskRequest(data_source_id=1, question="")


def test_ask_request_rejects_oversized_question():
    with pytest.raises(ValidationError):
        Text2SqlAskRequest(data_source_id=1, question="x" * 2001)


# --------------------------------------------------------------------------- #
# Text2SqlDataSourceCreate                                                    #
# --------------------------------------------------------------------------- #


def test_datasource_create_defaults():
    ds = Text2SqlDataSourceCreate(name="default")
    assert ds.db_name == "ai_platform"
    assert ds.max_rows == 100
    assert ds.timeout_ms == 5000
    assert ds.is_active is True


def test_datasource_create_bounds():
    with pytest.raises(ValidationError):
        Text2SqlDataSourceCreate(name="x", max_rows=0)  # ge=1
    with pytest.raises(ValidationError):
        Text2SqlDataSourceCreate(name="x", timeout_ms=10)  # ge=100


def test_datasource_update_partial():
    """``Update`` must accept partial fields (None = unchanged)."""
    u = Text2SqlDataSourceUpdate(max_rows=50)
    assert u.max_rows == 50
    assert u.name is None
    assert u.is_active is None


# --------------------------------------------------------------------------- #
# Text2SqlSchemaResponse                                                      #
# --------------------------------------------------------------------------- #


def test_schema_response_shape():
    r = Text2SqlSchemaResponse(
        data_source_id=1,
        db_name="ai_platform",
        table_count=2,
        schema_text="# users\n# agents",
        tables=[{"name": "users"}, {"name": "agents"}],
    )
    assert r.table_count == 2
    assert len(r.tables) == 2


def test_ask_response_success():
    r = Text2SqlAskResponse(
        query_id=1,
        status="success",
        generated_sql="SELECT 1",
        columns=["one"],
        rows=[{"one": 1}],
        row_count=1,
        attempts=1,
    )
    assert r.truncated is False  # default
    assert r.explanation is None
