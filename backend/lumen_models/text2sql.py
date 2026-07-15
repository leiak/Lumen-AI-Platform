"""Text2SQL (智能问数) persistence models.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.1

Two tables:

- ``text2sql_data_sources`` — per-tenant configuration of a database
  connection (only ``ai_platform`` is wired today, but the schema allows
  pointing at any logical DB name). The ``table_allowlist`` /
  ``field_allowlist`` JSON columns pin what the LLM is allowed to
  reference; an empty list means "all tables / fields" which is the
  default for the seeded ``ai_platform`` source.

- ``text2sql_queries`` — the audit log of every ask. Stores the
  generated SQL, the executor's result (rows / columns / row_count),
  the explanation, and links to the two LLMCallLog call_ids
  (``generate_call_id`` and ``explain_call_id``) for full trace
  reconstruction.

The status field drives the UI feedback loop:

- ``pending`` — request received, waiting for the background task
- ``generating`` — Phase 1 (SQL generation) is running
- ``executing`` — Phase 1 succeeded, trial execution in progress
- ``explaining`` — Phase 2 (Chinese explanation) is running
- ``success`` — returned rows + explanation to the user
- ``rejected`` — SQLGuard vetoed the LLM output (e.g. DDL keyword,
  table/field not in allowlist). ``error_type`` distinguishes the
  rejection category so the UI can give a targeted hint.
- ``failed`` — execution error or uncaught exception
"""
from sqlalchemy import Column, Integer, String, Text, JSON, ForeignKey, Index
from lumen_models.base import BaseModel


class Text2SqlDataSource(BaseModel):
    __tablename__ = "text2sql_data_sources"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    # Today only "ai_platform" is supported by the SQLExecutor; we keep
    # the column to leave room for read-replica / warehouse routing in
    # later milestones without another migration.
    db_name = Column(String(64), nullable=False, default="ai_platform")
    # JSON list of allowed table names (lowercase, exact match against
    # INFORMATION_SCHEMA.TABLES). Empty list == no restriction. The
    # default seeded "ai_platform" source uses [] to permit all
    # business tables (text2sql_* metadata tables are explicitly
    # excluded by SchemaInspector).
    table_allowlist = Column(JSON, nullable=True)
    # JSON dict of { table_name: [allowed_column_names] }. Empty dict
    # == no restriction. Keys/values are lowercase.
    field_allowlist = Column(JSON, nullable=True)
    # Hard cap on rows returned to the user; SQLGuard wraps every
    # generated SQL with a LIMIT matching this value.
    max_rows = Column(Integer, nullable=False, default=100)
    # MySQL MAX_EXECUTION_TIME hint (milliseconds). SQLGuard injects
    # this as a /*+ MAX_EXECUTION_TIME(N) */ comment after the first
    # SELECT.
    timeout_ms = Column(Integer, nullable=False, default=5000)
    description = Column(Text, nullable=True)
    is_active = Column(Integer, nullable=False, default=1)  # TINYINT(1) in MySQL

    __table_args__ = (
        Index(
            "ix_text2sql_ds_tenant_active",
            "tenant_id",
            "is_active",
        ),
    )


class Text2SqlQuery(BaseModel):
    __tablename__ = "text2sql_queries"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    data_source_id = Column(
        Integer,
        ForeignKey("text2sql_data_sources.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    question = Column(Text, nullable=False)
    # Final SQL the user saw (after Phase 1.5 retries, after SQLGuard
    # rewriting for LIMIT / MAX_EXECUTION_TIME).
    generated_sql = Column(Text, nullable=True)
    # How many generate→validate→execute cycles we burned before giving
    # up. Useful for the UI to show "solved on the 2nd try" badges.
    attempts = Column(Integer, nullable=False, default=1)
    # pending | generating | executing | explaining | success | rejected | failed
    status = Column(String(20), nullable=False, default="pending")
    # For rejected: sql_guard_blocklist | sql_guard_table | sql_guard_field |
    #                sql_guard_parse
    # For failed: exec_error | timeout | llm_error | unknown
    error_type = Column(String(40), nullable=True)
    error_message = Column(Text, nullable=True)
    # Serialised result rows (list of dicts, JSON-safe). Truncated to
    # max_rows in the SQLExecutor before being persisted.
    rows_json = Column(JSON, nullable=True)
    columns_json = Column(JSON, nullable=True)
    row_count = Column(Integer, nullable=True)
    truncated = Column(Integer, nullable=False, default=0)  # bool 0/1
    explanation = Column(Text, nullable=True)
    # 0.0 - 1.0, LLM self-reported confidence for the explanation
    # phase. UI shows this in a Progress ring.
    confidence = Column(Integer, nullable=True)  # store as int 0-100
    duration_ms = Column(Integer, nullable=True)
    # Links to llm_call_logs rows (call_id is VARCHAR(36)). Both
    # nullable because a query that fails at SQLGuard never gets a
    # generate_call_id, and one that fails before Phase 2 has no
    # explain_call_id.
    generate_call_id = Column(String(36), nullable=True, index=True)
    explain_call_id = Column(String(36), nullable=True)

    __table_args__ = (
        Index(
            "ix_text2sql_queries_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_text2sql_queries_data_source_created",
            "data_source_id",
            "created_at",
        ),
    )
