"""M33: tests for SchemaInspector (INFORMATION_SCHEMA reader).

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.2

The inspector is the ground-truth source for the LLM prompt and the
backbone of SQLGuard's table / column validators. We run all tests
against the real MySQL DB (no mocks) so we catch SQL typos and
INFORMATION_SCHEMA collation gotchas.
"""
from sqlalchemy import text

from lumen_core.database import SessionLocal
from lumen_services.text2sql.schema_inspector import (
    SchemaInspector,
    _is_meta_table,
)


def _inspector():
    return SchemaInspector(SessionLocal(), "ai_platform")


# --------------------------------------------------------------------------- #
# Meta-table guard                                                            #
# --------------------------------------------------------------------------- #


def test_is_meta_table_blocks_text2sql_prefix():
    """Tables starting with ``text2sql_`` must be hidden from the LLM."""
    assert _is_meta_table("text2sql_data_sources") is True
    assert _is_meta_table("text2sql_queries") is True


def test_is_meta_table_blocks_alembic():
    assert _is_meta_table("alembic_version") is True


def test_is_meta_table_allows_business_tables():
    """All non-meta tables must pass through the filter (sample)."""
    for name in ("users", "agents", "tenants", "conversations", "customers"):
        assert _is_meta_table(name) is False, (
            f"Expected business table {name!r} to NOT be filtered"
        )


# --------------------------------------------------------------------------- #
# list_tables                                                                 #
# --------------------------------------------------------------------------- #


def test_list_tables_excludes_meta_tables():
    """``text2sql_*`` / ``alembic_version`` must NOT appear in
    ``list_tables`` output, even when no allowlist is provided.
    """
    rows = _inspector().list_tables()
    names = {r["name"] for r in rows}
    assert "text2sql_data_sources" not in names
    assert "text2sql_queries" not in names
    assert "alembic_version" not in names


def test_list_tables_includes_business_tables():
    """At least the seed business tables (users, agents) must be visible."""
    rows = _inspector().list_tables()
    names = {r["name"] for r in rows}
    assert "users" in names
    assert "agents" in names


def test_list_tables_respects_allowlist():
    """When an allowlist is given, only listed tables appear."""
    rows = _inspector().list_tables(allowlist=["users", "agents"])
    names = {r["name"] for r in rows}
    assert names == {"users", "agents"}


def test_list_tables_allowlist_is_case_insensitive():
    rows = _inspector().list_tables(allowlist=["USERS", "Agents"])
    names = {r["name"] for r in rows}
    assert names == {"users", "agents"}


# --------------------------------------------------------------------------- #
# get_table_schema / validate_table / validate_field                          #
# --------------------------------------------------------------------------- #


def test_get_table_schema_returns_columns():
    cols = _inspector().get_table_schema("users")
    names = {c["name"] for c in cols}
    assert "id" in names
    assert "username" in names
    assert "email" in names


def test_get_table_schema_respects_field_allowlist():
    cols = _inspector().get_table_schema("users", field_allowlist=["id", "username"])
    names = {c["name"] for c in cols}
    assert names == {"id", "username"}


def test_validate_table_accepts_existing_business_table():
    assert _inspector().validate_table("users") is True
    assert _inspector().validate_table("USERS") is True  # case-insensitive


def test_validate_table_rejects_meta_table():
    """Even with no allowlist, meta tables must be rejected."""
    assert _inspector().validate_table("text2sql_data_sources") is False
    assert _inspector().validate_table("alembic_version") is False


def test_validate_field_works_case_insensitive():
    assert _inspector().validate_field("users", "id") is True
    assert _inspector().validate_field("USERS", "ID") is True


# --------------------------------------------------------------------------- #
# get_full_schema_text                                                        #
# --------------------------------------------------------------------------- #


def test_get_full_schema_text_contains_table_headers():
    """The schema text must include ``# users`` etc. so the LLM can
    see table names in the prompt."""
    text_out = _inspector().get_full_schema_text()
    assert "# users" in text_out
    assert "# agents" in text_out
    # No meta-table leakage
    assert "# text2sql_data_sources" not in text_out
    assert "# alembic_version" not in text_out


def test_get_full_schema_text_with_allowlist():
    text_out = _inspector().get_full_schema_text(table_allowlist=["users"])
    assert "# users" in text_out
    assert "# agents" not in text_out
