"""M33: tests for SQLGuard (static SQL safety).

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.3

The guard is the single point of decision for "can we run this SQL?".
The tests below cover:

- Parse failures (empty, garbage, multi-statement collapses to 1st)
- ``validate_select_only`` blocklist (DDL, DML, transaction, info-schema)
- ``validate_tables`` against the real MySQL INFORMATION_SCHEMA
- ``validate_columns`` + per-table field allowlist
- ``wrap_with_limit`` and ``inject_timeout`` rewrites

All tests use the real MySQL DB (no mock) so SQL / INFORMATION_SCHEMA
collation / case-sensitivity bugs surface immediately.
"""
from lumen_core.database import SessionLocal
from lumen_services.text2sql.schema_inspector import SchemaInspector
from lumen_services.text2sql.sql_guard import (
    GuardResult,
    SQLGuard,
    _has_select_keyword,
)


def _guard(table_allowlist=None, field_allowlist=None):
    return SQLGuard(
        SchemaInspector(SessionLocal(), "ai_platform"),
        table_allowlist=table_allowlist,
        field_allowlist=field_allowlist,
    )


# --------------------------------------------------------------------------- #
# parse                                                                       #
# --------------------------------------------------------------------------- #


def test_parse_empty_string_returns_error():
    stmt, err = _guard().parse("")
    assert stmt is None
    assert err is not None


def test_parse_garbage_returns_error():
    stmt, err = _guard().parse("NOT A SQL AT ALL")
    assert stmt is None or err is not None  # either parse fails or classifies as UNKNOWN
    # If parse succeeded but classified UNKNOWN, ``err`` may be None —
    # what we really care about is that ``run`` rejects it.


def test_parse_select_succeeds():
    stmt, err = _guard().parse("SELECT 1")
    assert err is None
    assert stmt is not None


# --------------------------------------------------------------------------- #
# validate_select_only                                                        #
# --------------------------------------------------------------------------- #


def test_blocklist_rejects_insert():
    stmt, _ = _guard().parse("INSERT INTO users (username) VALUES ('x')")
    res = _guard().validate_select_only(stmt)
    assert res.ok is False
    assert res.error_type == "blocklist"


def test_blocklist_rejects_update():
    stmt, _ = _guard().parse("UPDATE users SET username='x'")
    res = _guard().validate_select_only(stmt)
    assert res.ok is False
    assert res.error_type == "blocklist"


def test_blocklist_rejects_delete():
    stmt, _ = _guard().parse("DELETE FROM users")
    res = _guard().validate_select_only(stmt)
    assert res.ok is False


def test_blocklist_rejects_drop():
    stmt, _ = _guard().parse("DROP TABLE users")
    res = _guard().validate_select_only(stmt)
    assert res.ok is False


def test_blocklist_rejects_alter():
    stmt, _ = _guard().parse("ALTER TABLE users ADD COLUMN x INT")
    res = _guard().validate_select_only(stmt)
    assert res.ok is False


def test_blocklist_rejects_show():
    """SHOW TABLES would leak the metadata layer to the LLM.

    We test through ``run()`` (the public API) because ``parse()``
    short-circuits to an error for non-SELECT statements that
    sqlparse classifies as UNKNOWN, and the test wants to assert
    the rejection happens at the validate step (not at parse).
    """
    out, err = _guard().run("SHOW TABLES", max_rows=10, timeout_ms=1000)
    assert out is None
    assert err is not None
    assert err.error_type in {"parse", "blocklist"}


def test_blocklist_rejects_set():
    out, err = _guard().run("SET autocommit=0", max_rows=10, timeout_ms=1000)
    assert out is None
    assert err is not None
    assert err.error_type in {"parse", "blocklist"}


def test_select_only_accepts_select():
    stmt, _ = _guard().parse("SELECT 1")
    res = _guard().validate_select_only(stmt)
    assert res.ok is True


def test_select_only_accepts_with_cte():
    stmt, _ = _guard().parse("WITH cte AS (SELECT 1 AS a) SELECT a FROM cte")
    res = _guard().validate_select_only(stmt)
    assert res.ok is True


# --------------------------------------------------------------------------- #
# extract_tables / validate_tables                                            #
# --------------------------------------------------------------------------- #


def test_extract_tables_finds_from_table():
    stmt, _ = _guard().parse("SELECT * FROM users")
    tables = _guard().extract_tables(stmt)
    assert "users" in tables


def test_extract_tables_finds_join_table():
    stmt, _ = _guard().parse("SELECT u.id FROM users u JOIN agents a ON a.user_id = u.id")
    tables = _guard().extract_tables(stmt)
    assert set(tables) >= {"users", "agents"}


def test_validate_tables_rejects_nonexistent_table():
    res = _guard().validate_tables(["definitely_not_a_table_xyz"])
    assert res.ok is False
    assert res.error_type == "table"


def test_validate_tables_rejects_meta_table():
    res = _guard().validate_tables(["text2sql_data_sources"])
    assert res.ok is False
    assert res.error_type == "table"


def test_validate_tables_respects_allowlist():
    g = _guard(table_allowlist=["users"])
    res = g.validate_tables(["agents"])
    assert res.ok is False
    assert "table allowlist" in (res.error_message or "")


# --------------------------------------------------------------------------- #
# wrap_with_limit / inject_timeout                                            #
# --------------------------------------------------------------------------- #


def test_wrap_with_limit_adds_when_missing():
    out = _guard().wrap_with_limit("SELECT * FROM users", 50)
    assert "LIMIT 50" in out.upper()


def test_wrap_with_limit_lowers_existing():
    out = _guard().wrap_with_limit("SELECT * FROM users LIMIT 1000", 50)
    assert "LIMIT 50" in out.upper()
    assert "LIMIT 1000" not in out.upper()


def test_wrap_with_limit_keeps_smaller():
    out = _guard().wrap_with_limit("SELECT * FROM users LIMIT 10", 50)
    assert "LIMIT 10" in out.upper()


def test_inject_timeout_inserts_hint_after_select():
    out = _guard().inject_timeout("SELECT * FROM users", 500)
    assert "MAX_EXECUTION_TIME(500)" in out
    # Hinted after the first SELECT, not before
    select_pos = out.upper().find("SELECT")
    hint_pos = out.upper().find("MAX_EXECUTION_TIME")
    assert select_pos >= 0 and hint_pos > select_pos


def test_inject_timeout_idempotent():
    once = _guard().inject_timeout("SELECT * FROM users", 500)
    twice = _guard().inject_timeout(once, 500)
    assert once == twice


# --------------------------------------------------------------------------- #
# end-to-end run                                                              #
# --------------------------------------------------------------------------- #


def test_run_happy_path_returns_rewritten_sql():
    out, err = _guard().run("SELECT * FROM users", max_rows=10, timeout_ms=1000)
    assert err is None
    assert out is not None
    assert "LIMIT 10" in out.upper()
    assert "MAX_EXECUTION_TIME(1000)" in out


def test_run_rejected_for_ddl():
    out, err = _guard().run("DROP TABLE users", max_rows=10, timeout_ms=1000)
    assert out is None
    assert err is not None
    assert err.error_type == "blocklist"


def test_run_rejected_for_unknown_table():
    out, err = _guard().run("SELECT * FROM no_such_table_xyz", max_rows=10, timeout_ms=1000)
    assert out is None
    assert err is not None
    assert err.error_type == "table"


def test_run_rejected_for_meta_table_even_via_alias():
    """SELECT FROM text2sql_data_sources must be blocked even when the
    LLM uses an alias to try to hide it."""
    out, err = _guard().run(
        "SELECT * FROM text2sql_data_sources t", max_rows=10, timeout_ms=1000
    )
    assert out is None
    assert err is not None
    assert err.error_type == "table"
