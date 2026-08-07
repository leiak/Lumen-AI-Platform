from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from lumen_core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def create_tables():
    Base.metadata.create_all(bind=engine)


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists on a table in the current MySQL database.
    Idempotent migration helper for cases where Alembic isn't set up yet.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
            ),
            {"t": table_name, "c": column_name},
        ).scalar()
    return bool(row and row > 0)


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table in the current MySQL database.

    Mirror of ``_column_exists`` for indexes. ``CREATE INDEX`` is not
    idempotent in MySQL (it raises 1061 "Duplicate key name" on the
    second call), so every ensure_* migration that creates an index
    must guard it with this helper.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = :t AND INDEX_NAME = :i"
            ),
            {"t": table_name, "i": index_name},
        ).scalar()
    return bool(row and row > 0)


def _index_trailing_col_desc(table_name: str, index_name: str) -> bool:
    """Check if the LAST column in the given composite index has DESC
    ordering (i.e. ``COLLATION = 'D'`` in ``INFORMATION_SCHEMA.STATISTICS``).

    MySQL 8.0+ supports descending indexes natively. ``COLLATION='A'`` means
    ascending (the default), ``COLLATION='D'`` means descending, ``NULL``
    means the column is non-sortable (e.g. on a non-indexed expression
    in older MySQL versions — not relevant here).

    Returns:

    - ``True`` if the index does NOT exist (nothing to fix; the
      ``ensure_*`` table-creation migration will create it with DESC
      on a fresh DB).
    - ``True`` if the index exists AND the trailing column has
      ``COLLATION='D'`` (already correct, migration is a no-op).
    - ``False`` if the index exists but the trailing column is still
      ASC — the caller should DROP and re-CREATE the index with DESC.

    Used by ``ensure_external_apps_indexes_desc`` to upgrade the
    composite indexes on ``external_apps`` / ``external_visitors`` to
    have DESC on the trailing column, per ExternalChat spec § 4.1 /
    § 4.2.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT COLLATION FROM INFORMATION_SCHEMA.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = :t AND INDEX_NAME = :i "
                "ORDER BY SEQ_IN_INDEX DESC LIMIT 1"
            ),
            {"t": table_name, "i": index_name},
        ).fetchall()
    if not rows:
        # Index doesn't exist → nothing to fix. The ensure_* table
        # creation migration will create it with DESC on a fresh DB.
        return True
    return rows[0][0] == "D"


def _table_exists(table_name: str) -> bool:
    """Check if a table exists in the current MySQL database.

    Mirror of ``_column_exists`` / ``_index_exists`` for tables. Used
    by ``ensure_conversations_external_fks`` to add the DB-level FK
    constraint only after Task 3 has created the ``external_apps`` /
    ``external_visitors`` tables. Before Task 3 lands, the referenced
    table doesn't exist and any ``ADD CONSTRAINT FOREIGN KEY`` would
    fail with 1216 ("Cannot add foreign key constraint" on first run
    because the referenced table is missing). Checking first makes
    the migration safe to run regardless of task ordering.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = :t"
            ),
            {"t": table_name},
        ).scalar()
    return bool(row and row > 0)


def _fk_exists(table_name: str, constraint_name: str) -> bool:
    """Check if a foreign key constraint exists on a table in the current
    MySQL database.

    Mirror of ``_column_exists`` / ``_index_exists`` for FK constraints.
    ``ALTER TABLE ... ADD CONSTRAINT FOREIGN KEY`` is not idempotent in
    MySQL (it raises 1826 "Duplicate foreign key constraint" on the second
    call), so every ``ensure_*`` migration that adds an FK must guard it
    with this helper.

    MySQL stores constraint names in ``INFORMATION_SCHEMA.TABLE_CONSTRAINTS``
    using the case from the original DDL, but identifier comparison is
    collation-driven (default ``utf8mb4_0900_ai_ci`` is case-insensitive).
    We still wrap both sides in ``LOWER()`` to make the helper explicit
    and resilient to non-default collations.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = :t "
                "AND CONSTRAINT_TYPE = 'FOREIGN KEY' "
                "AND LOWER(CONSTRAINT_NAME) = LOWER(:c)"
            ),
            {"t": table_name, "c": constraint_name},
        ).scalar()
    return bool(row and row > 0)


def ensure_workflow_runs_trigger_source() -> None:
    """Add ``trigger_source`` to ``workflow_runs`` if it's missing.
    Backfills existing rows with 'manual' (the historical default — every
    pre-existing run was triggered via the manual /run endpoint).
    """
    if _column_exists("workflow_runs", "trigger_source"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE workflow_runs "
                "ADD COLUMN trigger_source VARCHAR(20) NOT NULL DEFAULT 'manual'"
            )
        )


def ensure_workflow_indexes() -> None:
    """M30a (2026-06-16): composite indexes for the workflow list pages.

    Three indexes cover the dominant filter patterns:

    - ``idx_workflow_tenant_active_created`` — the workflow list endpoint
      sorts by created_at DESC within a tenant + active flag, so MySQL
      can satisfy the query from the index without a filesort.
    - ``idx_workflow_run_workflow_started`` — the run history drawer
      sorts by started_at DESC for one workflow.
    - ``idx_workflow_run_workflow_status`` — ``?status=`` filter on the
      run history page.

    Idempotent: each CREATE INDEX is gated on ``_index_exists`` so the
    function is a no-op on subsequent restarts.
    """
    pairs = [
        (
            "workflows",
            "idx_workflow_tenant_active_created",
            "(tenant_id, is_active, created_at DESC)",
        ),
        (
            "workflow_runs",
            "idx_workflow_run_workflow_started",
            "(workflow_id, started_at DESC)",
        ),
        (
            "workflow_runs",
            "idx_workflow_run_workflow_status",
            "(workflow_id, status)",
        ),
    ]
    with engine.begin() as conn:
        for table, idx_name, cols in pairs:
            if _index_exists(table, idx_name):
                continue
            conn.execute(
                text(f"CREATE INDEX {idx_name} ON {table} {cols}")
            )


def ensure_document_chunks_embedding_status() -> None:
    """Add ``embedding_status`` to ``document_chunks`` if it's missing.

    Existing rows are treated as 'ok' (the historical default — chunks
    that exist were assumed to be embedded). Chunks written by the
    worker after this migration landed will get the real status from
    the embedder.
    """
    if _column_exists("document_chunks", "embedding_status"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE document_chunks "
                "ADD COLUMN embedding_status VARCHAR(20) NOT NULL DEFAULT 'ok'"
            )
        )
        # Index speeds up the "where embedding_status = 'ok'" filter
        # in list/search endpoints once the table gets large.
        conn.execute(
            text(
                "CREATE INDEX idx_document_chunks_embedding_status "
                "ON document_chunks (embedding_status)"
            )
        )


def ensure_documents_created_by() -> None:
    """Add ``created_by`` to ``documents`` if it's missing.
    Nullable; old rows are left NULL and will not get notifications
    (acceptable for the v1 rollout)."""
    if _column_exists("documents", "created_by"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN created_by INT NULL"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX idx_documents_created_by "
                "ON documents (created_by)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD CONSTRAINT fk_documents_created_by "
                "FOREIGN KEY (created_by) REFERENCES users(id)"
            )
        )


def ensure_conversations_deleted_at() -> None:
    """Add ``deleted_at`` to ``conversations`` if it's missing.
    Nullable DateTime used as a soft-delete tombstone; None = active,
    non-None = the timestamp at which the user soft-deleted the row.
    The list endpoint filters ``deleted_at IS NULL`` so soft-deleted
    rows disappear from the UI; the row is preserved in the DB for
    a future "Recently Deleted" restore feature.
    """
    if _column_exists("conversations", "deleted_at"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN deleted_at DATETIME NULL"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX ix_conversations_deleted_at "
                "ON conversations (deleted_at)"
            )
        )


def ensure_conversations_team_id() -> None:
    """Add ``team_id`` FK to ``conversations`` if it's missing.

    Nullable because a Conversation is owned by either an Agent
    (single-agent chat) OR a Team (multi-agent chat), and existing
    rows are all single-agent. The service layer enforces the
    mutual-exclusion at write time. We add the FK only on the first
    run — MySQL raises 1826 on duplicate FK ADD.
    """
    if _column_exists("conversations", "team_id"):
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD COLUMN team_id INT NULL"
            )
        )
        if not _index_exists("conversations", "ix_conversations_team_id"):
            conn.execute(
                text(
                    "CREATE INDEX ix_conversations_team_id "
                    "ON conversations (team_id)"
                )
            )
        # FK to agent_teams(id) — RESTRICT matches the chat→agent FK
        # semantics; deleting a team that has chats should be a
        # conscious decision, not a silent cascade.
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "ADD CONSTRAINT fk_conversations_team_id "
                "FOREIGN KEY (team_id) REFERENCES agent_teams(id)"
            )
        )


def ensure_conversations_user_id_nullable() -> None:
    """Make ``conversations.user_id`` nullable to support the EXTERNAL
    chat flow (see ExternalChat spec § 4.3).

    Internal flows always set ``user_id``; external flows leave it
    NULL and populate ``external_app_id`` + ``external_visitor_id``
    instead. The service layer (added in later tasks) enforces the
    mutual-exclusion invariant at write time.

    Idempotent: gated on ``_column_exists`` so the function is a
    no-op when the column doesn't exist (fresh DB scenario).
    MySQL 8 treats a no-op ``MODIFY COLUMN`` (same definition) as a
    successful no-op, so re-running the ALTER is safe.
    """
    if not _column_exists("conversations", "user_id"):
        return
    with engine.begin() as conn:
        # MODIFY COLUMN with the new (nullable) definition. We don't
        # add a new index because ``user_id`` is already an FK and
        # the implicit index on the FK covers the new nullable column
        # too.
        conn.execute(
            text(
                "ALTER TABLE conversations "
                "MODIFY COLUMN user_id INT NULL"
            )
        )


def ensure_conversations_external_fks() -> None:
    """Add ``external_app_id`` + ``external_visitor_id`` FK columns
    to ``conversations`` if they're missing.

    Both columns are nullable (per spec § 4.3 mutual-exclusion). The
    service layer (later tasks) enforces: internal convs have
    ``user_id NOT NULL`` and both external_*_id NULL; external
    convs have ``user_id IS NULL`` and both external_*_id NOT NULL.

    DB-level FK constraints are added ONLY when the referenced
    table exists — Task 3 (``ensure_external_apps_tables``) is the
    one that creates ``external_apps`` and ``external_visitors``.
    If Task 2 runs first, we still add the columns + indexes (so
    the application code works) and skip the FK constraint. The
    ORM-level FK reference is metadata-only and the DB will accept
    inserts/updates fine without the constraint; referential
    integrity is then enforced at the service layer.

    Idempotency strategy (matches the house pattern used by
    ``ensure_conversations_team_id`` / ``ensure_documents_created_by``
    / ``ensure_conversations_deleted_at``):

    - **Top-level short-circuit**: if both new columns already exist,
      return early. The assumption is "columns ⇒ indexes ⇒ FKs" — the
      migration adds them all in the same first-run block, so a
      fully-migrated DB hits this gate and does nothing.
    - **Steady-state FKs**: the ``_fk_exists`` helper gates the
      ``ADD CONSTRAINT`` so re-running is a clean no-op (no
      ``try/except`` swallowing arbitrary errors).
    - **Task-ordering safety**: the ``_table_exists`` guard still
      wraps the FK blocks, so a dev DB where Task 3 has not yet
      landed skips the FK cleanly instead of 1216'ing.

    The transient state "columns exist but FKs don't" (because Task 3
    ran after Task 2) is accepted as a rare dev-only edge case: the
    application code keeps working with the service-layer-enforced
    referential integrity, and the FK is added by a one-shot
    follow-up migration after Task 3 lands.
    """
    # Steady-state short-circuit: if both columns exist, we assume
    # the indexes and FKs also exist (we add them all in the same
    # first-run block below). The transient state where columns
    # exist but FKs don't (Task 3 not yet run) is rare and
    # self-heals via a one-shot follow-up migration.
    if _column_exists("conversations", "external_app_id") and _column_exists(
        "conversations", "external_visitor_id"
    ):
        return

    with engine.begin() as conn:
        # Un-gated DDL — the top-level gate guarantees fresh-DB state
        # (columns don't exist yet, so 1060/1061 cannot fire).
        conn.execute(text(
            "ALTER TABLE conversations "
            "ADD COLUMN external_app_id INT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX ix_conversations_external_app_id "
            "ON conversations (external_app_id)"
        ))
        conn.execute(text(
            "ALTER TABLE conversations "
            "ADD COLUMN external_visitor_id INT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX ix_conversations_external_visitor_id "
            "ON conversations (external_visitor_id)"
        ))
        # DB-level FK constraints — only added when the referenced
        # table exists (Task 3 ships the external_apps /
        # external_visitors table creation). The service layer is
        # the primary enforcement point for referential integrity
        # on these columns.
        if _table_exists("external_apps") and not _fk_exists(
            "conversations", "fk_conversations_external_app_id"
        ):
            conn.execute(text(
                "ALTER TABLE conversations "
                "ADD CONSTRAINT fk_conversations_external_app_id "
                "FOREIGN KEY (external_app_id) "
                "REFERENCES external_apps(id)"
            ))
        if _table_exists("external_visitors") and not _fk_exists(
            "conversations", "fk_conversations_external_visitor_id"
        ):
            conn.execute(text(
                "ALTER TABLE conversations "
                "ADD CONSTRAINT fk_conversations_external_visitor_id "
                "FOREIGN KEY (external_visitor_id) "
                "REFERENCES external_visitors(id)"
            ))


def ensure_external_apps_tables() -> None:
    """Create the ``external_apps`` and ``external_visitors`` tables if
    they don't exist. See ExternalChat spec § 4.1 / § 4.2 for the
    schema rationale.

    **Design choice — table creation only (no conversations column work)**:
    This helper deliberately does NOT re-do the
    ``conversations.external_app_id`` / ``external_visitor_id`` columns
    or indexes; those live in ``ensure_conversations_external_fks``,
    which ``main.py`` calls separately. The split matches the house
    "one helper per concern" pattern (compare
    ``ensure_conversations_team_id`` vs. ``ensure_conversations_deleted_at``)
    and keeps each function's idempotency contract auditable in
    isolation. Call order in ``main.startup_event`` is:

    1. ``ensure_conversations_user_id_nullable``
    2. ``ensure_conversations_external_fks`` (adds columns + indexes
       on ``conversations``; FKs are gated on these tables existing)
    3. ``ensure_external_apps_tables`` ← this function

    So by the time we run, ``ensure_conversations_external_fks`` has
    already added the columns and (if applicable) the FKs. The
    "create table" DDL below is a no-op on a dev DB that has the
    tables (gated by ``_table_exists``), and a one-shot on a fresh
    DB / CI DB.

    Schema notes:

    - ``allowed_origins`` / ``allowed_agent_ids`` / ``allowed_team_ids``
      are stored as JSON. The MySQL ``JSON`` type was used in the
      SQLAlchemy model too (see ``app/models/external_app.py``); the
      raw DDL below matches so ``Base.metadata.create_all`` produces
      the same shape on a fresh DB.
    - ``scopes`` default matches the ORM default.
    - Indexes: tenant+active (the hot filter for the admin list view),
      tenant+created (default sort), and created_by (for audit). The
      app_id+visitor_id unique key on ``external_visitors`` is the
      "one row per (app, client uuid)" invariant.
    - FKs: ``external_apps.tenant_id → tenants.id`` (RESTRICT default),
      ``external_apps.created_by → users.id`` (nullable, SET NULL
      would be more natural but MySQL FK actions on nullable cols
      are unreliable in older versions; we leave the user_id ON
      DELETE behaviour to the service layer), and
      ``external_visitors.app_id → external_apps.id`` ON DELETE
      CASCADE (a deleted app takes its visitors with it — they have
      no meaning without the app).

    Idempotency: ``_table_exists`` gates each ``CREATE TABLE``. We
    intentionally do NOT use ``CREATE TABLE IF NOT EXISTS`` here
    because the INFORMATION_SCHEMA-gate pattern matches the rest
    of the file (``ensure_*``) and keeps the DDL statements
    auditable in one place. Re-running this function is a clean
    no-op.
    """
    # Upgrade DESC on the composite indexes BEFORE the early-return.
    # This is what fixes a dev DB that was created by the previous
    # version of this function (which created the indexes without
    # ``DESC`` on the trailing column — see spec § 4.1 / § 4.2). The
    # helper is itself idempotent: on a fresh DB the index doesn't
    # exist yet, so it's a no-op; on a fully-upgraded dev DB the
    # trailing column already has COLLATION='D', so it's also a
    # no-op. See ``ensure_external_apps_indexes_desc`` for the gate
    # logic and the INFORMATION_SCHEMA check.
    ensure_external_apps_indexes_desc()

    # short-circuit if BOTH tables already exist; otherwise fall
    # through and check each one individually (in case a partial
    # state has only one of the two).
    if _table_exists("external_apps") and _table_exists("external_visitors"):
        return

    with engine.begin() as conn:
        if not _table_exists("external_apps"):
            conn.execute(text(
                "CREATE TABLE external_apps ("
                "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "tenant_id INT NOT NULL, "
                "name VARCHAR(100) NOT NULL, "
                "app_key VARCHAR(64) NOT NULL UNIQUE, "
                "app_secret_hash VARCHAR(255) NOT NULL, "
                "allowed_origins JSON NOT NULL, "
                "allowed_agent_ids JSON NOT NULL DEFAULT '[]', "
                "allowed_team_ids JSON NOT NULL DEFAULT '[]', "
                "scopes VARCHAR(255) NOT NULL "
                "DEFAULT 'chat:stream,chat:upload,conv:read', "
                "rate_limit_per_min INT NOT NULL DEFAULT 60, "
                "is_active TINYINT(1) NOT NULL DEFAULT 1, "
                "description TEXT NULL, "
                "created_by INT NULL, "
                "last_used_at DATETIME NULL, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
                "ON UPDATE CURRENT_TIMESTAMP, "
                "INDEX ix_external_apps_tenant_active (tenant_id, is_active), "
                "INDEX ix_external_apps_tenant_created (tenant_id, created_at DESC), "
                "INDEX ix_external_apps_created_by (created_by), "
                "CONSTRAINT fk_external_apps_tenant "
                "FOREIGN KEY (tenant_id) REFERENCES tenants(id), "
                "CONSTRAINT fk_external_apps_created_by "
                "FOREIGN KEY (created_by) REFERENCES users(id)"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            ))

        if not _table_exists("external_visitors"):
            conn.execute(text(
                "CREATE TABLE external_visitors ("
                "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "app_id INT NOT NULL, "
                "visitor_id VARCHAR(64) NOT NULL, "
                "display_name VARCHAR(100) NULL, "
                "visitor_metadata JSON NULL, "
                "first_seen_at DATETIME NOT NULL, "
                "last_seen_at DATETIME NOT NULL, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
                "ON UPDATE CURRENT_TIMESTAMP, "
                "UNIQUE KEY uq_external_visitors_app_visitor "
                "(app_id, visitor_id), "
                "INDEX ix_external_visitors_app_lastseen (app_id, last_seen_at DESC), "
                "CONSTRAINT fk_external_visitors_app "
                "FOREIGN KEY (app_id) REFERENCES external_apps(id) "
                "ON DELETE CASCADE"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
            ))


def ensure_external_apps_indexes_desc() -> None:
    """Upgrade the composite indexes on ``external_apps`` /
    ``external_visitors`` to have ``DESC`` on the trailing column,
    per ExternalChat spec § 4.1 / § 4.2.

    MySQL 8.0+ supports descending indexes natively, but it does NOT
    support ``ALTER INDEX ... DESC`` — the only way to add DESC to
    an existing composite index is to DROP and re-CREATE it. This
    helper does exactly that, gated on an INFORMATION_SCHEMA check
    so a re-run is a clean no-op.

    **Why this exists**: ``ensure_external_apps_tables`` (commit
    ``dc5495b9``) shipped with the composite indexes missing the
    ``DESC`` keyword on the trailing column. Any dev DB that was
    migrated by that commit has indexes with the right column set
    but the wrong ordering. Re-running the CREATE TABLE block is a
    no-op (tables exist), so the spec-compliance fix needs its own
    migration helper. We run it from the start of
    ``ensure_external_apps_tables`` (before its early-return) so
    every uvicorn boot re-applies the upgrade on legacy dev DBs.

    **Idempotency contract** (the ``_index_trailing_col_desc`` gate):

    - Index doesn't exist (fresh DB, tables not yet created) →
      helper is a no-op; the CREATE TABLE in
      ``ensure_external_apps_tables`` will create the index with
      ``DESC`` the first time it runs.
    - Index exists, trailing column already has ``COLLATION='D'``
      (fully-upgraded dev DB) → helper is a no-op.
    - Index exists, trailing column has ``COLLATION='A'`` (legacy
      dev DB) → helper DROPs and re-CREATEs the index with
      ``DESC``. The transaction is per-statement (DDL in MySQL is
      auto-committed), so a mid-flight failure leaves the table
      without the index; the next boot will re-attempt the
      recreation.

    Called from ``ensure_external_apps_tables``; **not** exported
    through ``main.startup_event`` separately — the public entry
    point for callers is still ``ensure_external_apps_tables``.
    """
    with engine.begin() as conn:
        # external_apps: (tenant_id, created_at DESC)
        # Fresh-DB path: index doesn't exist → _index_trailing_col_desc
        # returns True, we skip. Dev-DB path: if ASC, drop + recreate.
        if _index_exists("external_apps", "ix_external_apps_tenant_created") and \
                not _index_trailing_col_desc(
                    "external_apps", "ix_external_apps_tenant_created"
                ):
            conn.execute(text(
                "ALTER TABLE external_apps "
                "DROP INDEX ix_external_apps_tenant_created"
            ))
            conn.execute(text(
                "CREATE INDEX ix_external_apps_tenant_created "
                "ON external_apps (tenant_id, created_at DESC)"
            ))

        # external_visitors: (app_id, last_seen_at DESC)
        # Same pattern.
        if _index_exists("external_visitors", "ix_external_visitors_app_lastseen") and \
                not _index_trailing_col_desc(
                    "external_visitors", "ix_external_visitors_app_lastseen"
                ):
            conn.execute(text(
                "ALTER TABLE external_visitors "
                "DROP INDEX ix_external_visitors_app_lastseen"
            ))
            conn.execute(text(
                "CREATE INDEX ix_external_visitors_app_lastseen "
                "ON external_visitors (app_id, last_seen_at DESC)"
            ))


def ensure_model_configs_purpose_flags() -> None:
    """Add ``is_chat`` / ``is_embedding`` to ``model_configs`` if missing.

    Idempotent: re-running is a no-op. Default values are chosen to
    match the historical behavior of the application:

    - is_chat=True: every existing ModelConfig row was implicitly a
      chat model (no row was ever used purely for embedding).
    - is_embedding=False: legacy rows are NOT marked as embedding
      capable. The startup migration script
      ``migrate_embedding_model_config`` flips this to True for the
      canonical ``nomic-embed-text`` row it auto-creates for legacy
      KBs, so the UX after startup is: existing KBs still find their
      embedding model, but new users see the proper boolean.
    """
    with engine.begin() as conn:
        if not _column_exists("model_configs", "is_chat"):
            conn.execute(text(
                "ALTER TABLE model_configs "
                "ADD COLUMN is_chat TINYINT(1) NOT NULL DEFAULT 1"
            ))
        if not _column_exists("model_configs", "is_embedding"):
            conn.execute(text(
                "ALTER TABLE model_configs "
                "ADD COLUMN is_embedding TINYINT(1) NOT NULL DEFAULT 0"
            ))
        # Unique constraint (tenant_id, model_type, model_name).
        # MySQL allows multiple NULLs in a UNIQUE index, so global-config
        # rows (tenant_id IS NULL) won't conflict with each other or
        # with tenant rows.
        # Idempotency guard: CREATE INDEX is not idempotent in MySQL
        # (1061 "Duplicate key name" on second call) and this function
        # is called on every uvicorn boot.
        if not _index_exists("model_configs", "uq_model_configs_tenant_type_name"):
            conn.execute(text(
                "CREATE UNIQUE INDEX uq_model_configs_tenant_type_name "
                "ON model_configs (tenant_id, model_type, model_name)"
            ))


def ensure_model_configs_image_flag() -> None:
    """M22: add ``is_image_generation`` to ``model_configs`` if missing.

    Idempotent migration: guards with ``_column_exists`` and uses
    ``engine.begin()`` for a transaction so the ALTER rolls back on
    failure. Default is ``FALSE`` — legacy rows are NOT marked as
    image-generation capable (no model in production today is
    configured for image generation). The image-generation admin UI
    flips this to True for rows configured with a provider that
    supports it (e.g. OpenAI ``dall-e-3``, ``gpt-image-1``).

    Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §3.1
    """
    if _column_exists("model_configs", "is_image_generation"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE model_configs "
            "ADD COLUMN is_image_generation BOOLEAN NOT NULL DEFAULT FALSE "
            "COMMENT 'Usable as an image generation model'"
        ))


def ensure_model_configs_tts_subtitle_flags() -> None:
    """M35: add ``is_tts`` + ``is_subtitle_generation`` to ``model_configs``.

    Two new capability flags following the M22 ``is_image_generation``
    pattern. Idempotent via per-column ``_column_exists`` guard. Default
    is FALSE so legacy rows are not retroactively flagged — admins
    explicitly opt-in by configuring a TTS / subtitle provider.

    Both columns use the same BOOLEAN NOT NULL DEFAULT FALSE shape as
    ``is_image_generation`` so the existing API filter pattern
    (``is_X = TRUE`` exact match) works without changes.
    """
    if not _column_exists("model_configs", "is_tts"):
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE model_configs "
                "ADD COLUMN is_tts BOOLEAN NOT NULL DEFAULT FALSE "
                "COMMENT 'M35: Usable as a TTS (text-to-speech) model'"
            ))
    if not _column_exists("model_configs", "is_subtitle_generation"):
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE model_configs "
                "ADD COLUMN is_subtitle_generation BOOLEAN NOT NULL DEFAULT FALSE "
                "COMMENT 'M35: Usable as a subtitle generation model'"
            ))


def ensure_model_configs_video_flag() -> None:
    """M36: add ``is_video`` to ``model_configs``.

    Capability flag for the future video-generation provider layer
    (Kling / Sora / Veo / Wan). M36 ships the composition side
    (``video_compose`` workflow node + ``build_video_from_assets``), but
    no provider consumes this flag yet — it's reserved so the API filter
    ``?is_video=true`` and the frontend model dropdown are wired from
    day one.

    Idempotent via ``_column_exists``. Default FALSE so legacy model
    rows are not retroactively flagged; admins opt-in by configuring a
    video-gen provider (M36.2).
    """
    if _column_exists("model_configs", "is_video"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE model_configs "
            "ADD COLUMN is_video BOOLEAN NOT NULL DEFAULT FALSE "
            "COMMENT 'M36: Usable as a video generation model (Kling/Sora/Veo future)'"
        ))


def ensure_settings_model_fk_columns() -> None:
    """M31: convert ``system_settings.default_model`` /
    ``.embedding_model`` from VARCHAR(50) (free-text) to INT FK → ``model_configs.id``.

    The legacy columns stored free-text model names like
    ``"qwen2.5:7b"``. That had three problems: typo-prone, no
    consistency with the rest of the codebase (which has been on
    ``model_configs.id`` integer refs since M13), and silent breakage
    when an admin renames or soft-deletes a model. The new columns
    are nullable INT with an index and ``ON DELETE RESTRICT`` FK.

    Idempotent: re-running is a no-op once the columns are INT + FK.
    The hot-patch defensive branch handles the case where a future
    release accidentally reintroduced the columns as String — any
    non-integer values are NULL'd out (acceptable: the user simply
    has to re-pick in the UI).

    Mirrors the ``ensure_kb_embedding_model_config_id`` pattern
    (database.py:712+) which made the same VARCHAR → INT FK transition
    for ``knowledge_bases.embedding_model_config_id``.
    """
    _COLS = [
        ("default_model", "idx_system_settings_default_model", "fk_system_settings_default_model"),
        ("embedding_model", "idx_system_settings_embedding_model", "fk_system_settings_embedding_model"),
    ]
    for column, index_name, fk_name in _COLS:
        if not _column_exists("system_settings", column):
            with engine.begin() as conn:
                conn.execute(text(
                    f"ALTER TABLE system_settings "
                    f"ADD COLUMN {column} INT NULL"
                ))
                conn.execute(text(
                    f"CREATE INDEX {index_name} "
                    f"ON system_settings ({column})"
                ))
                conn.execute(text(
                    f"ALTER TABLE system_settings "
                    f"ADD CONSTRAINT {fk_name} "
                    f"FOREIGN KEY ({column}) "
                    f"REFERENCES model_configs(id) ON DELETE RESTRICT"
                ))
            continue

        # Column exists — make sure it's INT and the FK is in place.
        # Defensive against a future hot-patch that re-ADDed the column
        # as VARCHAR; NULL out non-integer leftovers then MODIFY.
        with engine.begin() as conn:
            data_type = conn.execute(
                text(
                    "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'system_settings' "
                    "AND COLUMN_NAME = :c"
                ),
                {"c": column},
            ).scalar()
            if data_type != "int":
                # NULL out any non-integer leftover rows so MODIFY
                # doesn't trip on conversion failure.
                conn.execute(text(
                    f"UPDATE system_settings SET {column} = NULL "
                    f"WHERE {column} IS NOT NULL "
                    f"AND {column} NOT REGEXP '^[0-9]+$'"
                ))
                conn.execute(text(
                    f"ALTER TABLE system_settings "
                    f"MODIFY COLUMN {column} INT NULL"
                ))
            if not _fk_exists("system_settings", fk_name):
                conn.execute(text(
                    f"ALTER TABLE system_settings "
                    f"ADD CONSTRAINT {fk_name} "
                    f"FOREIGN KEY ({column}) "
                    f"REFERENCES model_configs(id) ON DELETE RESTRICT"
                ))


def ensure_kb_embedding_model_config_id() -> None:
    """Add ``embedding_model_config_id`` FK to ``knowledge_bases``.

    Nullable during the migration period; will be flipped to NOT NULL
    in a follow-up release once we're confident every KB has a config.
    ``ON DELETE RESTRICT`` is the safety net: if someone ever changes
    ``DELETE /models/{id}`` to a real hard-delete, KBs won't be
    silently orphaned.
    """
    if _column_exists("knowledge_bases", "embedding_model_config_id"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE knowledge_bases "
            "ADD COLUMN embedding_model_config_id INT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX idx_kb_embedding_model_config_id "
            "ON knowledge_bases (embedding_model_config_id)"
        ))
        conn.execute(text(
            "ALTER TABLE knowledge_bases "
            "ADD CONSTRAINT fk_kb_embedding_model_config_id "
            "FOREIGN KEY (embedding_model_config_id) "
            "REFERENCES model_configs(id) ON DELETE RESTRICT"
        ))


def ensure_documents_embedding_model_config_id() -> None:
    """Add ``embedding_model_config_id`` FK to ``documents``.

    Records which embedding model was used to embed the document at
    ingest time. Nullable during the migration period; the migration
    script backfills it from the parent KB.
    """
    if _column_exists("documents", "embedding_model_config_id"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE documents "
            "ADD COLUMN embedding_model_config_id INT NULL"
        ))
        conn.execute(text(
            "CREATE INDEX idx_documents_embedding_model_config_id "
            "ON documents (embedding_model_config_id)"
        ))
        conn.execute(text(
            "ALTER TABLE documents "
            "ADD CONSTRAINT fk_documents_embedding_model_config_id "
            "FOREIGN KEY (embedding_model_config_id) "
            "REFERENCES model_configs(id) ON DELETE RESTRICT"
        ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_embedding_model_config_migrated() -> None:
    """Run the one-shot migration; idempotent — safe to call on every startup."""
    from lumen_scripts.migrate_embedding_model_config import (
        migrate_embedding_model_config,
    )

    session = SessionLocal()
    try:
        report = migrate_embedding_model_config(session)
        import logging
        logging.getLogger(__name__).info(
            f"embedding_model_config migration: scanned={report.kbs_scanned} "
            f"linked={report.kbs_linked} configs_created={report.configs_created} "
            f"docs_backfilled={report.docs_backfilled}"
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "ensure_embedding_model_config_migrated failed; will retry on next startup"
        )
    finally:
        session.close()


def ensure_workflow_model_refs_migrated() -> None:
    """Run the one-shot workflow ``model_config_id`` migration if any
    un-migrated LLM nodes exist. Idempotent: subsequent calls are
    no-ops. Safe to call on every startup.
    """
    from lumen_scripts.migrate_workflow_model_refs import migrate_workflow_model_refs

    session = SessionLocal()
    try:
        migrate_workflow_model_refs(session)
    except Exception:
        # Don't block app startup on a migration hiccup; log and continue.
        import logging
        logging.getLogger(__name__).exception(
            "ensure_workflow_model_refs_migrated failed; will retry on next startup"
        )
    finally:
        session.close()


def ensure_workflow_v2_migrated() -> None:
    """Run the one-shot migration; idempotent — safe to call on every startup."""
    from lumen_scripts.migrate_workflow_to_v2 import migrate_all_workflows

    db = SessionLocal()
    try:
        result = migrate_all_workflows(db, dry_run=False)
        import logging
        logging.getLogger(__name__).info(
            f"workflow_v2 migration: scanned={result['scanned']} "
            f"migrated={result['migrated']} skipped={result['skipped']} "
            f"errors={len(result['errors'])}"
        )
    finally:
        db.close()


def ensure_global_memories_conversation_id() -> None:
    """Add ``conversation_id`` to ``global_memories`` if it's missing.

    M15: lets the /dashboard/memory UI distinguish "this global
    memory row came from the currently selected conversation" from
    "it came from some other conversation" — the page dims
    current-conv rows and offers a "只看其它会话" toggle that
    filters them out.

    Nullable because every existing row was written without this
    column; legacy NULL is treated by the UI as "unknown source"
    (no dim, never filtered as "current"). The composite index
    (tenant_id, conversation_id, created_at) supports the
    future "exclude this conversation" server-side filter and the
    current cap-window scans.

    On any failure (e.g. MySQL MDL held by a stale uvicorn worker —
    see MEMORY.md "taskkill /F" entry), log and return so app
    startup continues; the next restart will retry the migration.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        with engine.begin() as conn:
            if not _column_exists("global_memories", "conversation_id"):
                conn.execute(text(
                    "ALTER TABLE global_memories "
                    "ADD COLUMN conversation_id INT NULL"
                ))
            if not _index_exists("global_memories", "idx_global_tenant_conv_created"):
                conn.execute(text(
                    "CREATE INDEX idx_global_tenant_conv_created "
                    "ON global_memories (tenant_id, conversation_id, created_at)"
                ))
    except Exception:
        logger.exception(
            "ensure_global_memories_conversation_id failed; will retry on next startup"
        )


def ensure_marketplace_type_column() -> None:
    """M16 migration: add ``type`` and ``type_config`` columns to
    ``skill_marketplace``.

    - ``type``: VARCHAR(20) NOT NULL DEFAULT 'prompt'. Discriminator
      column for the new skill type abstraction. Values:
      ``prompt`` (legacy text-prompt skills, also the default for any
      pre-existing row), ``script`` (Python sandboxed), ``http``
      (external HTTP endpoint). The index supports the
      "filter by type" filter on the marketplace list endpoint.
    - ``type_config``: JSON NULL. Per-type config payload
      (e.g. inline source code for script skills, endpoint URL /
      method / headers for http skills). NULL for prompt skills —
      the prompt body lives in the existing ``content`` column.

    Idempotent: every DDL statement is gated on
    ``_column_exists`` / ``_index_exists`` so re-running on every
    uvicorn boot is a clean no-op. Pattern mirrors
    ``ensure_conversations_deleted_at`` and
    ``ensure_model_configs_purpose_flags``.

    If ``type`` already exists but was added by an older migration
    that didn't enforce NOT NULL DEFAULT (e.g. M16 pre-finalization
    on a long-running dev DB), we ALTER it to the canonical shape.
    Backfilling NULL rows with 'prompt' must precede the NOT NULL
    tightening, otherwise the ALTER fails on existing data.

    On any failure (e.g. MySQL MDL held by a stale uvicorn worker —
    see MEMORY.md "taskkill /F" entry), log and return so app
    startup continues; the next restart will retry the migration.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        with engine.begin() as conn:
            if not _column_exists("skill_marketplace", "type"):
                conn.execute(text(
                    "ALTER TABLE skill_marketplace "
                    "ADD COLUMN type VARCHAR(20) NOT NULL DEFAULT 'prompt'"
                ))
            else:
                # If existing column lacks NOT NULL or DEFAULT 'prompt',
                # tighten it. Backfill NULLs first to satisfy NOT NULL.
                col_row = conn.execute(text(
                    "SELECT IS_NULLABLE, COLUMN_DEFAULT "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "  AND TABLE_NAME = 'skill_marketplace' "
                    "  AND COLUMN_NAME = 'type'"
                )).first()
                needs_tighten = (
                    col_row is not None
                    and (col_row.IS_NULLABLE == "YES"
                         or col_row.COLUMN_DEFAULT is None
                         or "prompt" not in str(col_row.COLUMN_DEFAULT))
                )
                if needs_tighten:
                    conn.execute(text(
                        "UPDATE skill_marketplace "
                        "SET type = 'prompt' WHERE type IS NULL"
                    ))
                    conn.execute(text(
                        "ALTER TABLE skill_marketplace "
                        "MODIFY COLUMN type VARCHAR(20) NOT NULL DEFAULT 'prompt'"
                    ))
            if not _column_exists("skill_marketplace", "type_config"):
                conn.execute(text(
                    "ALTER TABLE skill_marketplace "
                    "ADD COLUMN type_config JSON NULL"
                ))
            if not _index_exists("skill_marketplace", "ix_skill_marketplace_type"):
                conn.execute(text(
                    "CREATE INDEX ix_skill_marketplace_type "
                    "ON skill_marketplace (type)"
                ))
    except Exception:
        logger.exception(
            "ensure_marketplace_type_column failed; will retry on next startup"
        )


def ensure_llm_call_logs_table() -> None:
    """M26: create ``llm_call_logs`` table + composite indexes if missing.

    Mirrors the house ``ensure_*`` pattern (gates on ``_table_exists`` /
    ``_index_exists`` so re-running on every uvicorn boot is a no-op).
    We intentionally do NOT use ``CREATE TABLE IF NOT EXISTS`` to match
    the surrounding style; the table-creation is one-shot on a fresh
    DB and a no-op on a dev DB that already has the table.

    Schema notes:

    - JSON columns for ``messages`` / ``tool_calls`` / ``system_messages``
      — full payload storage is the explicit M26 design choice
      (DB may grow fast; M27+ will revisit gzip / archival).
    - ``call_id`` is a UUID string (unique) — distinguishes individual
      LLM invocations inside a single user request (chat stream +
      follow-up tool rounds).
    - ``trace_id`` groups all calls for one user message. The
      ``(trace_id, call_index)`` index lets the UI fetch a trace's
      full timeline cheaply.
    - ``parent_call_id`` links nested calls (e.g. an aggregated LLM
      that was synthesised from N worker LLM calls inside a team
      orchestration).
    - The composite indexes target the most common filter shapes the
      new ``/logs/llm-calls`` UI will issue: tenant+time, module+time,
      model+time, conversation+time, workflow+run, status+time.

    Spec: docs/superpowers/specs/2026-06-14-llm-call-logging-design.md
    """
    from lumen_models.llm_call_log import LLMCallLog  # noqa
    if _table_exists("llm_call_logs"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE llm_call_logs ("
            "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
            "call_id VARCHAR(36) NOT NULL, "
            "parent_call_id VARCHAR(36) NULL, "
            "trace_id VARCHAR(36) NOT NULL, "
            "call_type VARCHAR(64) NOT NULL, "
            "call_index INT NOT NULL DEFAULT 0, "
            "tenant_id INT NULL, "
            "user_id INT NULL, "
            "username VARCHAR(100) NULL, "
            "client_app VARCHAR(50) NULL, "
            "conversation_id INT NULL, "
            "message_id INT NULL, "
            "agent_id INT NULL, "
            "team_id INT NULL, "
            "team_member_id INT NULL, "
            "workflow_id INT NULL, "
            "workflow_run_id INT NULL, "
            "workflow_node_id VARCHAR(64) NULL, "
            "image_id INT NULL, "
            "model_type VARCHAR(50) NULL, "
            "model_name VARCHAR(100) NOT NULL, "
            "model_config_id INT NULL, "
            "temperature FLOAT NULL, "
            "max_tokens INT NULL, "
            "system_messages JSON NULL, "
            "user_message TEXT NULL, "
            "messages JSON NULL, "
            "tools JSON NULL, "
            "extra_params JSON NULL, "
            "input_chars INT NULL, "
            "input_tokens_estimate INT NULL, "
            "response_content TEXT NULL, "
            "finish_reason VARCHAR(50) NULL, "
            "tool_calls JSON NULL, "
            "output_chars INT NULL, "
            "output_tokens_estimate INT NULL, "
            "token_usage JSON NULL, "
            "started_at DATETIME NOT NULL, "
            "finished_at DATETIME NULL, "
            "duration_ms INT NULL, "
            "first_token_latency_ms INT NULL, "
            "status VARCHAR(20) NULL DEFAULT 'success', "
            "error_type VARCHAR(100) NULL, "
            "error_message TEXT NULL, "
            "retry_count INT NULL DEFAULT 0, "
            "request_ip VARCHAR(50) NULL, "
            "user_agent VARCHAR(500) NULL, "
            "extra JSON NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP, "
            "UNIQUE KEY uq_lcl_call_id (call_id), "
            "INDEX idx_lcl_parent_call_id (parent_call_id), "
            "INDEX idx_lcl_trace_id (trace_id), "
            "INDEX idx_lcl_tenant_id (tenant_id), "
            "INDEX idx_lcl_user_id (user_id), "
            "INDEX idx_lcl_conversation_id (conversation_id), "
            "INDEX idx_lcl_message_id (message_id), "
            "INDEX idx_lcl_agent_id (agent_id), "
            "INDEX idx_lcl_team_id (team_id), "
            "INDEX idx_lcl_workflow_id (workflow_id), "
            "INDEX idx_lcl_workflow_run_id (workflow_run_id), "
            "INDEX idx_lcl_image_id (image_id), "
            "INDEX idx_lcl_model_config_id (model_config_id), "
            "INDEX idx_lcl_status (status), "
            "INDEX idx_lcl_tenant_time (tenant_id, created_at), "
            "INDEX idx_lcl_module_time (call_type, created_at), "
            "INDEX idx_lcl_model_time (model_name, created_at), "
            "INDEX idx_lcl_conv_time (conversation_id, created_at), "
            "INDEX idx_lcl_workflow (workflow_id, workflow_run_id), "
            "INDEX idx_lcl_trace (trace_id, call_index), "
            "INDEX idx_lcl_status_time (status, created_at), "
            "CONSTRAINT fk_lcl_tenant_id "
            "FOREIGN KEY (tenant_id) REFERENCES tenants(id), "
            "CONSTRAINT fk_lcl_user_id "
            "FOREIGN KEY (user_id) REFERENCES users(id), "
            "CONSTRAINT fk_lcl_conversation_id "
            "FOREIGN KEY (conversation_id) REFERENCES conversations(id), "
            "CONSTRAINT fk_lcl_message_id "
            "FOREIGN KEY (message_id) REFERENCES messages(id), "
            "CONSTRAINT fk_lcl_agent_id "
            "FOREIGN KEY (agent_id) REFERENCES agents(id), "
            "CONSTRAINT fk_lcl_team_id "
            "FOREIGN KEY (team_id) REFERENCES agent_teams(id), "
            "CONSTRAINT fk_lcl_workflow_id "
            "FOREIGN KEY (workflow_id) REFERENCES workflows(id), "
            "CONSTRAINT fk_lcl_workflow_run_id "
            "FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id), "
            "CONSTRAINT fk_lcl_image_id "
            "FOREIGN KEY (image_id) REFERENCES generated_images(id), "
            "CONSTRAINT fk_lcl_model_config_id "
            "FOREIGN KEY (model_config_id) REFERENCES model_configs(id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ))


def ensure_generated_images_table() -> None:
    """Create ``generated_images`` table if it doesn't exist.

    Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §3.2

    Uses ``Base.metadata.create_all`` which is idempotent — safe to call
    on every uvicorn restart. Existing tables are not touched.

    Note: this only creates the table; subsequent column-level
    migrations (none today) would need their own ``ensure_*`` helper
    following the ``_column_exists`` pattern used by the other
    migrations in this file.
    """
    from lumen_models.image_generation import GeneratedImage  # noqa
    Base.metadata.create_all(bind=engine, tables=[GeneratedImage.__table__])


def ensure_generated_audios_table() -> None:
    """M35: create ``generated_audios`` table if it doesn't exist.

    Mirrors the M22 ``ensure_generated_images_table`` pattern — uses
    ``Base.metadata.create_all`` which is idempotent. The table is
    declared on ``GeneratedAudio`` (lumen_models.tts) with all
    composite indexes (``ix_gen_audios_tenant_status_created``) so
    list pages stay fast.
    """
    from lumen_models.tts import GeneratedAudio  # noqa
    Base.metadata.create_all(bind=engine, tables=[GeneratedAudio.__table__])


def ensure_subtitles_table() -> None:
    """M35: create ``subtitles`` table if it doesn't exist.

    Idempotent via ``Base.metadata.create_all``. The composite index
    ``ix_subtitles_tenant_created`` keeps the per-tenant history list
    query O(log n) on (tenant_id, created_at DESC).
    """
    from lumen_models.subtitle import Subtitle  # noqa
    Base.metadata.create_all(bind=engine, tables=[Subtitle.__table__])


def ensure_playbooks_table() -> None:
    """M35: create ``playbooks`` table if it doesn't exist.

    The unique index ``uq_playbook_tenant_name`` on (tenant_id, name) is
    declared in ``Playbook.__table_args__`` and created automatically by
    ``create_all``. Built-in playbooks share ``tenant_id=1``; per-tenant
    custom playbooks use the tenant's own id.
    """
    from lumen_models.playbook import Playbook  # noqa
    Base.metadata.create_all(bind=engine, tables=[Playbook.__table__])


def ensure_stock_assets_table() -> None:
    """M36.2.1: create ``stock_assets`` table if it doesn't exist.

    Mirrors the M22/M35 ``ensure_*`` pattern — ``Base.metadata.create_all``
    is idempotent. The composite index ``ix_stock_assets_category_created``
    is declared in ``StockAsset.__table_args__`` and is created
    automatically, keeping the gallery list query O(log n) on
    ``(category, created_at DESC)``.
    """
    from lumen_models.stock_asset import StockAsset  # noqa
    Base.metadata.create_all(bind=engine, tables=[StockAsset.__table__])


def ensure_stock_musics_table() -> None:
    """M36.2.2: create ``stock_musics`` table if it doesn't exist.

    Mirrors ``ensure_stock_assets_table`` (M36.2.1) — the model declares
    ``ix_stock_musics_category_created`` in ``StockMusic.__table_args__``
    so ``create_all`` picks it up automatically, keeping the gallery
    list query O(log n) on ``(category, created_at DESC)``.
    """
    from lumen_models.stock_music import StockMusic  # noqa
    Base.metadata.create_all(bind=engine, tables=[StockMusic.__table__])


def ensure_generated_videos_table() -> None:
    """M36: create ``generated_videos`` table if it doesn't exist.

    Mirrors ``ensure_generated_audios_table`` (M35) — ``Base.metadata.
    create_all`` is idempotent, so re-running is a no-op. The composite
    index ``ix_gen_videos_tenant_status_created`` is declared on
    ``GeneratedVideo.__table_args__`` and created automatically, keeping
    the per-tenant history list query O(log n) on
    (tenant_id, status, created_at DESC).

    The table also references ``conversations`` / ``generated_audios`` /
    ``subtitles`` / ``playbooks`` via FK — those tables are created by
    earlier ``ensure_*`` calls (M22/M35/M1), so this must run AFTER
    them in the startup sequence (wired in ``lumen_main.py``).
    """
    from lumen_models.video import GeneratedVideo  # noqa
    Base.metadata.create_all(bind=engine, tables=[GeneratedVideo.__table__])


def ensure_agent_kb_retrieval_config() -> None:
    """M21: add ``kb_retrieval_config`` JSON column to ``agents``.

    Per-agent knob for the multi-KB RAG retrieval that M21 introduces:

    - ``top_k`` (int): how many chunks to fetch from EACH bound KB
      before fusion. Default 3 (was the single-KB hard-coded value).
    - ``rrf_k`` (int): RRF (Reciprocal Rank Fusion) constant — bigger
      = flatter weighting across ranks. Default 30 (the canonical
      RRF constant used in the original Cormack et al. 2009 paper
      and in most production RAG stacks; matches the value used in
      the T4 _rrf_fuse unit test).

    Stored as a JSON object so we can extend it (e.g. with
    per-KB weight overrides) in a follow-up release without another
    migration. Nullable + backfilled on legacy rows so the column
    has a sane default the moment a row is read by the runner.

    Idempotent: ``_column_exists`` guards the ALTER; the backfill
    UPDATE is gated on ``IS NULL`` so re-running is a no-op even if
    the user has since edited a row's config.

    On any failure (e.g. MySQL MDL held by a stale uvicorn worker —
    see MEMORY.md "taskkill /F" entry), log and return so app
    startup continues; the next restart will retry the migration.
    """
    import json as _json
    import logging
    logger = logging.getLogger(__name__)
    try:
        with engine.begin() as conn:
            if not _column_exists("agents", "kb_retrieval_config"):
                conn.execute(text(
                    "ALTER TABLE agents "
                    "ADD COLUMN kb_retrieval_config JSON"
                ))
            # Backfill legacy rows. IS NULL guard makes this safe to
            # re-run; the bound parameter carries the JSON literal
            # (NOT a string — MySQL would happily accept a string for
            # a JSON column but pymysql's parameter binding becomes
            # ambiguous around JSON quoting).
            conn.execute(
                text(
                    "UPDATE agents SET kb_retrieval_config = :default "
                    "WHERE kb_retrieval_config IS NULL"
                ).bindparams(default=_json.dumps({"top_k": 3, "rrf_k": 30}))
            )
    except Exception:
        logger.exception(
            "ensure_agent_kb_retrieval_config failed; will retry on next startup"
        )


def ensure_embedding_call_logs_table() -> None:
    """M27: create ``embedding_call_logs`` table + composite indexes if missing.

    Mirrors ``ensure_llm_call_logs_table`` (M26). Idempotent — guards on
    ``_table_exists`` so re-running on every uvicorn boot is a no-op.

    Schema notes:
    - text is NOT stored in full — ``text_preview`` is the first 200
      chars, ``text_chars`` records the full character count.
    - Embedding vectors are NEVER stored (a 768d float32 vector is ~3KB
      and a 1M-row table would be 3GB — not worth it). Only ``embedding_dim``
      and ``embedding_bytes`` are recorded.
    - JSON ``extra`` column stores per-call hints (e.g.
      ``{is_dim_probe: true}`` for cold-start probes, or top_k /
      filter_expr for retrieval calls).

    Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md
    """
    from lumen_models.embedding_call_log import EmbeddingCallLog  # noqa
    if _table_exists("embedding_call_logs"):
        return
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE embedding_call_logs ("
            "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
            "call_id VARCHAR(36) NOT NULL, "
            "parent_call_id VARCHAR(36) NULL, "
            "trace_id VARCHAR(36) NOT NULL, "
            "call_type VARCHAR(64) NOT NULL, "
            "call_index INT NOT NULL DEFAULT 0, "
            "tenant_id INT NULL, "
            "user_id INT NULL, "
            "username VARCHAR(100) NULL, "
            "client_app VARCHAR(50) NULL, "
            "conversation_id INT NULL, "
            "agent_id INT NULL, "
            "team_id INT NULL, "
            "workflow_id INT NULL, "
            "workflow_run_id INT NULL, "
            "workflow_node_id VARCHAR(64) NULL, "
            "knowledge_base_id INT NULL, "
            "model_type VARCHAR(50) NULL, "
            "model_name VARCHAR(100) NOT NULL, "
            "model_config_id INT NULL, "
            "text_preview VARCHAR(200) NULL, "
            "text_chars INT NULL, "
            "is_batch TINYINT(1) NOT NULL DEFAULT 0, "
            "batch_size INT NULL, "
            "embedding_dim INT NULL, "
            "embedding_bytes INT NULL, "
            "started_at DATETIME NOT NULL, "
            "finished_at DATETIME NULL, "
            "duration_ms INT NULL, "
            "status VARCHAR(20) NULL DEFAULT 'success', "
            "error_type VARCHAR(100) NULL, "
            "error_message TEXT NULL, "
            "retry_count INT NULL DEFAULT 0, "
            "request_ip VARCHAR(50) NULL, "
            "user_agent VARCHAR(500) NULL, "
            "extra JSON NULL, "
            "archived_at DATETIME NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP, "
            "UNIQUE KEY uq_ecl_call_id (call_id), "
            "INDEX idx_ecl_parent_call_id (parent_call_id), "
            "INDEX idx_ecl_trace_id (trace_id), "
            "INDEX idx_ecl_tenant_id (tenant_id), "
            "INDEX idx_ecl_user_id (user_id), "
            "INDEX idx_ecl_conversation_id (conversation_id), "
            "INDEX idx_ecl_agent_id (agent_id), "
            "INDEX idx_ecl_team_id (team_id), "
            "INDEX idx_ecl_workflow_id (workflow_id), "
            "INDEX idx_ecl_workflow_run_id (workflow_run_id), "
            "INDEX idx_ecl_knowledge_base_id (knowledge_base_id), "
            "INDEX idx_ecl_model_config_id (model_config_id), "
            "INDEX idx_ecl_status (status), "
            "INDEX idx_ecl_archived (archived_at), "
            "INDEX idx_ecl_tenant_time (tenant_id, created_at), "
            "INDEX idx_ecl_model_time (model_config_id, created_at), "
            "INDEX idx_ecl_kb (knowledge_base_id, created_at), "
            "INDEX idx_ecl_trace (trace_id, call_index), "
            "INDEX idx_ecl_status_time (status, created_at), "
            "INDEX idx_ecl_call_type_time (call_type, created_at), "
            "CONSTRAINT fk_ecl_tenant_id "
            "FOREIGN KEY (tenant_id) REFERENCES tenants(id), "
            "CONSTRAINT fk_ecl_user_id "
            "FOREIGN KEY (user_id) REFERENCES users(id), "
            "CONSTRAINT fk_ecl_conversation_id "
            "FOREIGN KEY (conversation_id) REFERENCES conversations(id), "
            "CONSTRAINT fk_ecl_agent_id "
            "FOREIGN KEY (agent_id) REFERENCES agents(id), "
            "CONSTRAINT fk_ecl_team_id "
            "FOREIGN KEY (team_id) REFERENCES agent_teams(id), "
            "CONSTRAINT fk_ecl_workflow_id "
            "FOREIGN KEY (workflow_id) REFERENCES workflows(id), "
            "CONSTRAINT fk_ecl_workflow_run_id "
            "FOREIGN KEY (workflow_run_id) REFERENCES workflow_runs(id), "
            "CONSTRAINT fk_ecl_knowledge_base_id "
            "FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id), "
            "CONSTRAINT fk_ecl_model_config_id "
            "FOREIGN KEY (model_config_id) REFERENCES model_configs(id)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ))


def ensure_soft_delete_columns() -> None:
    """M27: add ``archived_at DATETIME NULL`` to ``llm_call_logs`` (and
    embedding_call_logs if the table already exists with the original
    M27-prerelease schema that lacked it).

    Idempotent — guards on ``_column_exists``. The retention scheduler
    (``app/services/retention_scheduler.py``) flips ``archived_at`` on
    rows 90+ days old and hard-deletes 180+ day rows.

    Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        with engine.begin() as conn:
            if _table_exists("llm_call_logs") and not _column_exists(
                "llm_call_logs", "archived_at"
            ):
                conn.execute(text(
                    "ALTER TABLE llm_call_logs ADD COLUMN archived_at DATETIME NULL"
                ))
                # Index speeds up the cron's "WHERE archived_at IS NULL"
                # filter when scanning for soft-delete candidates.
                if not _index_exists("llm_call_logs", "idx_lcl_archived"):
                    conn.execute(text(
                        "CREATE INDEX idx_lcl_archived ON llm_call_logs (archived_at)"
                    ))
            if _table_exists("embedding_call_logs") and not _column_exists(
                "embedding_call_logs", "archived_at"
            ):
                conn.execute(text(
                    "ALTER TABLE embedding_call_logs ADD COLUMN archived_at DATETIME NULL"
                ))
                if not _index_exists("embedding_call_logs", "idx_ecl_archived"):
                    conn.execute(text(
                        "CREATE INDEX idx_ecl_archived ON embedding_call_logs (archived_at)"
                    ))
    except Exception:
        logger.exception(
            "ensure_soft_delete_columns failed; will retry on next startup"
        )


def ensure_faq_entries_table() -> None:
    """M31: create the ``faq_entries`` table for the Q&A entry feature.

    Each row is a manually-entered Q&A pair (1 row → 1 virtual
    ``Document`` (doc_type='qa_pair') + 1 ``DocumentChunk``). The
    chunk is what gets embedded into the per-KB vector store; the
    FAQEntry row is the user-facing CRUD handle (question/answer/
    category/tags editable via the API).

    Idempotency: gated on ``_table_exists`` so re-running on every
    uvicorn boot is a clean no-op. We intentionally do NOT use
    ``CREATE TABLE IF NOT EXISTS`` here — the rest of the file's
    ``ensure_*`` helpers all use the INFORMATION_SCHEMA-gate
    pattern, and the test
    ``tests/unit/test_ensure_faq_entries.py`` locks the contract
    that calling this twice never raises.

    Schema notes:
    - ``tenant_id`` is intentionally NOT a column. Tenant isolation
      goes through ``knowledge_bases.tenant_id`` via JOIN at the
      API layer (same convention as ``Document.tenant_id`` — the
      column exists on the row for audit but isn't the source of
      truth for isolation; the parent KB is).
    - ``tags`` is JSON (list of strings) to match the project's
      ``MarketplaceSkill.type_config`` convention.
    - FK actions: ON DELETE CASCADE on the KB / doc / chunk FKs
      so the OS-level cleanup is atomic; ON DELETE RESTRICT on
      ``embedding_model_config_id`` so a ModelConfig can't be
      hard-deleted while FAQs still reference it; SET NULL on
      ``created_by`` so a user deletion doesn't take the FAQ
      with it.
    - Indexes: ``knowledge_base_id`` (the hot filter for list
      endpoints), ``category`` (for the category-filter UI), and
      the composite ``(knowledge_base_id, category)`` to back the
      list-by-KB-and-category query the UI issues.

    Spec: docs/superpowers/specs/2026-06-17-faq-entry.md
    """
    if _table_exists("faq_entries"):
        # Table already exists (probably auto-created by ORM
        # create_all() on a dev DB that pre-dated this ensure
        # helper). Make sure the canonical index names exist —
        # SQLAlchemy's auto-named FK indexes use
        # ``ix_faq_entries_knowledge_base_id`` instead of the
        # shorter ``ix_faq_entries_kb`` we want for hot-path KB
        # filter queries, and we may be missing the composite
        # ``(knowledge_base_id, category)`` index entirely.
        with engine.begin() as conn:
            for idx_name, cols in (
                ("ix_faq_entries_kb", "(knowledge_base_id)"),
                ("ix_faq_entries_category", "(category)"),
                ("ix_faq_entries_kb_category", "(knowledge_base_id, category)"),
            ):
                if not _index_exists("faq_entries", idx_name):
                    conn.execute(text(
                        f"CREATE INDEX {idx_name} ON faq_entries {cols}"
                    ))
        return

    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE faq_entries ("
            "id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, "
            "knowledge_base_id INT NOT NULL, "
            "question TEXT NOT NULL, "
            "answer TEXT NOT NULL, "
            "category VARCHAR(50) NULL, "
            "tags JSON NULL, "
            "vector_id VARCHAR(100) NULL, "
            "document_id INT NOT NULL, "
            "chunk_id INT NOT NULL, "
            "embedding_model_config_id INT NULL, "
            "created_by INT NULL, "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
            "ON UPDATE CURRENT_TIMESTAMP, "
            "INDEX ix_faq_entries_kb (knowledge_base_id), "
            "INDEX ix_faq_entries_category (category), "
            "INDEX ix_faq_entries_kb_category (knowledge_base_id, category), "
            "CONSTRAINT fk_faq_entries_kb "
            "FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_bases(id) "
            "ON DELETE CASCADE, "
            "CONSTRAINT fk_faq_entries_document "
            "FOREIGN KEY (document_id) REFERENCES documents(id) "
            "ON DELETE CASCADE, "
            "CONSTRAINT fk_faq_entries_chunk "
            "FOREIGN KEY (chunk_id) REFERENCES document_chunks(id) "
            "ON DELETE CASCADE, "
            "CONSTRAINT fk_faq_entries_mc "
            "FOREIGN KEY (embedding_model_config_id) REFERENCES model_configs(id) "
            "ON DELETE RESTRICT, "
            "CONSTRAINT fk_faq_entries_user "
            "FOREIGN KEY (created_by) REFERENCES users(id) "
            "ON DELETE SET NULL"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        ))


# ---------------------------------------------------------------------------
# M32: 公众号助手 (WeChat Publisher) — 6 张表 wx_accounts / wx_templates /
# wx_drafts / wx_draft_sections / wx_materials / wx_publish_records
#
# Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3
#
# Each ensure_* follows the project house pattern:
#   1. ``Base.metadata.create_all`` for the table (idempotent — won't
#      touch an existing table) — this is the preferred path for NEW
#      tables because it picks up FKs, indexes, column types
#      (LONGTEXT/MEDIUMBLOB) and UniqueConstraints from the declarative
#      model in one shot.
#   2. Idempotent ``_index_exists`` guards for any composite/secondary
#      indexes not auto-emitted by ``create_all`` (none here — every
#      index is declared in the model's ``__table_args__``).
# ---------------------------------------------------------------------------


def ensure_wx_accounts_table() -> None:
    """M32: create ``wx_accounts`` table if missing.

    Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.1

    All indexes + the ``UNIQUE(tenant_id, app_id)`` constraint are
    declared in ``WxTemplate.__table_args__`` and are emitted by
    ``Base.metadata.create_all`` on a fresh DB, so this helper has
    nothing else to do.
    """
    from lumen_models.wx_publisher import WxAccount  # noqa
    Base.metadata.create_all(bind=engine, tables=[WxAccount.__table__])


def ensure_wx_templates_table() -> None:
    """M32: create ``wx_templates`` table if missing.

    Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.2
    """
    from lumen_models.wx_publisher import WxTemplate  # noqa
    Base.metadata.create_all(bind=engine, tables=[WxTemplate.__table__])


def ensure_wx_drafts_table() -> None:
    """M32: create ``wx_drafts`` table if missing.

    Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.3
    """
    from lumen_models.wx_publisher import WxDraft  # noqa
    Base.metadata.create_all(bind=engine, tables=[WxDraft.__table__])


def ensure_wx_draft_sections_table() -> None:
    """M32: create ``wx_draft_sections`` table if missing.

    Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.4

    The ``UNIQUE(draft_id, order_index)`` constraint is declared in
    ``WxDraftSection.__table_args__`` and emitted automatically.
    """
    from lumen_models.wx_publisher import WxDraftSection  # noqa
    Base.metadata.create_all(bind=engine, tables=[WxDraftSection.__table__])


def ensure_wx_materials_table() -> None:
    """M32: create ``wx_materials`` table if missing.

    Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.5
    """
    from lumen_models.wx_publisher import WxMaterial  # noqa
    Base.metadata.create_all(bind=engine, tables=[WxMaterial.__table__])


def ensure_wx_publish_records_table() -> None:
    """M32: create ``wx_publish_records`` table if missing.

    Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.6
    """
    from lumen_models.wx_publisher import WxPublishRecord  # noqa
    Base.metadata.create_all(bind=engine, tables=[WxPublishRecord.__table__])


# ---------------------------------------------------------------------------
# M33: 客户管理(CRM) - 3 张新表 customers / customer_follow_ups /
# customer_field_definitions。所有 INDEX + UNIQUE 都在 model.__table_args__
# 里声明,create_all 一次性建好。
# ---------------------------------------------------------------------------

def ensure_customers_table() -> None:
    """M33: create ``customers`` table if missing.

    Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.1
    """
    from lumen_models.customer import Customer  # noqa
    Base.metadata.create_all(bind=engine, tables=[Customer.__table__])


def ensure_customer_follow_ups_table() -> None:
    """M33: create ``customer_follow_ups`` table if missing.

    Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.2
    """
    from lumen_models.customer import CustomerFollowUp  # noqa
    Base.metadata.create_all(bind=engine, tables=[CustomerFollowUp.__table__])


def ensure_customer_field_definitions_table() -> None:
    """M33: create ``customer_field_definitions`` table if missing.

    Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.3
    """
    from lumen_models.customer import CustomerFieldDefinition  # noqa
    Base.metadata.create_all(bind=engine, tables=[CustomerFieldDefinition.__table__])


# --------------------------------------------------------------------------- #
# M33: Text2SQL (智能问数) — 2 张表                                            #
# --------------------------------------------------------------------------- #


def ensure_text2sql_data_sources_table() -> None:
    """M33: create ``text2sql_data_sources`` table if missing.

    Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.1
    """
    from lumen_models.text2sql import Text2SqlDataSource  # noqa
    Base.metadata.create_all(bind=engine, tables=[Text2SqlDataSource.__table__])


def ensure_text2sql_queries_table() -> None:
    """M33: create ``text2sql_queries`` table if missing.

    Must run AFTER ``ensure_text2sql_data_sources_table`` because
    ``text2sql_queries.data_source_id`` has a FK to
    ``text2sql_data_sources.id``.

    Idempotency: ``create_all`` is a no-op for tables that already
    exist with matching column types. The composite index
    ``ix_text2sql_queries_tenant_status_created`` is part of the
    model ``__table_args__`` so ``create_all`` creates it on a fresh
    DB; on an existing DB the helper is a no-op.
    """
    from lumen_models.text2sql import Text2SqlQuery  # noqa
    Base.metadata.create_all(bind=engine, tables=[Text2SqlQuery.__table__])


# --------------------------------------------------------------------------- #
# M34: Platform-wide system KV config (skill_http_allowed_domains + future) #
# --------------------------------------------------------------------------- #


# Default HTTP allowlist seeded into SystemConfig on first startup.
# Mirrors the 3 free public APIs the marketplace ships by default in the
# same PR (weather / forex / short-URL). Operators may add/remove
# domains via SQL; this seed only fires when the row is missing, so it
# never clobbers a manually-edited list.
_DEFAULT_SKILL_HTTP_ALLOWED_DOMAINS = [
    "api.open-meteo.com",
    "api.frankfurter.app",
    "is.gd",
]


def ensure_system_configs_table() -> None:
    """M34: create ``system_configs`` table if missing.

    Used by ``HttpExecutor._resolve_allowed_domains`` to gate M16 HTTP
    skills against an SSRF allowlist. Also seeds the default
    ``skill_http_allowed_domains`` row on first startup when the row is
    absent (idempotent: existing rows are left untouched so manual
    operator edits survive a backend restart).

    Idempotency: ``create_all`` is a no-op when the table + columns
    already exist with matching types. The seed uses an
    ``INSERT ... ON DUPLICATE KEY UPDATE`` style guard at the Python
    layer (check-then-insert) because the value payload is JSON and we
    don't want it to drift if an operator ever hand-edits.
    """
    from lumen_models.system_config import SystemConfig  # noqa

    Base.metadata.create_all(bind=engine, tables=[SystemConfig.__table__])

    db = SessionLocal()
    try:
        existing = (
            db.query(SystemConfig)
            .filter(SystemConfig.key == "skill_http_allowed_domains")
            .first()
        )
        if existing is None:
            db.add(SystemConfig(
                key="skill_http_allowed_domains",
                value=list(_DEFAULT_SKILL_HTTP_ALLOWED_DOMAINS),
            ))
            db.commit()
    finally:
        db.close()


def ensure_skills_tenant_id() -> None:
    """Skill 表添加 tenant_id 列（nullable）+ 索引。

    - tenant_id = NULL  → 内置技能，平台可见，各租户只能读不能写
    - tenant_id = N     → 租户 N 的自定义技能，只有 N 能读写

    幂等：列已存在时为 no-op。
    已安装的自定义技能（名字含 _{数字} 结尾）从名字解析 tenant_id；
    内置技能保持 tenant_id = NULL。
    """
    with engine.connect() as conn:
        if not _column_exists("skills", "tenant_id"):
            conn.execute(text("ALTER TABLE skills ADD COLUMN tenant_id INT NULL"))
            conn.execute(text("CREATE INDEX ix_skills_tenant_id ON skills(tenant_id)"))
            conn.commit()

        # 回填已安装自定义技能的 tenant_id（名字如 xxx_5 → tenant_id=5）
        conn.execute(text("""
            UPDATE skills
            SET tenant_id = CAST(SUBSTRING_INDEX(name, '_', -1) AS UNSIGNED)
            WHERE tenant_id IS NULL
              AND is_builtin = FALSE
              AND name REGEXP '_[0-9]+$'
              AND SUBSTRING_INDEX(name, '_', -1) REGEXP '^[0-9]+$'
        """))
        conn.commit()


def ensure_skill_type_column() -> None:
    """Skill 表添加 type 列（默认 'prompt'）。

    - prompt = LLM 调用型技能（渲染后送 LLM）
    - script = Python 脚本型技能（SkillScriptExecutor 执行）

    幂等：列已存在时为 no-op。现有行的 type 默认填 'prompt'。
    """
    with engine.connect() as conn:
        if not _column_exists("skills", "type"):
            conn.execute(text(
                "ALTER TABLE skills ADD COLUMN type VARCHAR(20) NOT NULL DEFAULT 'prompt'"
            ))
            conn.commit()


def ensure_eval_datasets_table() -> None:
    """M37.1: create the eval_datasets + eval_dataset_items tables for the
    RAG evaluation suite.

    Mirrors the M22/M35/M36.2.1 ensure_* pattern — Base.metadata.create_all
    is idempotent, so re-running on every uvicorn boot is a clean no-op.

    Why ``Base.metadata.create_all(bind=engine)`` (no ``tables=[...]``):

    ``EvalDataset`` carries FKs to ``knowledge_bases`` / ``tenants`` /
    ``users``, and ``EvalDatasetItem`` FKs to ``eval_datasets``. When
    ``tables=[...]`` is passed, SQLAlchemy's FK resolver only sees the
    explicitly-listed tables and raises
    ``NoReferencedTableError: Foreign key ... could not find table
    'knowledge_bases'`` even if the referenced model is already
    registered on ``Base.metadata``. The existing ``create_tables()``
    helper (line 18) already runs ``create_all(bind=engine)`` with no
    ``tables`` arg as the canonical "make sure every declared model
    exists" entry point; calling the same here keeps the behaviour
    consistent (idempotent: ``CREATE TABLE IF NOT EXISTS`` for each
    declared table — no-op for the ~50 existing tables, real DDL for
    the two new M37 tables). It does require the caller to have
    imported all ORM modules before calling — ``lumen_main.py``
    imports them at lines 67-110.

    Schema notes:

    - ``eval_datasets`` is the parent table; ``eval_dataset_items`` is
      the child (one dataset → N items). FK CASCADE so deleting a
      dataset sweeps its items, and deleting a KB sweeps its datasets
      (golden queries become meaningless without the underlying KB).
    - ``expected_doc_ids`` (JSON list of int) lets the user express
      partial relevance: "doc 42 must be in top-3, doc 17 must be in
      top-10". The runner materialises this into a binary relevance
      set for Hit@K / MRR / NDCG.
    - ``answer_keywords`` is for the cheap ``keyword_hit_rate`` answer
      metric; LLM judge (faithfulness / answer_relevancy) kicks in only
      when ``expected_answer`` is set.
    - The composite indexes ``ix_eval_datasets_kb_active`` and
      ``ix_eval_dataset_items_ds_category`` are declared on the model
      ``__table_args__`` and created automatically by create_all —
      they back the list-by-KB and slice-by-category dashboard queries.

    Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
    """
    from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem  # noqa
    Base.metadata.create_all(bind=engine)


def ensure_eval_runs_table() -> None:
    """M37.2: create the eval_runs + eval_run_results tables for the
    RAG evaluation runner.

    Mirrors the M22/M35/M36.2.1/M37.1 ensure_* pattern — Base.metadata.create_all
    is idempotent. Same FK resolution caveat as ``ensure_eval_datasets_table``:
    we call ``create_all(bind=engine)`` (no ``tables=[...]``) so all referenced
    tables (eval_datasets, users, eval_dataset_items) get included in the FK
    resolver's view, regardless of whether they're explicitly listed.

    Schema notes (per spec §4.2):

    - ``eval_runs`` holds one row per evaluation run; ``eval_run_results``
      holds one row per item that the runner touches (including failed
      ones — we keep the row + ``error_message`` so the dashboard can
      surface partial completion).
    - FK ``run_id → eval_runs.id ON DELETE CASCADE`` so deleting a run
      sweeps its results; ``item_id → eval_dataset_items.id ON DELETE
      CASCADE`` so deleting an item (rare; usually via dataset CASCADE)
      doesn't leave orphan result rows pointing at dead item ids.
    - ``created_by → users.id ON DELETE SET NULL`` — we keep the run even
      if its creator is removed (audit / dashboard view "who ran what"
      tolerates the NULL).
    - ``status`` is ``String(20)`` not MySQL ENUM (project-wide
      convention since video/text2sql/wx_publisher) — adding a new state
      is a no-ALTER change, only the docstring on the ORM lists the
      valid values.
    - ``config_json`` / ``metrics_json`` / ``llm_judge_calls`` are
      ``Column(JSON)``; the API layer validates the shape via Pydantic
      schemas (EvalRunConfig / RetrievalMetrics / AnswerMetrics).
    - ``trace_id`` (VARCHAR(36)) joins to ``llm_call_logs.trace_id`` /
      ``embedding_call_logs.trace_id`` so the M37.3 dashboard can jump
      from a run row to its full LLM/embedding trace.

    Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
    Plan: docs-internal/superpowers/plans/m37-plan.md CP3 T8
    """
    # 预加载所有被 FK 引用的父表 —— EvalRun.dataset_id → eval_datasets,
    # EvalRun.created_by → users, EvalRunResult.run_id → eval_runs,
    # EvalRunResult.item_id → eval_dataset_items。裸 import EvalRun /
    # EvalRunResult 时 Base.metadata 看不到父表, SQLAlchemy FK sort 阶段
    # 会 NoReferencedTableError。
    # 同 ensure_eval_datasets_table 的套路 (line 1826-1839)。
    from lumen_models.user import User  # noqa: F401
    from lumen_models.tenant import Tenant  # noqa: F401
    from lumen_models.knowledge import KnowledgeBase  # noqa: F401
    from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem  # noqa: F401
    from lumen_models.eval_run import EvalRun, EvalRunResult  # noqa: F401
    Base.metadata.create_all(bind=engine)
