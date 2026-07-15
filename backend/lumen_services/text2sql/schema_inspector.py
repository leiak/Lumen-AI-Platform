"""Read the MySQL INFORMATION_SCHEMA for the text2sql engine.

The LLM needs a *ground-truth* description of the database schema to
generate correct SQL. We can't feed it ``SHOW TABLES`` output because
the data is scattered across many tables and the LLM would have to
reverse-engineer the column types from comments. Instead, we read
``INFORMATION_SCHEMA.TABLES`` and ``INFORMATION_SCHEMA.COLUMNS``
directly and produce a deterministic, compact schema text that goes
into the system prompt.

Why a dedicated module (instead of using ``sqlalchemy.inspect``)?

- We need to *exclude* the ``text2sql_*`` metadata tables themselves
  (they describe the text2sql feature, not business data).
- The LLM doesn't need the full TEXT/MEDIUMTEXT column types; the
  compact format keeps the prompt under control.
- We support a per-source ``table_allowlist`` / ``field_allowlist``
  that filters the schema to what the user is allowed to query.
- We need to *validate* SQLGuard's output: when the LLM emits
  ``SELECT * FROM foo``, the SchemaInspector says whether ``foo`` is
  in scope and what columns it has. The validation function
  ``validate_table`` / ``validate_field`` is a tight loop, not a
  general inspector.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session


# Internal tables that the LLM must never see or query. They hold
# M33's own bookkeeping (datasources, queries, generated SQL audit)
# and exposing them to the LLM would be both noisy and a security
# foot-gun (an attacker could trick the LLM into reading the audit
# log).
_META_TABLE_PREFIXES: Tuple[str, ...] = ("text2sql_",)

# Same idea for obvious Laravel-style metadata tables if they ever
# get added. The set is conservative — we only block what we know
# exists or what an LLM could be tricked into querying.
_OTHER_HIDDEN_TABLES: Set[str] = {
    "alembic_version",  # Alembic migration tracking
}


def _is_meta_table(name: str) -> bool:
    """Return True if the table should be hidden from the LLM."""
    lower = name.lower()
    if any(lower.startswith(p) for p in _META_TABLE_PREFIXES):
        return True
    return lower in _OTHER_HIDDEN_TABLES


class SchemaInspector:
    """Read INFORMATION_SCHEMA for the configured database.

    Args:
        db: an open ``Session`` (typically ``SessionLocal()``) for the
            ai_platform MySQL database. The inspector uses ``text()``
            SQL directly — SQLAlchemy ORM isn't relevant here because
            we want to read the *catalog* tables, not the application
            tables.
        db_name: logical name (e.g. ``"ai_platform"``). Today the value
            is informational only — every project reads from the
            current database — but we keep the parameter for future
            read-replica routing.
    """

    def __init__(self, db: Session, db_name: str = "ai_platform") -> None:
        self.db = db
        self.db_name = db_name

    # ------------------------------------------------------------------ #
    # Read paths (used by the engine to build the prompt)                 #
    # ------------------------------------------------------------------ #

    def list_tables(
        self,
        allowlist: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return ``[{name, comment}]`` for every visible table.

        Meta tables (``text2sql_*``, ``alembic_version``) are always
        excluded. If ``allowlist`` is provided, only those names are
        kept (case-insensitive). The result is sorted by name for
        prompt determinism.
        """
        allow_norm = (
            {n.lower() for n in allowlist} if allowlist is not None else None
        )
        rows = self.db.execute(
            text(
                "SELECT TABLE_NAME, IFNULL(TABLE_COMMENT, '') AS TABLE_COMMENT "
                "FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_TYPE = 'BASE TABLE'"
            )
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for name, comment in rows:
            if _is_meta_table(name):
                continue
            if allow_norm is not None and name.lower() not in allow_norm:
                continue
            out.append({"name": name, "comment": comment or ""})
        out.sort(key=lambda d: d["name"])
        return out

    def get_table_schema(
        self,
        table_name: str,
        field_allowlist: Optional[Sequence[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return ``[{name, type, nullable, key, default, comment}]`` for one table.

        ``key`` is ``"PRI"`` for primary keys, ``"UNI"`` for unique,
        ``"MUL"`` for the first column of a non-unique index. ``default``
        and ``comment`` come from INFORMATION_SCHEMA.COLUMNS (string
        form; LLM doesn't need the typed form).
        """
        field_norm = (
            {n.lower() for n in field_allowlist}
            if field_allowlist is not None
            else None
        )
        # Column metadata
        col_rows = self.db.execute(
            text(
                "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, IS_NULLABLE, "
                "       IFNULL(COLUMN_DEFAULT, '') AS COLUMN_DEFAULT, "
                "       IFNULL(COLUMN_COMMENT, '') AS COLUMN_COMMENT, "
                "       COLUMN_KEY, ORDINAL_POSITION "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t "
                "ORDER BY ORDINAL_POSITION"
            ),
            {"t": table_name},
        ).fetchall()
        cols: List[Dict[str, Any]] = []
        for (
            col_name,
            data_type,
            col_type,
            is_nullable,
            default,
            comment,
            key,
            _ordinal,
        ) in col_rows:
            if field_norm is not None and col_name.lower() not in field_norm:
                continue
            cols.append(
                {
                    "name": col_name,
                    "type": col_type or data_type,
                    "nullable": (is_nullable or "NO").upper() == "YES",
                    "key": key or "",
                    "default": default or "",
                    "comment": comment or "",
                }
            )
        return cols

    def get_full_schema_text(
        self,
        table_allowlist: Optional[Sequence[str]] = None,
        field_allowlist: Optional[Dict[str, Sequence[str]]] = None,
    ) -> str:
        """Return a compact, deterministic multi-line schema text.

        Format (one table per block, columns indented with two spaces)::

            # customers
            #   业务客户表
            #   id BIGINT NOT NULL  [PRI]
            #   name VARCHAR(100) NOT NULL
            #   created_at DATETIME NOT NULL

        The text is fed verbatim into the system prompt. The hash
        (line-by-line) is what we log in LLMCallLog ``extra`` for
        cache hit rate analysis.
        """
        if field_allowlist is None:
            field_allowlist = {}
        tables = self.list_tables(allowlist=table_allowlist)
        blocks: List[str] = []
        for t in tables:
            # Header line — e.g. ``# users`` — always emitted.
            blocks.append(f"# {t['name']}")
            if t["comment"]:
                blocks.append(f"#   {t['comment']}")
            cols = self.get_table_schema(
                t["name"],
                field_allowlist=field_allowlist.get(t["name"]),
            )
            for c in cols:
                null_str = "NULL" if c["nullable"] else "NOT NULL"
                key_str = f"  [{c['key']}]" if c["key"] else ""
                default_str = f"  default={c['default']}" if c["default"] else ""
                col_line = f"#   {c['name']} {c['type']} {null_str}{key_str}{default_str}"
                if c["comment"]:
                    col_line += f"  -- {c['comment']}"
                blocks.append(col_line)
            if not cols:
                blocks.append("#   (no accessible columns)")
            # blank line between tables
            blocks.append("")
        return "\n".join(blocks).rstrip()

    # ------------------------------------------------------------------ #
    # Validation (used by SQLGuard; also exposed to the service layer)    #
    # ------------------------------------------------------------------ #

    def validate_table(self, table_name: str) -> bool:
        """Return True if ``table_name`` exists, is a base table, and is
        not a meta table.

        Case-insensitive — MySQL's default collation is case-insensitive
        on identifiers, so ``Customers`` and ``customers`` refer to the
        same table. We normalise to lower for the comparison.
        """
        row = self.db.execute(
            text(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
                "AND LOWER(TABLE_NAME) = LOWER(:t)"
            ),
            {"t": table_name},
        ).fetchone()
        if not row:
            return False
        return not _is_meta_table(row[0])

    def validate_field(self, table_name: str, column_name: str) -> bool:
        """Return True if ``column_name`` exists on ``table_name``.

        Both are matched case-insensitively. The check is two-step:
        the table must exist (avoid silent false positives for typos
        like ``customer`` vs ``customers``) AND the column must be in
        INFORMATION_SCHEMA.COLUMNS.
        """
        row = self.db.execute(
            text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND LOWER(TABLE_NAME) = LOWER(:t) "
                "AND LOWER(COLUMN_NAME) = LOWER(:c) "
                "LIMIT 1"
            ),
            {"t": table_name, "c": column_name},
        ).fetchone()
        return row is not None

    def list_all_columns(self, table_name: str) -> List[str]:
        """Return column names (original case) for a table.

        Used by SQLGuard's column validator when a per-table field
        allowlist is configured — we need the full list to apply
        the per-table filter and report a useful error.
        """
        rows = self.db.execute(
            text(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
            ),
            {"t": table_name},
        ).fetchall()
        return [r[0] for r in rows]
