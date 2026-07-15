"""Static SQL safety layer for the text2sql engine.

The LLM can (and will) produce SQL we don't want to run. This module
is the *single* gate that decides whether a piece of SQL is allowed
to be executed against the production database. It runs in three
phases:

1. **Parse** (``parse``) — use ``sqlparse`` to tokenize and
   classify the SQL. We keep only the first statement (multi-statement
   payloads are a common injection pattern).
2. **Validate** (``validate_select_only``) — refuse anything that
   isn't a ``SELECT`` or ``WITH ... SELECT``. The blocklist is
   explicit (``INSERT``, ``UPDATE``, ``DELETE``, ``DROP``, ``ALTER``,
   ``TRUNCATE``, ``CREATE``, ``GRANT``, ``REVOKE``, ``SET``, ``BEGIN``,
   ``COMMIT``, ``CALL``, ``EXEC``, ``LOCK``, ``USE``, ``RENAME``) so
   the rejection is auditable and not a vibe check.
3. **Rewrite** (``wrap_with_limit`` / ``inject_timeout``) — even
   when the SQL is a ``SELECT``, we still need to bound the damage.
   - Auto-append ``LIMIT max_rows`` if missing or larger than the cap.
   - Inject ``/*+ MAX_EXECUTION_TIME(N) */`` after the first SELECT
     so MySQL bails out at the optimizer level.

The validators for table / column references are kept separate from
``validate_select_only`` because they need a ``SchemaInspector`` —
the caller decides whether to apply per-source allowlists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import sqlparse
from sqlparse.sql import (
    Comparison,
    Function,
    Identifier,
    IdentifierList,
    Parenthesis,
    Statement,
    Where,
)
from sqlparse.tokens import Keyword

from lumen_services.text2sql.schema_inspector import SchemaInspector


# Blocked top-level statement types. Anything in this set causes
# ``validate_select_only`` to return (False, "<type> not allowed").
# The set is conservative: better to reject a slightly weird but
# legitimate query than to let a DDL/DML slip through.
_BLOCKED_TYPES: Set[str] = {
    "INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE",
    "DROP", "ALTER", "TRUNCATE", "CREATE", "RENAME",
    "GRANT", "REVOKE",
    "SET", "BEGIN", "COMMIT", "ROLLBACK", "START",
    "CALL", "EXEC", "EXECUTE",
    "LOCK", "UNLOCK", "USE",
    "EXPLAIN",  # not destructive but we want the LLM to call us, not explain
    "ANALYZE", "OPTIMIZE", "REPAIR", "CHECK", "CHECKSUM",
    "HANDLER", "LOAD", "BINLOG", "DO",
    "SHOW", "DESCRIBE", "DESC",  # info-schema leakage
}

# Allowed top-level statement types (only SELECT / WITH).
_ALLOWED_DML: Set[str] = {"SELECT"}

# Pattern to find the LIMIT clause (case-insensitive). We anchor to
# end-of-string so we don't accidentally match a subquery's LIMIT.
_LIMIT_RE = re.compile(
    r"\bLIMIT\s+(\d+)(?:\s+OFFSET\s+\d+)?\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)

# Pattern to strip trailing semicolons.
_TRAILING_SEMI = re.compile(r";\s*$")

# Pattern to find the first SELECT/WITH in the body (for MAX_EXECUTION_TIME
# injection).
_FIRST_SELECT_RE = re.compile(r"\b(SELECT)\b", re.IGNORECASE)

# Keywords that, when seen as the *next* token after FROM/JOIN, end
# the table list.
_END_TABLE_LIST = {
    "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET",
    "UNION", "INTERSECT", "EXCEPT", "RETURNING",
    "ON", "USING", "SET", "INTO",
}


@dataclass(frozen=True)
class GuardResult:
    """Outcome of a single guard check.

    Attributes:
        ok: ``True`` when the check passed.
        error_type: short machine-readable category; one of
            ``"parse"``, ``"blocklist"``, ``"table"``, ``"field"``,
            ``"limit"`` or ``None`` when ok.
        error_message: human-readable detail, included in the
            ``Text2SqlQuery.error_message`` column.
    """

    ok: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None


class SQLGuard:
    """Static SQL safety checks.

    Args:
        inspector: ``SchemaInspector`` for the same database. The guard
            delegates table / column existence checks to it.
        table_allowlist: optional set of allowed table names (lowercase).
            When ``None``/empty, all non-meta tables are allowed.
        field_allowlist: optional mapping of ``{table_name: [col_name]}``.
            When a table is in this mapping, only the listed columns
            pass column validation.
    """

    def __init__(
        self,
        inspector: SchemaInspector,
        table_allowlist: Optional[Sequence[str]] = None,
        field_allowlist: Optional[Dict[str, Sequence[str]]] = None,
    ) -> None:
        self.inspector = inspector
        self.table_allowlist_norm: Optional[Set[str]] = (
            {n.lower() for n in table_allowlist} if table_allowlist else None
        )
        self.field_allowlist_norm: Optional[Dict[str, Set[str]]] = None
        if field_allowlist:
            self.field_allowlist_norm = {
                k.lower(): {c.lower() for c in v}
                for k, v in field_allowlist.items()
            }

    # ------------------------------------------------------------------ #
    # Parse                                                                #
    # ------------------------------------------------------------------ #

    def parse(self, sql: str) -> Tuple[Optional[Statement], Optional[str]]:
        """Parse ``sql`` and return the first statement (or None on error)."""
        if not sql or not sql.strip():
            return None, "SQL is empty"
        try:
            stmts = [s for s in sqlparse.split(sql) if s.strip()]
        except Exception as exc:  # sqlparse raises ValueError on weird unicode
            return None, f"SQL parse error: {exc}"
        if not stmts:
            return None, "SQL is empty"
        parsed = sqlparse.parse(stmts[0])
        if not parsed:
            return None, "SQL is empty"
        stmt = parsed[0]
        if (stmt.get_type() or "UNKNOWN").upper() == "UNKNOWN" and not _has_select_keyword(stmt):
            return None, "SQL could not be classified"
        return stmt, None

    # ------------------------------------------------------------------ #
    # Validate                                                             #
    # ------------------------------------------------------------------ #

    def validate_select_only(self, stmt: Statement) -> GuardResult:
        """Reject anything that isn't a SELECT or WITH...SELECT."""
        stmt_type = (stmt.get_type() or "UNKNOWN").upper()
        if stmt_type in _ALLOWED_DML or stmt_type == "WITH":
            return GuardResult(ok=True)
        if stmt_type in _BLOCKED_TYPES:
            return GuardResult(
                ok=False,
                error_type="blocklist",
                error_message=(
                    f"Statement type {stmt_type!r} is not allowed; "
                    f"only SELECT/WITH are permitted"
                ),
            )
        if not _has_select_keyword(stmt):
            return GuardResult(
                ok=False,
                error_type="blocklist",
                error_message=(
                    f"Statement type {stmt_type!r} is not allowed; "
                    f"only SELECT/WITH are permitted"
                ),
            )
        return GuardResult(ok=True)

    def extract_tables(self, stmt: Statement) -> List[str]:
        """Return the list of table names referenced in FROM / JOIN / INTO.

        We walk the top-level token stream (NOT ``flatten()``) so that
        ``Identifier`` / ``IdentifierList`` parents are visible — the
        leaf-level ``flatten()`` strips them down to bare ``Token.Name``
        tokens which lack the parent metadata we need.
        """
        tables: List[str] = []
        # Track whether the next non-keyword token we see is a table ref.
        # The state is set to the keyword that opened the table list
        # (``from`` / ``join`` / ``into``) and cleared by any other
        # top-level token (LIMIT, WHERE, etc.).
        state: Optional[str] = None
        for tok in stmt.tokens:
            ttype = tok.ttype
            upper = tok.value.upper().strip() if ttype is Keyword else None
            if upper in {"FROM", "INTO"}:
                state = "from" if upper == "FROM" else "into"
                continue
            if upper == "JOIN":
                state = "join"
                continue
            if upper in _END_TABLE_LIST:
                state = None
                continue
            if state is None:
                continue
            if isinstance(tok, IdentifierList):
                for ident in tok.get_identifiers():
                    self._collect_table_name(ident, tables)
            elif isinstance(tok, (Identifier, Function)):
                self._collect_table_name(tok, tables)
            else:
                # Whitespace / Punctuation / etc. — skip, but if we see
                # a bare word after a FROM it might be a table name that
                # sqlparse didn't wrap in an Identifier (rare but seen
                # with some unformatted LLM output).
                if ttype is None and tok.value and tok.value.strip():
                    word = tok.value.strip().strip("`\"';,")
                    if word and word.upper() not in {
                        "SELECT", "WHERE", "ON", "USING", "AND", "OR",
                    }:
                        # Best effort: treat it as a table reference.
                        # SQLGuard's validate_tables will reject the bad
                        # ones against INFORMATION_SCHEMA.
                        tables.append(word)
        return tables

    @staticmethod
    def _collect_table_name(ident: Any, tables: List[str]) -> None:
        """Append the table name from one ``Identifier`` to ``tables``."""
        # An Identifier may be ``users`` (just a name) or
        # ``users u`` (name + alias) or ``schema.users`` (catalog + name).
        name = ident.get_real_name() or ident.get_name() or ""
        if not name:
            # Fallback: pull the first non-whitespace leaf.
            for inner in ident.tokens:
                if inner.ttype in (None,) and inner.value and not inner.value.isspace():
                    name = inner.value.strip("`\"' ")
                    break
        if name:
            tables.append(name.strip("`\"' "))

    def extract_columns(self, stmt: Statement) -> List[Tuple[str, str]]:
        """Return ``[(table, column)]`` for every column reference.

        For unqualified columns (just ``name``), ``table`` is the
        empty string.
        """
        pairs: List[Tuple[str, str]] = []
        seen: Set[Tuple[str, str]] = set()

        def _walk_ident(ident: Any) -> None:
            if not isinstance(ident, Identifier):
                return
            name = ident.get_real_name() or ident.get_name() or ""
            parent = ident.get_parent_name() or ""
            if not name:
                return
            key = (parent.lower(), name.lower())
            if key in seen:
                return
            seen.add(key)
            pairs.append((parent, name))

        # SELECT list — top-level identifiers and Function arguments
        for tok in stmt.tokens:
            if isinstance(tok, Function):
                for inner in tok.tokens:
                    if isinstance(inner, Identifier):
                        _walk_ident(inner)
            elif isinstance(tok, Identifier):
                _walk_ident(tok)

        # WHERE / ON / USING — Comparison and bare identifiers
        for tok in stmt.tokens:
            if isinstance(tok, Where):
                for inner in tok.tokens:
                    if isinstance(inner, Comparison):
                        for leaf in inner.tokens:
                            if isinstance(leaf, Identifier):
                                _walk_ident(leaf)
                    elif isinstance(inner, Identifier):
                        _walk_ident(inner)
            elif isinstance(tok, Parenthesis):
                for inner in tok.tokens:
                    if isinstance(inner, Comparison):
                        for leaf in inner.tokens:
                            if isinstance(leaf, Identifier):
                                _walk_ident(leaf)
                    elif isinstance(inner, Identifier):
                        _walk_ident(inner)
        return pairs

    def validate_columns(
        self,
        stmt: Statement,
        pairs: List[Tuple[str, str]],
    ) -> GuardResult:
        """Ensure every ``(table, column)`` pair is in scope.

        Unqualified columns are checked against the field allowlists
        of the FROM-clause tables. We don't do full FROM-binding
        resolution — that's the LLM's responsibility — but the
        per-table allowlist still catches the common case (e.g. the
        data source only allows a subset of columns for a sensitive
        table).
        """
        from collections import defaultdict
        by_table: Dict[str, List[str]] = defaultdict(list)
        for table, col in pairs:
            by_table[table.lower()].append(col)

        from_tables = [t.lower() for t in self.extract_tables(stmt)]

        # Qualified columns: every (table, col) must be in scope.
        for table, cols in by_table.items():
            if not table:
                continue
            if not self.inspector.validate_table(table):
                return GuardResult(
                    ok=False,
                    error_type="table",
                    error_message=f"Table {table!r} does not exist or is not allowed",
                )
            allow = (
                self.field_allowlist_norm.get(table)
                if self.field_allowlist_norm
                else None
            )
            if allow is None:
                continue
            for c in cols:
                if c.lower() not in allow:
                    return GuardResult(
                        ok=False,
                        error_type="field",
                        error_message=(
                            f"Column {c!r} is not in the field allowlist "
                            f"for table {table!r}"
                        ),
                    )

        # Unqualified columns: if any from-clause table has a
        # field allowlist configured, the column must appear in the
        # *intersection* of those allowlists. With no allowlist on
        # any from-table, the reference is accepted.
        if "" in by_table:
            unqualified = by_table[""]
            restrictions = [
                self.field_allowlist_norm[t]
                for t in from_tables
                if self.field_allowlist_norm and t in self.field_allowlist_norm
            ]
            if restrictions:
                allowed = set.intersection(*restrictions) if restrictions else set()
                for c in unqualified:
                    if c.lower() not in allowed:
                        return GuardResult(
                            ok=False,
                            error_type="field",
                            error_message=(
                                f"Column {c!r} is not in the field allowlist "
                                f"for the FROM-clause tables"
                            ),
                        )
        return GuardResult(ok=True)

    def validate_tables(self, tables: Iterable[str]) -> GuardResult:
        """Ensure every table reference is a real, non-meta table in scope."""
        for raw in tables:
            t = raw.strip("`\"' ")
            if not t:
                continue
            if not self.inspector.validate_table(t):
                return GuardResult(
                    ok=False,
                    error_type="table",
                    error_message=f"Table {t!r} does not exist or is not allowed",
                )
            if (
                self.table_allowlist_norm is not None
                and t.lower() not in self.table_allowlist_norm
            ):
                return GuardResult(
                    ok=False,
                    error_type="table",
                    error_message=(
                        f"Table {t!r} is not in the data source's "
                        f"table allowlist"
                    ),
                )
        return GuardResult(ok=True)

    # ------------------------------------------------------------------ #
    # Rewrite                                                              #
    # ------------------------------------------------------------------ #

    def wrap_with_limit(self, sql: str, max_rows: int) -> str:
        """Ensure ``sql`` has a ``LIMIT`` no larger than ``max_rows``."""
        if max_rows <= 0:
            return sql
        stripped = _TRAILING_SEMI.sub("", sql.rstrip())
        m = _LIMIT_RE.search(stripped)
        if m is None:
            return f"{stripped} LIMIT {int(max_rows)}"
        existing = int(m.group(1))
        if existing > max_rows:
            return (
                f"{stripped[: m.start(1)]}{int(max_rows)}"
                f"{stripped[m.end(1): ]}"
            )
        return sql

    def inject_timeout(self, sql: str, timeout_ms: int) -> str:
        """Insert ``/*+ MAX_EXECUTION_TIME(N) */`` after the first SELECT."""
        if timeout_ms <= 0:
            return sql
        if "MAX_EXECUTION_TIME(" in sql:
            return sql
        m = _FIRST_SELECT_RE.search(sql)
        if m is None:
            return sql
        hint = f" /*+ MAX_EXECUTION_TIME({int(timeout_ms)}) */ "
        return sql[: m.end(1)] + hint + sql[m.end(1): ]

    # ------------------------------------------------------------------ #
    # Run all checks at once                                               #
    # ------------------------------------------------------------------ #

    def run(
        self,
        sql: str,
        *,
        max_rows: int = 100,
        timeout_ms: int = 5000,
        enforce_columns: bool = True,
    ) -> Tuple[Optional[str], Optional[GuardResult]]:
        """Run the full pipeline and return ``(rewritten_sql, error)``."""
        stmt, err = self.parse(sql)
        if err is not None:
            return None, GuardResult(ok=False, error_type="parse", error_message=err)
        # ``parse`` returns None on unrecoverable parse errors, but
        # by this point stmt is always a real Statement or we
        # already returned above.
        assert stmt is not None
        kind = self.validate_select_only(stmt)
        if not kind.ok:
            return None, kind
        tables = self.extract_tables(stmt)
        kind = self.validate_tables(tables)
        if not kind.ok:
            return None, kind
        if enforce_columns:
            columns = self.extract_columns(stmt)
            kind = self.validate_columns(stmt, columns)
            if not kind.ok:
                return None, kind
        rewritten = self.wrap_with_limit(sql, max_rows)
        rewritten = self.inject_timeout(rewritten, timeout_ms)
        return rewritten, None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _has_select_keyword(stmt: Statement) -> bool:
    """True when the statement body contains a SELECT or WITH keyword."""
    for tok in stmt.flatten():
        if tok.ttype is Keyword and tok.value.upper() in {"SELECT", "WITH"}:
            return True
    return False
