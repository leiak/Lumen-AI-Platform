"""M33: SQLAlchemy model contract tests for Text2SqlDataSource + Text2SqlQuery.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.1

The tests below are pure SQLAlchemy metadata checks (no DB roundtrip)
so they run as fast as a unit test should. We verify:

1. Both tables are registered with the expected names and the
   expected set of required columns. Catches a future typo that
   would silently change a column name and break the API.
2. The composite index on ``text2sql_queries`` is declared in
   ``__table_args__``. The query list endpoint relies on this index
   for the (tenant_id, status, created_at) sort.
"""
from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery


def test_text2sql_data_source_table_name():
    """The tablename MUST be ``text2sql_data_sources`` (matches the
    migration DDL and the SQLGuard exclude list)."""
    assert Text2SqlDataSource.__tablename__ == "text2sql_data_sources"


def test_text2sql_data_source_required_columns():
    """The data source model must carry the columns that SQLGuard /
    Service / API all reference. A regression here would break the
    JSON serialisation of the API response.
    """
    cols = {c.name for c in Text2SqlDataSource.__table__.columns}
    expected = {
        "id", "tenant_id", "name", "db_name", "table_allowlist",
        "field_allowlist", "max_rows", "timeout_ms", "description",
        "is_active", "created_at", "updated_at",
    }
    assert expected.issubset(cols), (
        f"Missing required columns on Text2SqlDataSource: "
        f"{expected - cols}"
    )


def test_text2sql_query_table_name():
    assert Text2SqlQuery.__tablename__ == "text2sql_queries"


def test_text2sql_query_required_columns_and_composite_index():
    """The query model must carry the audit columns AND declare the
    composite index used by the history list endpoint.
    """
    cols = {c.name for c in Text2SqlQuery.__table__.columns}
    expected = {
        "id", "tenant_id", "user_id", "data_source_id", "question",
        "generated_sql", "attempts", "status", "error_type",
        "error_message", "rows_json", "columns_json", "row_count",
        "truncated", "explanation", "confidence", "duration_ms",
        "generate_call_id", "explain_call_id", "created_at", "updated_at",
    }
    assert expected.issubset(cols), (
        f"Missing required columns on Text2SqlQuery: {expected - cols}"
    )

    # Composite index check: parse __table_args__ for an Index named
    # ix_text2sql_queries_tenant_status_created. SQLAlchemy stores
    # Index objects directly; we just check name membership.
    from sqlalchemy import Index
    index_names = {
        arg.name
        for arg in Text2SqlQuery.__table__.indexes
        if isinstance(arg, Index)
    }
    assert "ix_text2sql_queries_tenant_status_created" in index_names, (
        f"Expected composite index "
        f"ix_text2sql_queries_tenant_status_created on Text2SqlQuery, "
        f"got {index_names}"
    )
