"""Tests for startup migration idempotency.

These guard against the bug class "CREATE [something] inside a function
that's called on every uvicorn boot" — the second boot will crash with
(1061, "Duplicate key name") / (1060, "Duplicate column name") / etc.

The fix pattern (and the pattern the rest of this file's `ensure_*`
helpers already use) is: check ``INFORMATION_SCHEMA`` for the object's
existence, then ALTER / CREATE only if missing. This test file locks
that contract for the model_configs-purpose-flags migration specifically,
because that one shipped the bug.
"""
from lumen_core.database import (
    ensure_model_configs_purpose_flags,
    ensure_conversations_user_id_nullable,
    ensure_conversations_external_fks,
    ensure_external_apps_tables,
    ensure_external_apps_indexes_desc,
    ensure_global_memories_conversation_id,  # NEW
    ensure_agent_kb_retrieval_config,  # M21
    ensure_model_configs_image_flag,  # M22
    ensure_settings_model_fk_columns,  # M31
    ensure_faq_entries_table,  # M31
    ensure_text2sql_data_sources_table,  # M33
    ensure_text2sql_queries_table,  # M33
)


def test_ensure_model_configs_purpose_flags_is_idempotent():
    """Calling the migration twice must NOT raise.

    Regression for the (1061, "Duplicate key name 'uq_model_configs_tenant_type_name'")
    crash that brought down every uvicorn restart on the
    ``feat/embedding-model-config`` branch: the first boot created the
    columns and unique index, the second boot re-ran the CREATE UNIQUE
    INDEX unconditionally and MySQL rejected it.
    """
    # First call: should be a no-op once the columns + index are in place
    # (the function is designed to be re-entrant; we rely on that here).
    ensure_model_configs_purpose_flags()
    # Second call: must succeed. Before the fix this raised
    # sqlalchemy.exc.OperationalError on the CREATE UNIQUE INDEX.
    ensure_model_configs_purpose_flags()


def test_ensure_conversations_user_id_nullable_is_idempotent():
    """Calling the migration twice must NOT raise.

    Makes ``conversations.user_id`` nullable (the EXTERNAL chat flow
    leaves it NULL — see ExternalChat spec § 4.3). First run ALTERs
    the column; second run hits MySQL's "same definition = no-op"
    MODIFY COLUMN and returns success.
    """
    ensure_conversations_user_id_nullable()
    # Second call: must succeed. If the function accidentally re-ran
    # an unconditional ALTER, MySQL would still accept it as a no-op
    # for the MODIFY COLUMN itself, but if a future change adds more
    # DDL (e.g. an index) that wasn't gated, the second call would
    # raise 1060/1061 — which is what this test catches.
    ensure_conversations_user_id_nullable()


def test_ensure_conversations_external_fks_is_idempotent():
    """Calling the migration twice must NOT raise.

    Adds ``external_app_id`` + ``external_visitor_id`` columns and
    indexes to ``conversations`` (the EXTERNAL chat flow uses these
    columns — see ExternalChat spec § 4.3). The DB-level FK
    constraints are added only when ``external_apps`` /
    ``external_visitors`` exist (Task 3); without that guard, the
    first run would 1216 ("Cannot add foreign key constraint") when
    those tables aren't there yet.
    """
    # First call: creates the columns + indexes. FK constraints
    # skipped (external_apps table doesn't exist on a Task 2-only
    # dev DB; Task 3 will land those).
    ensure_conversations_external_fks()
    # Second call: must succeed. Without the ``_column_exists`` /
    # ``_index_exists`` gates, this would raise 1060/1061.
    ensure_conversations_external_fks()


def test_ensure_external_apps_tables_is_idempotent():
    """Calling the migration twice must NOT raise.

    Creates the ``external_apps`` and ``external_visitors`` tables for
    the embeddable chat widget (see ExternalChat spec § 4.1-4.2).
    Gated on ``_table_exists`` so the second call is a clean no-op.
    Before this migration shipped, the tables were metadata-only
    (registered with SQLAlchemy ``Base.metadata``) but the dev DB had
    no DDL for them — every fresh ``uvicorn`` boot would silently miss
    the tables and the first external-app request would 500. This
    test locks in the "create on startup, never crash on rerun" contract.
    """
    # First call: should be a no-op once the tables exist (the
    # function is designed to be re-entrant; we rely on that here).
    ensure_external_apps_tables()
    # Second call: must succeed. If the function accidentally
    # re-ran an unconditional ``CREATE TABLE``, MySQL would still
    # accept it (``IF NOT EXISTS`` semantics), but the real failure
    # mode we want to catch is a missed gate around an
    # ``ALTER TABLE`` / index / FK that would raise 1060/1061/1062
    # on the second call.
    ensure_external_apps_tables()


def test_fk_exists_returns_true_for_existing_constraint_and_false_for_missing():
    """The new ``_fk_exists`` helper must reliably detect FK
    presence / absence. We test against the real MySQL DB (not
    mocked) so we catch SQL syntax errors, INFORMATION_SCHEMA view
    typos, and collation mismatches.

    Negative case uses a name that definitely doesn't exist on any
    table. Positive case looks up any real FK on the ``conversations``
    table (the ``user_id`` FK is created by SQLAlchemy's ``create_all``
    on a fresh DB) and verifies ``_fk_exists`` returns True for it,
    including with upper-cased input (case-insensitive match).
    """
    from sqlalchemy import text as sa_text
    from lumen_core.database import _fk_exists, engine

    # Negative case: an obviously fake constraint name must return False
    assert (
        _fk_exists("conversations", "fk_definitely_not_a_real_constraint_xyz")
        is False
    )

    # Positive case: find any real FK on the conversations table and
    # verify _fk_exists finds it. Use INFORMATION_SCHEMA directly so
    # we don't hardcode a name (the team_id FK is only present after
    # ensure_conversations_team_id has run).
    with engine.connect() as conn:
        real_fk = conn.execute(
            sa_text(
                "SELECT CONSTRAINT_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'conversations' "
                "AND CONSTRAINT_TYPE = 'FOREIGN KEY' "
                "LIMIT 1"
            )
        ).scalar()

    if real_fk is not None:
        # Exact case must match
        assert _fk_exists("conversations", real_fk) is True
        # Upper-cased input must also match (LOWER() comparison is
        # collation-independent)
        assert _fk_exists("conversations", real_fk.upper()) is True
    # else: no FKs on conversations in this DB — skip the positive case.
    # In a normal deployment conversations always has at least the
    # user_id FK, so this branch is informational only.


def test_ensure_external_apps_indexes_desc_is_idempotent_and_applies_desc():
    """Calling the DESC-index migration twice must NOT raise, AND the
    trailing column of each composite index must end up with
    ``COLLATION='D'`` per ExternalChat spec § 4.1 / § 4.2.

    This test locks two contracts for ``ensure_external_apps_indexes_desc``:

    1. **Idempotency** — second call is a no-op (no 1061, no dropped
       table). The helper gates on ``_index_trailing_col_desc`` so a
       re-run hits the gate and returns without touching the indexes.
    2. **Spec compliance** — after the call, both
       ``ix_external_apps_tenant_created`` (trailing: ``created_at``)
       and ``ix_external_visitors_app_lastseen`` (trailing:
       ``last_seen_at``) have ``COLLATION='D'`` in
       ``INFORMATION_SCHEMA.STATISTICS``. We assert this directly
       against the live MySQL DB so a regression in the helper
       (silent skip, wrong column name, wrong collation value) is
       caught here.

    Skips the COLLATION assertion on a fresh DB where the index
    hasn't been created yet (e.g. tables don't exist). On a fully
    migrated dev DB this assertion is the load-bearing check.
    """
    from sqlalchemy import text as sa_text
    from lumen_core.database import _index_exists, engine

    # Make sure the tables exist (idempotent; this is the
    # "ensure_external_apps_tables creates with DESC" entry point).
    ensure_external_apps_tables()

    # First call: applies the DESC change if the index exists with
    # the wrong ordering. Idempotent re-run follows.
    ensure_external_apps_indexes_desc()
    # Second call: must be a clean no-op. If the gate logic missed
    # something, MySQL would raise 1061 (Duplicate key name) on the
    # second CREATE INDEX.
    ensure_external_apps_indexes_desc()

    # Spec-compliance assertion: each composite index's trailing
    # column must have COLLATION='D' (the marker for DESC ordering
    # in MySQL 8.0+ INFORMATION_SCHEMA.STATISTICS).
    cases = [
        ("external_apps", "ix_external_apps_tenant_created", "created_at"),
        ("external_visitors", "ix_external_visitors_app_lastseen", "last_seen_at"),
    ]
    for table_name, index_name, trailing_col in cases:
        if not _index_exists(table_name, index_name):
            # Fresh DB / table not yet created — nothing to assert.
            # On a normal dev DB both tables have existed since
            # dc5495b9, so this branch is informational only.
            continue
        with engine.connect() as conn:
            row = conn.execute(
                sa_text(
                    "SELECT COLLATION FROM INFORMATION_SCHEMA.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = :t AND INDEX_NAME = :i "
                    "AND COLUMN_NAME = :c"
                ),
                {"t": table_name, "i": index_name, "c": trailing_col},
            ).scalar()
        assert row == "D", (
            f"Expected DESC (COLLATION='D') on {table_name}.{index_name}"
            f"({trailing_col}) per spec § 4.1 / § 4.2, got {row!r}. "
            f"Run ensure_external_apps_indexes_desc() to upgrade."
        )


def test_ensure_global_memories_conversation_id_is_idempotent():
    """Calling the migration twice must NOT raise.

    Regression class: 1060 'Duplicate column name' on the second boot.
    The function guards with ``_column_exists`` / ``_index_exists`` and
    is safe to re-run.
    """
    ensure_global_memories_conversation_id()
    # Second call must succeed.
    ensure_global_memories_conversation_id()


def test_ensure_agent_kb_retrieval_config_idempotent():
    """M21: 跑两次 ensure 函数不抛,1060 Duplicate column 兜底。

    Adds the ``kb_retrieval_config`` JSON column to ``agents`` for the
    per-agent KB retrieval knobs (top_k, rrf_k, …) introduced in M21.
    Mirrors the ``ensure_marketplace_type_column`` pattern: a single
    nullable JSON column, gated on ``_column_exists`` so the second
    call is a clean no-op. After the column is added, legacy rows are
    backfilled with the default ``{"top_k": 3, "rrf_k": 30}`` config
    (only if the column is NULL — re-running must not clobber rows the
    user has since customized).
    """
    # First call: should add the column (no-op on a fully migrated DB)
    ensure_agent_kb_retrieval_config()
    # Second call: must succeed without raising 1060.
    ensure_agent_kb_retrieval_config()

    # Verify the column exists and legacy rows have the default config.
    from sqlalchemy import text as sa_text
    from lumen_core.database import _column_exists, engine

    assert _column_exists("agents", "kb_retrieval_config") is True

    with engine.connect() as conn:
        null_count = conn.execute(
            sa_text("SELECT COUNT(*) FROM agents WHERE kb_retrieval_config IS NULL")
        ).scalar()
    assert null_count == 0, (
        f"Expected all agents rows to have kb_retrieval_config backfilled, "
        f"got {null_count} NULLs. ensure_agent_kb_retrieval_config should "
        f"backfill the default on legacy rows."
    )


def test_ensure_model_configs_image_flag_idempotent():
    """M22: 跑两次 ensure 函数不抛,1060 Duplicate column 兜底。

    Adds the ``is_image_generation`` BOOLEAN column to ``model_configs``
    for the M22 image generation feature. Default ``FALSE`` — legacy
    rows are not marked as image-generation capable. The image-gen
    admin UI flips this to True for rows configured with a provider
    that supports it (e.g. OpenAI ``dall-e-3``, ``gpt-image-1``).

    Mirrors the ``ensure_global_memories_conversation_id`` pattern:
    single column, gated on ``_column_exists`` so the second call is a
    clean no-op.
    """
    from lumen_core.database import _column_exists

    # First call: should add the column (no-op on a fully migrated DB)
    ensure_model_configs_image_flag()
    # Second call: must succeed without raising 1060.
    ensure_model_configs_image_flag()

    # Verify the column exists with the expected default.
    assert _column_exists("model_configs", "is_image_generation") is True


def test_ensure_settings_model_fk_columns_idempotent():
    """M31: 跑两次 ensure 函数不抛,INT FK + 索引全部就位。

    Migrates ``system_settings.default_model`` / ``.embedding_model``
    from VARCHAR(50) (free-text model name) to INT FK →
    ``model_configs.id``. Replaces the prior hard-coded string
    defaults in the router fallback with a server-side lookup.

    Mirrors the ``ensure_kb_embedding_model_config_id`` pattern:
    a column + index + FK triple, each gated on the appropriate
    INFORMATION_SCHEMA check so the second call is a clean no-op
    (no 1060 / 1061 / 1826).
    """
    from sqlalchemy import text as sa_text
    from lumen_core.database import _column_exists, _fk_exists, engine

    # First call: should add the columns + indexes + FKs (no-op on a
    # fully migrated DB).
    ensure_settings_model_fk_columns()
    # Second call: must succeed. Before the fix this raised 1060
    # (Duplicate column name) / 1061 (Duplicate key name) / 1826
    # (Duplicate foreign key constraint) on the second call.
    ensure_settings_model_fk_columns()

    # Verify both columns exist with DATA_TYPE='int'.
    for col in ("default_model", "embedding_model"):
        assert _column_exists("system_settings", col) is True, (
            f"Expected column system_settings.{col} to exist after M31 migration"
        )
        with engine.connect() as conn:
            data_type = conn.execute(
                sa_text(
                    "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'system_settings' "
                    "AND COLUMN_NAME = :c"
                ),
                {"c": col},
            ).scalar()
        assert data_type == "int", (
            f"Expected system_settings.{col} DATA_TYPE='int' after M31 "
            f"migration, got {data_type!r}. ensure_settings_model_fk_columns "
            f"should MODIFY COLUMN to INT."
        )

    # Verify both FKs are in place.
    assert _fk_exists("system_settings", "fk_system_settings_default_model") is True
    assert _fk_exists("system_settings", "fk_system_settings_embedding_model") is True


def test_ensure_text2sql_tables_idempotent():
    """M33: 跑两次 ensure 函数不抛,create_all 对已存在的表是 no-op。

    ``text2sql_data_sources`` 和 ``text2sql_queries`` 两张表都有
    FK / 复合索引,create_all 一次性建好;第二次调用必须 no-op。
    """
    from sqlalchemy import text as sa_text
    from lumen_core.database import _table_exists

    # First call: should create the tables (no-op if already exist).
    ensure_text2sql_data_sources_table()
    ensure_text2sql_queries_table()
    # Second call: must succeed.
    ensure_text2sql_data_sources_table()
    ensure_text2sql_queries_table()

    assert _table_exists("text2sql_data_sources") is True
    assert _table_exists("text2sql_queries") is True

    # Composite index on text2sql_queries must be present (the
    # history list endpoint depends on it for the tenant+status+sort).
    from lumen_core.database import engine
    with engine.connect() as conn:
        idx_count = conn.execute(
            sa_text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'text2sql_queries' "
                "AND INDEX_NAME = 'ix_text2sql_queries_tenant_status_created'"
            )
        ).scalar()
    assert idx_count and idx_count > 0, (
        "Expected composite index ix_text2sql_queries_tenant_status_created "
        "to exist on text2sql_queries after ensure_text2sql_queries_table()"
    )
